# pyright: basic
"""Rigenera i dati ISTAT del package ``crime_risk_analyzer.istat`` (#345, spec 4.1).

Script MANUALE (D2): l'app non chiama mai ISTAT a runtime. Riscarica i valori del
dataset 73_67 per l'anno di riferimento e per dieci anni prima e riscrive
``delitti.json``; con ``--confini`` rigenera anche ``luoghi.json`` dai confini
amministrativi generalizzati ISTAT.

Uso (dalla cartella ``backend``)::

    uv run python scripts/istat_refresh.py            # solo delitti.json
    uv run python scripts/istat_refresh.py --confini  # anche luoghi.json

Le librerie geometriche (pyshp, pyproj, shapely) sono dipendenze del solo gruppo
``dev``: sono importate dentro le funzioni dei confini, cosi' il runtime del
package non ne dipende e la parte dei delitti gira anche senza.

``# pyright: basic`` in testa: pyshp e shapely non hanno tipi completi e in modalita'
strict ogni chiamata sarebbe un ``reportUnknownMemberType``; lo script non fa parte
del package e non gira in produzione.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import httpx

from crime_risk_analyzer.istat.mappatura import MAPPATURA

#: Anno di riferimento ``Y`` e anno di confronto ``Y-10`` (spec 3).
ANNO = 2024
ANNO_CONFRONTO = ANNO - 10

DATASET = "73_67"
TITOLO = "Delitti denunciati dalle forze di polizia all'autorità giudiziaria"
LICENZA = "CC BY 4.0"
URL_DATI = (
    "https://esploradati.istat.it/SDMXWS/rest/data/IT1,73_67,1.0/"
    "A..CRIMEN+CRIMET..9.YRDUR?startPeriod={inizio}&endPeriod={fine}&format=csv"
)
URL_STRUTTURA = (
    "https://esploradati.istat.it/SDMXWS/rest/dataflow/IT1/73_67/1.0?references=all"
)
URL_CONFINI_2024 = (
    "https://www.istat.it/storage/cartografia/confini_amministrativi/"
    "generalizzati/2024/Limiti01012024_g.zip"
)
URL_CONFINI_2001 = (
    "https://www.istat.it/storage/cartografia/confini_amministrativi/"
    "generalizzati/Limiti2001_g.zip"
)

#: Codice dell'Italia nel dataset.
CODICE_ITALIA = "IT"
#: Voce del totale dei delitti (cornice, D10).
VOCE_TOTALE = "TOT"
#: Flag ISTAT "il dato non raggiunge la metà della cifra minima considerata":
#: tasso mostrato come "meno di 0,1 ogni 100.000 abitanti" (spec 3).
FLAG_SOTTO_SOGLIA = "0"

#: Codice provincia ISTAT (COD_PROV dei confini 2024) -> codice NUTS3 del dataset.
#: Costruita confrontando i nomi della codelist CL_ITTER107 con DEN_UTS dei confini
#: 2024 e verificata dallo script a ogni rigenerazione (:func:`verifica_nomi`). Le
#: quattro province sarde storiche NON sono qui: vedi :data:`SARDEGNA_2001`.
PROVINCIA_NUTS: dict[int, str] = {
    1: "ITC11",
    2: "ITC12",
    3: "ITC15",
    4: "ITC16",
    5: "ITC17",
    6: "ITC18",
    7: "ITC20",
    8: "ITC31",
    9: "ITC32",
    10: "ITC33",
    11: "ITC34",
    12: "ITC41",
    13: "ITC42",
    14: "ITC44",
    15: "ITC45",
    16: "ITC46",
    17: "ITC47",
    18: "ITC48",
    19: "ITC4A",
    20: "ITC4B",
    21: "ITD10",
    22: "ITD20",
    23: "ITD31",
    24: "ITD32",
    25: "ITD33",
    26: "ITD34",
    27: "ITD35",
    28: "ITD36",
    29: "ITD37",
    30: "ITD42",
    31: "ITD43",
    32: "ITD44",
    33: "ITD51",
    34: "ITD52",
    35: "ITD53",
    36: "ITD54",
    37: "ITD55",
    38: "ITD56",
    39: "ITD57",
    40: "ITD58",
    41: "ITE31",
    42: "ITE32",
    43: "ITE33",
    44: "ITE34",
    45: "ITE11",
    46: "ITE12",
    47: "ITE13",
    48: "ITE14",
    49: "ITE16",
    50: "ITE17",
    51: "ITE18",
    52: "ITE19",
    53: "ITE1A",
    54: "ITE21",
    55: "ITE22",
    56: "ITE41",
    57: "ITE42",
    58: "ITE43",
    59: "ITE44",
    60: "ITE45",
    61: "ITF31",
    62: "ITF32",
    63: "ITF33",
    64: "ITF34",
    65: "ITF35",
    66: "ITF11",
    67: "ITF12",
    68: "ITF13",
    69: "ITF14",
    70: "ITF22",
    71: "ITF41",
    72: "ITF42",
    73: "ITF43",
    74: "ITF44",
    75: "ITF45",
    76: "ITF51",
    77: "ITF52",
    78: "ITF61",
    79: "ITF63",
    80: "ITF65",
    81: "ITG11",
    82: "ITG12",
    83: "ITG13",
    84: "ITG14",
    85: "ITG15",
    86: "ITG16",
    87: "ITG17",
    88: "ITG18",
    89: "ITG19",
    93: "ITD41",
    94: "ITF21",
    96: "ITC13",
    97: "ITC43",
    98: "ITC49",
    99: "ITD59",
    100: "ITE15",
    101: "ITF62",
    102: "ITF64",
    103: "ITC14",
    108: "IT108",
    109: "IT109",
    110: "IT110",
}

#: Regola Sardegna (spec 4.1): il dataset usa le 4 province storiche con i confini
#: all'inizio del 2001 (nota ISTAT). I loro poligoni si prendono dai confini
#: generalizzati 2001 (``Prov2001_g``), non da un'assegnazione dei comuni attuali:
#: cosi' non serve alcuna tabella comune -> provincia storica e non c'e' margine
#: d'errore da dichiarare (es. Bosa, passata a Oristano nel 2005, resta in Nuoro).
SARDEGNA_2001: dict[int, str] = {90: "ITG25", 91: "ITG26", 92: "ITG27", 95: "ITG28"}

#: Province 2024 sarde da NON usare (sostituite dai poligoni 2001).
SARDEGNA_2024 = frozenset({90, 91, 92, 95, 111})

#: Nomi estesi che non seguono la forma "Provincia di <nome>".
NOMI_ESTESI_SPECIALI: dict[str, str] = {
    "ITC20": "Valle d'Aosta",
    "ITD10": "Provincia autonoma di Bolzano",
    "ITD20": "Provincia autonoma di Trento",
}
#: Nomi brevi (quelli che la narrativa scrive) diversi dalla codelist.
NOMI_BREVI_SPECIALI: dict[str, str] = {
    "ITC20": "Valle d'Aosta",
    "ITD10": "Bolzano",
    "021008": "Bolzano",
}

#: Tolleranze di semplificazione in gradi (~200 m per le province, ~50 m per i
#: comuni capoluogo, dove la precisione ai bordi conta di piu').
TOLLERANZA_PROVINCE = 0.002
TOLLERANZA_COMUNI = 0.0005
DECIMALI = 5

_NS = {
    "s": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
    "c": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common",
}
_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

CARTELLA = Path(__file__).resolve().parents[1] / "src" / "crime_risk_analyzer" / "istat"


def voci_richieste() -> list[str]:
    """Voci da estrarre: quelle collegate a un hazard piu' il totale (D10)."""
    voci = {m.voce_istat for m in MAPPATURA.values() if m.voce_istat}
    return sorted(voci | {VOCE_TOTALE})


def is_provincia(codice: str) -> bool:
    """Le province del dataset hanno codice NUTS3 di 5 caratteri (es. ITE43, IT108)."""
    return codice.startswith("IT") and len(codice) == 5


def is_comune(codice: str) -> bool:
    """I comuni capoluogo hanno il codice comune ISTAT a 6 cifre."""
    return len(codice) == 6 and codice.isdigit()


def scarica(url: str) -> bytes:
    """GET con timeout largo: i file ISTAT pesano decine di MB."""
    risposta = httpx.get(url, timeout=300.0, follow_redirects=True)
    risposta.raise_for_status()
    return risposta.content


def codelist(xml: bytes, identificativo: str) -> dict[str, str]:
    """Codice -> nome italiano di una codelist SDMX (es. CL_ITTER107)."""
    radice = ET.fromstring(xml)
    out: dict[str, str] = {}
    for lista in radice.iter(f"{{{_NS['s']}}}Codelist"):
        if lista.get("id") != identificativo:
            continue
        for codice in lista.findall("s:Code", _NS):
            nomi = {n.get(_LANG): n.text or "" for n in codice.findall("c:Name", _NS)}
            out[str(codice.get("id"))] = nomi.get("it") or nomi.get("en") or ""
    return out


def valori_da_csv(
    testo: str, *, anni: Iterable[int], voci: Iterable[str]
) -> dict[str, dict[str, dict[str, dict[str, Any] | None]]]:
    """``luogo -> voce -> anno -> {delitti, tasso, tasso_sotto_soglia}`` dal CSV SDMX.

    Tiene solo province, comuni capoluogo e Italia (scarta regioni e ripartizioni)
    e solo gli ``anni``/``voci`` richiesti. Un anno senza ``CRIMEN`` resta ``None``.
    """
    anni_str = {str(a) for a in anni}
    voci_set = set(voci)
    grezzi: dict[tuple[str, str, str], dict[str, Any]] = {}
    for riga in csv.DictReader(io.StringIO(testo)):
        area = riga["REF_AREA"]
        if not (area == CODICE_ITALIA or is_provincia(area) or is_comune(area)):
            continue
        if riga["TYPE_CRIME"] not in voci_set or riga["TIME_PERIOD"] not in anni_str:
            continue
        chiave = (area, riga["TYPE_CRIME"], riga["TIME_PERIOD"])
        voce = grezzi.setdefault(chiave, {})
        valore = riga["OBS_VALUE"].strip()
        if riga["DATA_TYPE"] == "CRIMEN":
            voce["delitti"] = int(float(valore)) if valore else None
        elif riga["DATA_TYPE"] == "CRIMET":
            voce["tasso"] = float(valore) if valore else None
            voce["tasso_sotto_soglia"] = (
                not valore and riga["OBS_STATUS"] == FLAG_SOTTO_SOGLIA
            )
    out: dict[str, dict[str, dict[str, dict[str, Any] | None]]] = {}
    for (area, voce, anno), v in sorted(grezzi.items()):
        if v.get("delitti") is None:
            dato = None
        else:
            dato = {
                "delitti": v["delitti"],
                "tasso": v.get("tasso"),
                "tasso_sotto_soglia": bool(v.get("tasso_sotto_soglia", False)),
            }
        out.setdefault(area, {}).setdefault(voce, {})[anno] = dato
    for area in out:
        for voce in out[area]:
            for anno in sorted(anni_str):
                out[area][voce].setdefault(anno, None)
    return out


def verifica_completezza(
    valori: Mapping[str, Mapping[str, Mapping[str, object]]], voci: Iterable[str]
) -> list[str]:
    """Problemi bloccanti: conteggi di territori e voci senza ``ANNO`` (spec 3)."""
    problemi: list[str] = []
    province = [c for c in valori if is_provincia(c)]
    comuni = [c for c in valori if is_comune(c)]
    if len(province) != 106:
        problemi.append(f"attese 106 province, trovate {len(province)}")
    if len(comuni) != 108:
        problemi.append(f"attesi 108 comuni capoluogo, trovati {len(comuni)}")
    if CODICE_ITALIA not in valori:
        problemi.append("manca la riga Italia")
    for area, per_voce in valori.items():
        for voce in voci:
            if per_voce.get(voce, {}).get(str(ANNO)) is None:
                problemi.append(f"{area}/{voce}: manca il dato {ANNO}")
    return problemi


def scrivi_json(percorso: Path, contenuto: object) -> None:
    """JSON compatto e deterministico (chiavi ordinate, UTF-8, LF)."""
    testo = json.dumps(
        contenuto, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    percorso.write_text(testo + "\n", encoding="utf-8", newline="\n")


def aggiorna_delitti(cartella: Path) -> None:
    voci = voci_richieste()
    struttura = scarica(URL_STRUTTURA)
    etichette = codelist(struttura, "CL_REATI_PS")
    url = URL_DATI.format(inizio=ANNO_CONFRONTO, fine=ANNO)
    testo = scarica(url).decode("utf-8-sig")
    valori = valori_da_csv(testo, anni=(ANNO, ANNO_CONFRONTO), voci=voci)
    problemi = verifica_completezza(valori, voci)
    if problemi:
        raise SystemExit("dati ISTAT incompleti:\n  " + "\n  ".join(problemi))
    scrivi_json(
        cartella / "delitti.json",
        {
            "dataset": DATASET,
            "titolo": TITOLO,
            "url": url,
            "estratto_il": dt.date.today().isoformat(),
            "licenza": LICENZA,
            "anno": ANNO,
            "anno_confronto": ANNO_CONFRONTO,
            "voci": {v: etichette[v] for v in voci},
            "valori": valori,
        },
    )


def _poligoni(geometria: Any) -> list[Any]:
    """Le sole parti areali di una geometria (make_valid puo' dare una collezione)."""
    from shapely.geometry import MultiPolygon, Polygon

    if isinstance(geometria, Polygon):
        return [geometria]
    if isinstance(geometria, MultiPolygon):
        return list(geometria.geoms)
    return [p for parte in getattr(geometria, "geoms", []) for p in _poligoni(parte)]


def _multipoligono(geometria: Any) -> dict[str, Any]:
    """Geometria shapely -> GeoJSON MultiPolygon arrotondato, coordinate (lon, lat)."""
    from shapely.geometry import mapping

    coordinate = [
        [
            [[round(x, DECIMALI), round(y, DECIMALI)] for x, y in anello]
            for anello in mapping(poligono)["coordinates"]
        ]
        for poligono in _poligoni(geometria)
    ]
    return {"type": "MultiPolygon", "coordinates": coordinate}


def _shape(
    zip_bytes: bytes, prefisso: str, cartella: Path
) -> list[tuple[dict[str, Any], Any]]:
    """Record + geometria WGS84 (non semplificata) di uno shapefile dentro lo zip."""
    import shapefile
    from pyproj import Transformer
    from shapely.geometry import shape
    from shapely.ops import transform

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archivio:
        archivio.extractall(cartella)
    base = next(cartella.rglob(f"{prefisso}*.shp")).with_suffix("")
    # I file si chiamano *_WGS84 ma la proiezione nel .prj e' WGS84 UTM 32N.
    trasforma = Transformer.from_crs(
        "EPSG:32632", "EPSG:4326", always_xy=True
    ).transform
    # ``with`` (non ``as``, i cui stub tipano il ritorno come ``_HasExitStack``):
    # su Windows un .dbf lasciato aperto blocca la pulizia della tmpdir.
    lettore = shapefile.Reader(str(base))
    with lettore:
        risultato: list[tuple[dict[str, Any], Any]] = []
        for sr in lettore.iterShapeRecords():
            # ``record``/``shape`` sono opzionali solo nello stub (ctor con default
            # None): ``iterShapeRecords`` li popola sempre.
            assert sr.record is not None and sr.shape is not None
            risultato.append(
                (
                    sr.record.as_dict(),
                    transform(trasforma, shape(sr.shape.__geo_interface__)),
                )
            )
        return risultato


def _luogo(
    codice: str, nome: str, tipo: str, geometria: Any, tolleranza: float, **extra: Any
) -> dict[str, Any]:
    from shapely.validation import make_valid

    semplice = make_valid(geometria.simplify(tolleranza, preserve_topology=True))
    punto = geometria.representative_point()
    if not semplice.contains(punto):
        punto = semplice.representative_point()
    min_lon, min_lat, max_lon, max_lat = semplice.bounds
    breve = NOMI_BREVI_SPECIALI.get(codice, nome)
    if tipo == "comune":
        esteso = f"Comune di {breve}"
    else:
        esteso = NOMI_ESTESI_SPECIALI.get(codice, f"Provincia di {breve}")
    return {
        "codice": codice,
        "tipo": tipo,
        "nome": esteso,
        "nome_breve": breve,
        "bbox": [
            round(min_lon, DECIMALI),
            round(min_lat, DECIMALI),
            round(max_lon, DECIMALI),
            round(max_lat, DECIMALI),
        ],
        "punto_interno": [round(punto.x, DECIMALI), round(punto.y, DECIMALI)],
        "geometria": _multipoligono(semplice),
        **extra,
    }


def _normalizza(nome: str) -> str:
    import unicodedata

    piano = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return "".join(c for c in piano.split("/")[0].lower() if c.isalpha())


def verifica_nomi(
    province_2024: Iterable[tuple[int, str]], nomi_dataset: Mapping[str, str]
) -> list[str]:
    """Controllo incrociato della tabella :data:`PROVINCIA_NUTS` sui nomi."""
    problemi: list[str] = []
    for cod_prov, den in province_2024:
        if cod_prov in SARDEGNA_2024:
            continue
        nuts = PROVINCIA_NUTS.get(cod_prov)
        if nuts is None:
            problemi.append(f"COD_PROV {cod_prov} ({den}) senza codice NUTS")
            continue
        atteso = _normalizza(nomi_dataset.get(nuts, ""))
        if nuts == "ITC20":
            atteso = "aosta"
        if _normalizza(den) != atteso:
            problemi.append(
                f"COD_PROV {cod_prov}: {den!r} != {nomi_dataset.get(nuts)!r} ({nuts})"
            )
    return problemi


def aggiorna_luoghi(cartella: Path) -> None:
    struttura = scarica(URL_STRUTTURA)
    nomi = codelist(struttura, "CL_ITTER107")
    delitti = json.loads((cartella / "delitti.json").read_text(encoding="utf-8"))
    codici = set(delitti["valori"]) - {CODICE_ITALIA}
    luoghi: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as tmp:
        z2024 = scarica(URL_CONFINI_2024)
        z2001 = scarica(URL_CONFINI_2001)
        province = _shape(z2024, "ProvCM01012024_g", Path(tmp) / "2024p")
        problemi = verifica_nomi(
            ((r["COD_PROV"], r["DEN_UTS"]) for r, _ in province), nomi
        )
        if problemi:
            raise SystemExit(
                "tabella province non coerente:\n  " + "\n  ".join(problemi)
            )
        for record, geometria in province:
            if record["COD_PROV"] in SARDEGNA_2024:
                continue
            nuts = PROVINCIA_NUTS[record["COD_PROV"]]
            luoghi.append(
                _luogo(nuts, nomi[nuts], "provincia", geometria, TOLLERANZA_PROVINCE)
            )
        for record, geometria in _shape(z2001, "Prov2001_g", Path(tmp) / "2001p"):
            nuts = SARDEGNA_2001.get(record["COD_PROV"])
            if nuts:
                luoghi.append(
                    _luogo(
                        nuts, nomi[nuts], "provincia", geometria, TOLLERANZA_PROVINCE
                    )
                )
        for record, geometria in _shape(z2024, "Com01012024_g", Path(tmp) / "2024c"):
            codice = record["PRO_COM_T"]
            if codice not in codici:
                continue
            cod_prov = record["COD_PROV"]
            provincia = SARDEGNA_2001.get(cod_prov) or PROVINCIA_NUTS[cod_prov]
            luoghi.append(
                _luogo(
                    codice,
                    nomi[codice],
                    "comune",
                    geometria,
                    TOLLERANZA_COMUNI,
                    provincia=provincia,
                )
            )
    trovati = {luogo["codice"] for luogo in luoghi}
    if trovati != codici:
        raise SystemExit(
            f"poligoni mancanti: {sorted(codici - trovati)}; "
            f"in piu': {sorted(trovati - codici)}"
        )
    luoghi.sort(key=lambda luogo: (luogo["tipo"], luogo["codice"]))
    scrivi_json(
        cartella / "luoghi.json",
        {
            "fonte": (
                "ISTAT, confini amministrativi generalizzati al 1/1/2024 "
                "(province e comuni capoluogo) e al 2001 (le 4 province sarde storiche)"
            ),
            "url": [URL_CONFINI_2024, URL_CONFINI_2001],
            "licenza": LICENZA,
            "generato_il": dt.date.today().isoformat(),
            "luoghi": luoghi,
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--confini", action="store_true", help="rigenera anche luoghi.json"
    )
    parser.add_argument(
        "--cartella", type=Path, default=CARTELLA, help=argparse.SUPPRESS
    )
    args = parser.parse_args(argv)
    aggiorna_delitti(args.cartella)
    if args.confini:
        aggiorna_luoghi(args.cartella)
    for nome in ("delitti.json", "luoghi.json"):
        percorso = args.cartella / nome
        if percorso.exists():
            print(f"{nome}: {percorso.stat().st_size / 1_000_000:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
