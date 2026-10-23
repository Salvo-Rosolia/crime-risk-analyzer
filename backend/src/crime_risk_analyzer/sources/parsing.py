"""Lettura e controllo dei cinque file delle fonti (#415).

Entrata unica: :func:`check_sources` (non solleva, restituisce il report) e
:func:`read_sources` (solleva :class:`SourceValidationError` se ci sono errori).
Prendono i byte dei file caricati (:class:`UploadedFiles`) e il vocabolario OWL
(:class:`OntologyVocabulary`); producono un :class:`ParsedSources` con i dati gia'
nei tipi del progetto (``DatiIstat`` e ``Mappatura`` degli stessi modelli che usa
oggi l'ISTAT), pronto per essere impacchettato in un set di fonti. Il modulo non
conosce il set attivo, le sessioni o il contesto di richiesta: e' puro.

I cinque file:

* **ontologia** (Turtle o OWL/RDF-XML): :mod:`.ontology_reader`;
* **tabella OSM -> classe** (``osm_table``): ``osm_tag,classe``;
* **dati statistici** (``data``): ``luogo,voce,voce_etichetta,anno,delitti,tasso``
  e, opzionale, ``tasso_sotto_soglia`` (``si``/``no``). L'anno piu' recente del
  file e' l'anno corrente, quello di confronto e' ``anno - 10``; ``IT`` e' la
  riga nazionale e ``TOT`` la voce del totale (come ``delitti.json``); versione =
  primi 12 caratteri dello SHA-256 del file;
* **tabella hazard -> voce** (``hazard_table``): ``hazard,voce,corrispondenza``
  e, opzionali, ``serie_non_confrontabile`` (``si``/``no``) e ``nota``;
* **confini** (``boundaries``, opzionale): GeoJSON ``FeatureCollection`` con in
  ``properties`` ``codice``, ``tipo`` (``comune``/``provincia``), ``nome``,
  ``nome_breve`` e, opzionale, ``provincia``. Senza il file valgono solo i
  confini passati in ``fallback_luoghi`` (quelli nostri).

Il controllo gira prima di attivare qualunque cosa e raccoglie TUTTI i problemi.
I controlli incrociati (classi e hazard nell'ontologia, voci nei dati) si
saltano solo quando il file da cui dipendono non e' leggibile.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from rdflib import Graph

from crime_risk_analyzer.istat.dati import (
    CODICE_ITALIA,
    VOCE_TOTALE,
    DatiIstat,
    FileDelitti,
    Luogo,
    TipoLuogo,
    ValoreAnno,
)
from crime_risk_analyzer.istat.mappatura import Corrispondenza, Mappatura
from crime_risk_analyzer.models.geo import (
    CityBoundary,
    Polygon,
    Ring,
    boundary_from_geojson,
    point_in_polygon,
)
from crime_risk_analyzer.sources.csv_reader import CsvRow, read_csv
from crime_risk_analyzer.sources.limits import (
    MAX_BYTES_CSV,
    MAX_BYTES_GEOJSON,
    MAX_BYTES_ONTOLOGIA,
    controlla_nota,
    controlla_testo,
)
from crime_risk_analyzer.sources.ontology_reader import (
    OntologyReading,
    read_ontology,
)
from crime_risk_analyzer.sources.report import (
    FileName,
    SourceValidationError,
    ValidationReport,
)
from crime_risk_analyzer.sources.vocabulary import (
    TERMINUS_VOCABULARY,
    OntologyVocabulary,
)

__all__ = [
    "DATA_COLUMNS",
    "DATA_OPTIONAL_COLUMNS",
    "HAZARD_COLUMNS",
    "HAZARD_OPTIONAL_COLUMNS",
    "OSM_COLUMNS",
    "ParsedSources",
    "UploadedFiles",
    "check_sources",
    "read_sources",
]

OSM_COLUMNS = ("osm_tag", "classe")
DATA_COLUMNS = (
    "luogo",
    "voce",
    "voce_etichetta",
    "anno",
    "delitti",
    "tasso",
)
DATA_OPTIONAL_COLUMNS = ("tasso_sotto_soglia",)
HAZARD_COLUMNS = ("hazard", "voce", "corrispondenza")
HAZARD_OPTIONAL_COLUMNS = ("serie_non_confrontabile", "nota")

_CORRISPONDENZE: tuple[Corrispondenza, ...] = ("esatta", "piu_larga", "piu_stretta")
_TIPI_LUOGO: tuple[TipoLuogo, ...] = ("comune", "provincia")
_OSM_TAG = re.compile(r"[A-Za-z0-9_:\-]+=[A-Za-z0-9_:.\-]+")
_CODICE_LUOGO = re.compile(r"[A-Za-z0-9_\-]{1,20}")
_CODICE_VOCE = re.compile(r"[A-Za-z0-9_]{1,40}")
_ANNO = re.compile(r"[0-9]{4}")
_INTERO = re.compile(r"[0-9]{1,12}")
_DECIMALE = re.compile(r"[0-9]{1,15}(?:\.[0-9]{1,6})?")
_ANNI_CONFRONTO = 10


@dataclass(frozen=True)
class UploadedFiles:
    """Byte dei file caricati; ``boundaries`` e' l'unico opzionale."""

    ontology: bytes
    #: Nome del file dell'ontologia: l'estensione sceglie il formato.
    ontology_name: str
    osm_table: bytes
    data: bytes
    hazard_table: bytes
    boundaries: bytes | None = None


@dataclass(frozen=True)
class ParsedSources:
    """Fonti lette e controllate, nei tipi del progetto."""

    graph: Graph
    vocabulary: OntologyVocabulary
    #: Nomi locali di tutte le classi dell'ontologia nel namespace.
    classes: frozenset[str]
    #: Classe -> (etichetta IT, etichetta EN); ripiego: nome con ``_`` -> spazio.
    labels: dict[str, tuple[str, str]]
    #: ``chiave=valore`` OSM -> nome della classe (stessa forma di ``OSM_TO_TERMINUS``).
    osm_to_class: dict[str, str]
    #: Famiglie di chiavi OSM nell'ordine di prima comparsa nella tabella.
    ordine_famiglie: tuple[str, ...]
    #: Dati e luoghi con confini (solo luoghi che hanno dati), come ``carica_dati``.
    istat: DatiIstat
    #: Hazard -> voce (stessa forma di ``istat.mappatura.MAPPATURA``).
    mappatura: dict[str, Mappatura]
    #: Voci con serie non confrontabile (equivalente di ``VOCI_ROTTURA_2016``).
    voci_rottura: frozenset[str]
    #: Primi 12 caratteri dello SHA-256 del file dei dati.
    versione: str


def read_sources(
    files: UploadedFiles,
    vocabulary: OntologyVocabulary = TERMINUS_VOCABULARY,
    *,
    fallback_luoghi: Sequence[Luogo] = (),
) -> tuple[ParsedSources, ValidationReport]:
    """Come :func:`check_sources`, ma solleva se il caricamento non e' valido.

    Raises:
        SourceValidationError: ``report`` ha tutti i problemi bloccanti.
    """
    parsed, report = check_sources(files, vocabulary, fallback_luoghi=fallback_luoghi)
    if parsed is None:
        raise SourceValidationError(report)
    return parsed, report


def check_sources(
    files: UploadedFiles,
    vocabulary: OntologyVocabulary = TERMINUS_VOCABULARY,
    *,
    fallback_luoghi: Sequence[Luogo] = (),
) -> tuple[ParsedSources | None, ValidationReport]:
    """Legge e controlla i file; ``ParsedSources`` e' ``None`` se ci sono errori.

    Gli avvisi (``report.warnings``) non bloccano e si riportano anche a esito
    positivo. ``fallback_luoghi`` sono i confini nostri, usati per i luoghi dei
    dati che il file dei confini non copre.
    """
    report = ValidationReport()
    ammessi = _controlla_dimensioni(files, report)

    ontologia = (
        read_ontology(files.ontology, files.ontology_name, vocabulary, report)
        if "ontology" in ammessi
        else None
    )
    osm = (
        _leggi_osm(files.osm_table, ontologia, report)
        if "osm_table" in ammessi
        else None
    )
    dati = _leggi_dati(files.data, report) if "data" in ammessi else None
    mappatura = (
        _leggi_hazard(files.hazard_table, ontologia, dati, report)
        if "hazard_table" in ammessi
        else None
    )
    confini = (
        _leggi_confini(files.boundaries, report)
        if files.boundaries is not None and "boundaries" in ammessi
        else {}
    )
    luoghi = (
        _scegli_luoghi(dati, confini, fallback_luoghi, report)
        if dati is not None and (files.boundaries is None or "boundaries" in ammessi)
        else None
    )

    if (
        not report.ok
        or ontologia is None
        or osm is None
        or dati is None
        or mappatura is None
        or luoghi is None
    ):
        return None, report

    delitti = _file_delitti(dati, files.data)
    versione = delitti.estratto_il
    voci_rottura, per_hazard = mappatura
    return (
        ParsedSources(
            graph=ontologia.graph,
            vocabulary=vocabulary,
            classes=ontologia.classes,
            labels=ontologia.labels,
            osm_to_class=dict(osm.tag_classe),
            ordine_famiglie=osm.famiglie,
            istat=DatiIstat(delitti=delitti, luoghi=luoghi),
            mappatura=per_hazard,
            voci_rottura=voci_rottura,
            versione=versione,
        ),
        report,
    )


# --- dimensioni ---


def _controlla_dimensioni(
    files: UploadedFiles, report: ValidationReport
) -> set[FileName]:
    """Segnala i file oltre il limite e restituisce quelli da leggere."""
    limiti: list[tuple[FileName, bytes | None, int]] = [
        ("ontology", files.ontology, MAX_BYTES_ONTOLOGIA),
        ("osm_table", files.osm_table, MAX_BYTES_CSV),
        ("data", files.data, MAX_BYTES_CSV),
        ("hazard_table", files.hazard_table, MAX_BYTES_CSV),
        ("boundaries", files.boundaries, MAX_BYTES_GEOJSON),
    ]
    ammessi: set[FileName] = set()
    for nome, contenuto, limite in limiti:
        if contenuto is not None and len(contenuto) > limite:
            report.error(
                "file_troppo_grande",
                nome,
                f"il file pesa {len(contenuto) / (1024 * 1024):.1f} MB, "
                f"il massimo e' {limite // (1024 * 1024)} MB",
            )
        else:
            ammessi.add(nome)
    return ammessi


# --- tabella OSM ---


@dataclass(frozen=True)
class _Osm:
    tag_classe: dict[str, str]
    famiglie: tuple[str, ...]


def _leggi_osm(
    content: bytes, ontologia: OntologyReading | None, report: ValidationReport
) -> _Osm | None:
    righe = read_csv(content, "osm_table", required=OSM_COLUMNS, report=report)
    if righe is None:
        return None
    tag_classe: dict[str, str] = {}
    visti: set[str] = set()
    for riga in righe:
        tag, classe = riga.cells["osm_tag"], riga.cells["classe"]
        if _OSM_TAG.fullmatch(tag) is None:
            report.error(
                "osm_tag_non_valido",
                "osm_table",
                f"selettore OSM {tag[:40]!r} non valido: serve la forma "
                "chiave=valore, solo lettere, cifre e _ : . -",
                line=riga.line,
            )
            continue
        if tag in visti:
            report.error(
                "chiave_duplicata",
                "osm_table",
                f"il selettore {tag!r} compare piu' volte",
                line=riga.line,
            )
            continue
        visti.add(tag)
        if ontologia is not None and classe not in ontologia.classes:
            report.error(
                "classe_assente_dall_ontologia",
                "osm_table",
                f"la classe {classe[:40]!r} non esiste nell'ontologia caricata",
                line=riga.line,
            )
            continue
        tag_classe[tag] = classe
    famiglie = tuple(dict.fromkeys(t.partition("=")[0] for t in tag_classe))
    return _Osm(tag_classe=tag_classe, famiglie=famiglie)


# --- dati statistici ---


@dataclass(frozen=True)
class _Dati:
    anno: int
    voci: dict[str, str]
    valori: dict[str, dict[str, dict[str, ValoreAnno | None]]]


def _si_no(valore: str) -> bool | None:
    """``True``/``False`` per ``si``/``no`` (vuoto = ``no``); ``None`` se non valido."""
    chiaro = valore.strip().lower()
    if chiaro in ("", "no"):
        return False
    if chiaro in ("si", "sì"):
        return True
    return None


def _leggi_dati(content: bytes, report: ValidationReport) -> _Dati | None:
    righe = read_csv(
        content,
        "data",
        required=DATA_COLUMNS,
        optional=DATA_OPTIONAL_COLUMNS,
        report=report,
    )
    if righe is None:
        return None
    voci: dict[str, str] = {}
    valori: dict[str, dict[str, dict[str, ValoreAnno | None]]] = {}
    for riga in righe:
        _riga_dati(riga, voci, valori, report)
    if not valori:
        return None
    if CODICE_ITALIA not in valori:
        report.error(
            "riga_nazionale_mancante",
            "data",
            f"manca la riga nazionale (luogo={CODICE_ITALIA}), serve per il "
            "confronto con il tasso nazionale",
        )
    anni = [
        int(a) for per_voce in valori.values() for v in per_voce.values() for a in v
    ]
    anno = max(anni)
    if not any(
        str(anno - _ANNI_CONFRONTO) in per_anno
        for per_voce in valori.values()
        for per_anno in per_voce.values()
    ):
        report.warning(
            "anno_confronto_assente",
            "data",
            f"nessun dato per l'anno di confronto {anno - _ANNI_CONFRONTO}: "
            "la tendenza non si calcola",
        )
    senza_totale = sorted(
        luogo for luogo, per_voce in valori.items() if VOCE_TOTALE not in per_voce
    )
    if senza_totale:
        report.warning(
            "totale_mancante",
            "data",
            f"nessuna riga della voce {VOCE_TOTALE} (totale) per: "
            f"{', '.join(senza_totale)}",
        )
    return _Dati(anno=anno, voci=voci, valori=valori)


def _riga_dati(
    riga: CsvRow,
    voci: dict[str, str],
    valori: dict[str, dict[str, dict[str, ValoreAnno | None]]],
    report: ValidationReport,
) -> None:
    c = riga.cells
    ok = True

    def errore(codice: str, messaggio: str) -> None:
        nonlocal ok
        ok = False
        report.error(codice, "data", messaggio, line=riga.line)

    luogo, voce, etichetta = c["luogo"], c["voce"], c["voce_etichetta"]
    if _CODICE_LUOGO.fullmatch(luogo) is None:
        errore(
            "codice_non_valido",
            f"codice luogo {luogo[:40]!r} non valido: massimo 20 tra lettere, "
            "cifre, _ e -",
        )
    if _CODICE_VOCE.fullmatch(voce) is None:
        errore(
            "codice_non_valido",
            f"codice voce {voce[:40]!r} non valido: massimo 40 tra lettere, cifre e _",
        )
    motivo = controlla_testo(etichetta)
    if motivo is not None:
        errore("testo_non_ammesso", f"etichetta della voce {voce[:40]!r}: {motivo}")
    elif voce in voci and voci[voce] != etichetta:
        errore(
            "etichetta_voce_incoerente",
            f"la voce {voce!r} ha gia' l'etichetta {voci[voce]!r}, qui {etichetta!r}",
        )

    anno = c["anno"]
    if _ANNO.fullmatch(anno) is None or not 1900 <= int(anno) <= 2100:
        errore(
            "valore_non_valido",
            f"anno {anno[:20]!r} non valido: serve un anno a 4 cifre",
        )

    delitti = c["delitti"]
    if delitti and _INTERO.fullmatch(delitti) is None:
        errore(
            "valore_non_valido",
            f"delitti {delitti[:20]!r} non valido: serve un intero non negativo "
            "o vuoto",
        )
    tasso: float | None = None
    try:
        tasso = _numero(c["tasso"])
    except ValueError:
        errore(
            "valore_non_valido",
            f"tasso {c['tasso'][:20]!r} non valido: serve un numero non negativo "
            "con il punto decimale, o vuoto",
        )
    sotto = _si_no(c.get("tasso_sotto_soglia", ""))
    if sotto is None:
        errore(
            "valore_non_valido",
            f"tasso_sotto_soglia {c['tasso_sotto_soglia'][:20]!r} non valido: "
            "si oppure no",
        )
    if ok:
        if not delitti and (tasso is not None or sotto):
            errore(
                "valore_non_valido",
                "senza il numero di delitti (dato mancante) tasso e "
                "tasso_sotto_soglia devono essere vuoti",
            )
        elif sotto and tasso is not None:
            errore(
                "valore_non_valido",
                "con tasso_sotto_soglia=si il tasso deve essere vuoto",
            )
    if not ok:
        return
    per_anno = valori.setdefault(luogo, {}).setdefault(voce, {})
    if anno in per_anno:
        report.error(
            "chiave_duplicata",
            "data",
            f"luogo {luogo!r}, voce {voce!r}, anno {anno} compaiono piu' volte",
            line=riga.line,
        )
        return
    voci.setdefault(voce, etichetta)
    per_anno[anno] = (
        ValoreAnno(
            delitti=int(delitti),
            tasso=tasso,
            tasso_sotto_soglia=bool(sotto),
        )
        if delitti
        else None
    )


def _numero(testo: str) -> float | None:
    """Decimale non negativo col punto (``12`` o ``12.5``); ``None`` se vuoto.

    Niente separatori ``_``, esponenti, ``nan``/``inf`` o cifre non ASCII:
    ``ValueError`` per tutto il resto.
    """
    if not testo:
        return None
    if _DECIMALE.fullmatch(testo) is None:
        raise ValueError(testo)
    return float(testo)


def _file_delitti(dati: _Dati, contenuto: bytes) -> FileDelitti:
    versione = hashlib.sha256(contenuto).hexdigest()[:12]
    return FileDelitti(
        dataset="caricato",
        titolo="Dati statistici caricati dall'utente",
        url="",
        estratto_il=versione,
        licenza="",
        anno=dati.anno,
        anno_confronto=dati.anno - _ANNI_CONFRONTO,
        voci=dict(dati.voci),
        valori=dati.valori,
    )


# --- tabella hazard -> voce ---


def _leggi_hazard(
    content: bytes,
    ontologia: OntologyReading | None,
    dati: _Dati | None,
    report: ValidationReport,
) -> tuple[frozenset[str], dict[str, Mappatura]] | None:
    righe = read_csv(
        content,
        "hazard_table",
        required=HAZARD_COLUMNS,
        optional=HAZARD_OPTIONAL_COLUMNS,
        report=report,
    )
    if righe is None:
        return None
    visti: set[str] = set()
    validi: list[tuple[str, str | None, Corrispondenza | None, bool, str]] = []
    for riga in righe:
        esito = _riga_hazard(riga, ontologia, dati, visti, report)
        if esito is not None:
            validi.append(esito)
    flag_per_voce: dict[str, set[bool]] = {}
    for _, voce, _, rottura, _ in validi:
        if voce is not None:
            flag_per_voce.setdefault(voce, set()).add(rottura)
    voci_rottura = frozenset(v for v, flag in flag_per_voce.items() if True in flag)
    for voce in sorted(v for v, flag in flag_per_voce.items() if len(flag) == 2):
        report.warning(
            "serie_non_confrontabile_incoerente",
            "hazard_table",
            f"la voce {voce!r} e' segnata serie_non_confrontabile=si in alcune "
            "righe e no in altre: vale si per tutta la voce",
        )
    mappatura = {
        hazard: Mappatura(
            voce_istat=voce,
            corrispondenza=corrispondenza,
            rottura_2016=voce in voci_rottura if voce is not None else False,
            nota=nota,
        )
        for hazard, voce, corrispondenza, _, nota in validi
    }
    return voci_rottura, mappatura


def _riga_hazard(
    riga: CsvRow,
    ontologia: OntologyReading | None,
    dati: _Dati | None,
    visti: set[str],
    report: ValidationReport,
) -> tuple[str, str | None, Corrispondenza | None, bool, str] | None:
    c = riga.cells
    hazard, voce, corr = c["hazard"], c["voce"], c["corrispondenza"]
    ok = True

    def errore(codice: str, messaggio: str) -> None:
        nonlocal ok
        ok = False
        report.error(codice, "hazard_table", messaggio, line=riga.line)

    if hazard in visti:
        errore("chiave_duplicata", f"l'hazard {hazard[:40]!r} compare piu' volte")
    elif ontologia is not None and hazard not in ontologia.classes:
        errore(
            "hazard_assente_dall_ontologia",
            f"l'hazard {hazard[:40]!r} non esiste nell'ontologia caricata",
        )
    if bool(voce) != bool(corr):
        errore(
            "voce_corrispondenza_incoerenti",
            "voce e corrispondenza vanno compilate insieme o lasciate "
            "entrambe vuote (nessuna voce adeguata)",
        )
    elif voce:
        if corr not in _CORRISPONDENZE:
            errore(
                "corrispondenza_non_valida",
                f"corrispondenza {corr[:20]!r} non valida: "
                f"{', '.join(_CORRISPONDENZE)}",
            )
        if dati is not None and voce not in dati.voci:
            errore(
                "voce_assente_dai_dati",
                f"la voce {voce[:40]!r} non compare nel file dei dati",
            )
    rottura = _si_no(c.get("serie_non_confrontabile", ""))
    if rottura is None:
        errore(
            "valore_non_valido",
            f"serie_non_confrontabile {c['serie_non_confrontabile'][:20]!r} "
            "non valido: si oppure no",
        )
    nota = c.get("nota", "")
    motivo = controlla_nota(nota)
    if motivo is not None:
        errore("testo_non_ammesso", motivo)
    visti.add(hazard)
    if not ok or rottura is None:
        return None
    return (
        hazard,
        voce or None,
        cast("Corrispondenza", corr) if corr else None,
        rottura,
        nota,
    )


# --- confini ---


def _leggi_confini(content: bytes, report: ValidationReport) -> dict[str, Luogo]:
    try:
        radice = cast("object", json.loads(content.decode("utf-8-sig")))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        report.error(
            "confini_illeggibili",
            "boundaries",
            f"il file dei confini non e' un JSON valido: {str(exc)[:200]}",
        )
        return {}
    if (
        not isinstance(radice, dict)
        or cast("dict[str, object]", radice).get("type") != "FeatureCollection"
        or not isinstance(cast("dict[str, object]", radice).get("features"), list)
    ):
        report.error(
            "confini_non_validi",
            "boundaries",
            "il file dei confini deve essere un GeoJSON di tipo FeatureCollection",
        )
        return {}
    features = cast("list[object]", cast("dict[str, object]", radice)["features"])
    luoghi: dict[str, Luogo] = {}
    for indice, feature in enumerate(features, start=1):
        luogo = _feature(indice, feature, report)
        if luogo is None:
            continue
        if luogo.codice in luoghi:
            report.error(
                "chiave_duplicata",
                "boundaries",
                f"feature {indice}: il codice {luogo.codice!r} compare piu' volte",
            )
            continue
        luoghi[luogo.codice] = luogo
    return luoghi


def _feature(indice: int, feature: object, report: ValidationReport) -> Luogo | None:
    def errore(codice: str, messaggio: str) -> None:
        report.error(codice, "boundaries", f"feature {indice}: {messaggio}")

    if not isinstance(feature, dict):
        errore("confini_non_validi", "non e' un oggetto GeoJSON")
        return None
    campi = cast("dict[str, object]", feature)
    proprieta_raw = campi.get("properties")
    proprieta = (
        cast("dict[str, object]", proprieta_raw)
        if isinstance(proprieta_raw, dict)
        else {}
    )
    ok = True
    testi: dict[str, str] = {}
    for nome in ("codice", "tipo", "nome", "nome_breve"):
        valore = proprieta.get(nome)
        if not isinstance(valore, str) or not valore.strip():
            errore("confini_non_validi", f"manca la proprieta' {nome!r}")
            ok = False
        else:
            testi[nome] = valore.strip()
    provincia_raw = proprieta.get("provincia")
    provincia = provincia_raw.strip() if isinstance(provincia_raw, str) else None
    if "codice" in testi and _CODICE_LUOGO.fullmatch(testi["codice"]) is None:
        errore("codice_non_valido", f"codice {testi['codice'][:40]!r} non valido")
        ok = False
    if "tipo" in testi and testi["tipo"] not in _TIPI_LUOGO:
        errore(
            "confini_non_validi",
            f"tipo {testi['tipo'][:20]!r} non valido: comune o provincia",
        )
        ok = False
    for nome in ("nome", "nome_breve"):
        if nome in testi:
            motivo = controlla_testo(testi[nome])
            if motivo is not None:
                errore("testo_non_ammesso", f"proprieta' {nome!r}: {motivo}")
                ok = False
    if provincia is not None and _CODICE_LUOGO.fullmatch(provincia) is None:
        errore("codice_non_valido", f"provincia {provincia[:40]!r} non valida")
        ok = False
    geometria = campi.get("geometry")
    confine = _confine(geometria, errore)
    if not ok or confine is None:
        return None
    try:
        punto_interno = _punto_interno(confine)
    except ValueError:
        errore(
            "confini_non_validi",
            "non si trova un punto interno al poligono: geometria degenere",
        )
        return None
    return Luogo(
        codice=testi["codice"],
        tipo=cast("TipoLuogo", testi["tipo"]),
        nome=testi["nome"],
        nome_breve=testi["nome_breve"],
        provincia=provincia,
        bbox=_bbox(confine),
        punto_interno=punto_interno,
        confine=confine,
    )


def _confine(
    geometria: object, errore: Callable[[str, str], None]
) -> CityBoundary | None:
    if not isinstance(geometria, dict):
        errore("confini_non_validi", "manca la geometria")
        return None
    geo = cast("dict[str, object]", geometria)
    tipo = geo.get("type")
    if tipo not in ("Polygon", "MultiPolygon"):
        errore(
            "confini_non_validi",
            f"geometria {str(tipo)[:20]!r} non supportata: Polygon o MultiPolygon",
        )
        return None
    if not _coordinate_numeriche(geo.get("coordinates")):
        errore(
            "confini_non_validi",
            "le coordinate devono essere numeri JSON (non stringhe o booleani)",
        )
        return None
    try:
        confine = boundary_from_geojson(geo)
    except (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        OverflowError,
        RecursionError,
    ):
        errore("confini_non_validi", "coordinate della geometria malformate")
        return None
    if not confine.polygons:
        errore("confini_non_validi", "la geometria non ha poligoni")
        return None
    for poligono in confine.polygons:
        if not poligono:
            errore("confini_non_validi", "poligono senza anelli")
            return None
        for anello in poligono:
            if len(anello) < 4:
                errore(
                    "confini_non_validi",
                    "ogni anello del poligono deve avere almeno 4 punti",
                )
                return None
            if anello[0] != anello[-1]:
                errore(
                    "confini_non_validi",
                    "ogni anello deve essere chiuso: primo e ultimo punto uguali",
                )
                return None
            if _area_doppia(anello) == 0:
                errore("confini_non_validi", "un anello ha area zero")
                return None
            for lon, lat in anello:
                if not (
                    math.isfinite(lon)
                    and math.isfinite(lat)
                    and -180 <= lon <= 180
                    and -90 <= lat <= 90
                ):
                    errore(
                        "confini_non_validi",
                        "coordinate fuori range: longitudine -180..180, "
                        "latitudine -90..90",
                    )
                    return None
    return confine


def _coordinate_numeriche(coordinate: object) -> bool:
    """``True`` se tutte le foglie sono numeri JSON (no stringhe, no bool)."""
    pila: list[object] = [coordinate]
    while pila:
        voce = pila.pop()
        if isinstance(voce, list):
            pila.extend(cast("list[object]", voce))
        elif isinstance(voce, bool) or not isinstance(voce, (int, float)):
            return False
    return True


def _area_doppia(anello: Ring) -> float:
    """Doppia area con segno dell'anello (formula del lacciaio)."""
    return sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(anello, anello[1:], strict=False)
    )


def _bbox(confine: CityBoundary) -> tuple[float, float, float, float]:
    punti = [p for poly in confine.polygons for p in poly[0]]
    lons = [p[0] for p in punti]
    lats = [p[1] for p in punti]
    return (min(lons), min(lats), max(lons), max(lats))


def _punto_interno(confine: CityBoundary) -> tuple[float, float]:
    """Un punto dentro il poligono piu' esteso (la forma puo' essere concava)."""
    principale: Polygon = max(
        confine.polygons,
        key=lambda poly: (
            (max(p[0] for p in poly[0]) - min(p[0] for p in poly[0]))
            * (max(p[1] for p in poly[0]) - min(p[1] for p in poly[0]))
        ),
    )
    lats = [p[1] for p in principale[0]]
    basso, alto = min(lats), max(lats)
    for frazione in (0.5, 0.25, 0.75, 0.4, 0.6, 0.1, 0.9):
        y = basso + (alto - basso) * frazione
        incroci = sorted(_incroci_orizzontali(principale, y))
        intervalli = list(zip(incroci[0::2], incroci[1::2], strict=False))
        if not intervalli:
            continue
        x0, x1 = max(intervalli, key=lambda i: i[1] - i[0])
        candidato = ((x0 + x1) / 2, y)
        if point_in_polygon(candidato, principale):
            return candidato
    lon_min, lat_min, lon_max, lat_max = _bbox(confine)
    centro = ((lon_min + lon_max) / 2, (lat_min + lat_max) / 2)
    if not any(point_in_polygon(centro, poly) for poly in confine.polygons):
        raise ValueError("nessun punto interno trovato")
    return centro


def _incroci_orizzontali(poligono: Polygon, y: float) -> list[float]:
    incroci: list[float] = []
    for anello in poligono:
        for (x1, y1), (x2, y2) in zip(anello, anello[1:], strict=False):
            if (y1 > y) != (y2 > y):
                incroci.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
    return incroci


def _scegli_luoghi(
    dati: _Dati,
    caricati: Mapping[str, Luogo],
    fallback: Sequence[Luogo],
    report: ValidationReport,
) -> tuple[Luogo, ...] | None:
    """Luoghi dei dati con confini (caricati, poi nostri); avvisi per gli altri."""
    nostri = {luogo.codice: luogo for luogo in fallback}
    codici = sorted(set(dati.valori) - {CODICE_ITALIA})
    scelti: list[Luogo] = []
    senza: list[str] = []
    for codice in codici:
        luogo = caricati.get(codice) or nostri.get(codice)
        if luogo is None:
            senza.append(codice)
        else:
            scelti.append(luogo)
    if not scelti:
        if not _confini_non_leggibili(report):
            report.error(
                "nessun_luogo_con_confini",
                "boundaries",
                "nessun luogo dei dati ha i confini, ne' caricati ne' nostri: "
                "carica il file dei confini con gli stessi codici dei dati",
            )
        return None
    if senza:
        report.warning(
            "luogo_senza_confini",
            "data",
            f"luoghi senza confini, i POI al loro interno non avranno dati "
            f"statistici: {', '.join(senza)}",
        )
    senza_dati = sorted(set(caricati) - set(codici))
    if senza_dati:
        report.warning(
            "luogo_senza_dati",
            "boundaries",
            f"confini di luoghi che non hanno dati, ignorati: {', '.join(senza_dati)}",
        )
    return tuple(sorted(scelti, key=lambda lg: (lg.tipo, lg.codice)))


def _confini_non_leggibili(report: ValidationReport) -> bool:
    return any(p.file == "boundaries" for p in report.errors)
