"""Test del client Overpass -> POI on-demand (#16). Le risposte HTTP sono mockate."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast

import httpx
import pytest
import respx

from crime_risk_analyzer import overpass_client
from crime_risk_analyzer.eval.snapshots import capturing_source
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.overpass_client import (
    DEFAULT_OVERPASS_URL,
    INTERACTIVE_RETRY,
    MAX_POIS,
    OFFLINE_RETRY,
    PER_SELECTOR_CAP,
    OverpassError,
    Poi,
    TaglioOsm,
    fetch_pois,
    fetch_pois_with_cut,
    remark_segnala_risposta_incompleta,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "overpass_sample.json"
_BBOX = Bbox(41.88, 12.48, 41.90, 12.50)


def _sample() -> dict[str, object]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _no_retry_pause(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    """Azzera le pause della politica interattiva: nessuno sleep reale (#232).

    ``fetch_pois`` risolve la politica di default AL MOMENTO DELLA CHIAMATA
    (``retry or INTERACTIVE_RETRY``), non come default di firma: per questo
    sostituire l'attributo di modulo qui basta a rendere la suite istantanea.
    """
    monkeypatch.setattr(
        overpass_client,
        "INTERACTIVE_RETRY",
        replace(overpass_client.INTERACTIVE_RETRY, pause_s=(0.0,)),
    )


def _poi_a(poi_id: str, lat: float, lon: float, terminus_class: str = "Bank") -> Poi:
    """POI sintetico posizionato a mano (per i test di selezione, #254)."""
    return Poi(
        id=poi_id,
        name=f"POI {poi_id}",
        lat=lat,
        lon=lon,
        osm_tags="amenity=bank",
        terminus_class=terminus_class,
        citta="Roma",
    )


# --- #254: quali POI entrano nei MAX_POIS posti ---


def test_select_pois_prefers_the_nearest_to_the_center() -> None:
    """I posti vanno ai POI piu' vicini al centro dell'area, non ai primi arrivati.

    Prima di #254 il taglio prendeva i primi ``MAX_POIS`` nell'ordine in cui
    Overpass li emetteva, cioe' nell'ordine dei selettori dichiarati: i POI delle
    famiglie di tag in coda non entravano mai in una zona densa.
    """
    center_lat, center_lon = _BBOX.center()
    lontano = _poi_a("lontano", center_lat + 0.02, center_lon)
    vicino = _poi_a("vicino", center_lat + 0.0001, center_lon)

    selected = overpass_client.select_pois(
        [lontano, vicino], _BBOX.center(), max_pois=1
    )

    assert [p["id"] for p in selected] == ["vicino"]


def test_select_pois_caps_a_dense_class_while_other_classes_are_present() -> None:
    """Una classe densa non si prende tutti i posti se ci sono altre classi.

    In centro citta' i POI piu' vicini sono spesso della stessa classe (otto
    bancomat entro 150 m): senza tetto la zona verrebbe descritta su un campione
    omogeneo, cioe' la distorsione che #254 chiude, solo con un'altra causa.
    """
    lat, lon = _BBOX.center()
    banche = [_poi_a(f"bank-{i}", lat + 0.0001 * i, lon, "Bank") for i in range(5)]
    altre = [
        _poi_a("school", lat + 0.001, lon, "School"),
        _poi_a("museum", lat + 0.0011, lon, "Museum"),
    ]

    selected = overpass_client.select_pois(
        banche + altre, (lat, lon), max_pois=5, per_class_cap=3
    )

    per_classe = Counter(p["terminus_class"] for p in selected)
    assert per_classe == Counter({"Bank": 3, "School": 1, "Museum": 1})


def test_select_pois_fills_remaining_slots_when_only_capped_classes_are_left() -> None:
    """Il tetto non deve far restituire MENO POI di quanti la zona ne abbia.

    In una zona di sole banche un tetto rigido restituirebbe 3 punti invece di
    ``max_pois``: peggio di prima. Esauriti i candidati di altre classi, i posti
    rimasti si riempiono coi piu' vicini fra gli scartati, mantenendo l'ordine di
    distanza.
    """
    lat, lon = _BBOX.center()
    banche = [_poi_a(f"bank-{i}", lat + 0.0001 * i, lon, "Bank") for i in range(6)]

    selected = overpass_client.select_pois(
        banche, (lat, lon), max_pois=5, per_class_cap=3
    )

    assert [p["id"] for p in selected] == [
        "bank-0",
        "bank-1",
        "bank-2",
        "bank-3",
        "bank-4",
    ]


def test_select_pois_esce_sempre_in_ordine_di_distanza() -> None:
    """Anche i POI riammessi dal secondo giro stanno al loro posto in distanza.

    Non e' cosmetica: l'impronta del contesto (#242) e' SENSIBILE all'ordine — un
    riordino a contenuto invariato fa rispondere 409 a ``/analyze/poi`` — e la
    numerazione dei marker in mappa segue questa lista. Senza il riordino finale
    l'uscita sarebbe ``bank-0, bank-1, bank-2, school, bank-3``.
    """
    lat, lon = _BBOX.center()
    banche = [_poi_a(f"bank-{i}", lat + 0.0001 * i, lon, "Bank") for i in range(4)]
    scuola = _poi_a("school", lat + 0.005, lon, "School")

    selected = overpass_client.select_pois(
        [*banche, scuola], (lat, lon), max_pois=5, per_class_cap=3
    )

    assert [p["id"] for p in selected] == [
        "bank-0",
        "bank-1",
        "bank-2",
        "bank-3",
        "school",
    ]


def test_select_pois_breaks_distance_ties_by_id() -> None:
    """A parita' di distanza vince l'``id`` minore.

    Senza un criterio di rottura dei pareggi due esecuzioni sullo stesso input
    possono produrre prompt diversi e ``repro.prompt_hash`` diverge, rendendo la
    run non ricostruibile.
    """
    lat, lon = _BBOX.center()
    selected = overpass_client.select_pois(
        [_poi_a("b", lat + 0.001, lon), _poi_a("a", lat + 0.001, lon)],
        (lat, lon),
        max_pois=1,
    )

    assert [p["id"] for p in selected] == ["a"]


@respx.mock
async def test_fetch_pois_deduplica_elementi_emessi_da_piu_blocchi() -> None:
    """Lo stesso oggetto OSM emesso da piu' blocchi ``out`` entra una volta sola.

    La query ha un blocco per selettore e ogni ``out`` stampa il PROPRIO set:
    verificato dal vivo sul bbox del Colosseo, dove l'Arco di Costantino
    (``tourism=attraction`` + ``historic=monument``) e la Basilica di San Pietro in
    Vincoli (``amenity=place_of_worship`` + ``tourism=attraction``) arrivano due
    volte. Finche' il taglio era «i primi 20 emessi» i blocchi che li duplicano non
    entravano mai in output; con la selezione per prossimita' i doppioni sono i piu'
    vicini, quindi si mangerebbero i posti proprio delle classi che #254 vuole far
    emergere, e ``zone_composition`` conterebbe tre luoghi di culto dove ce n'e' uno.
    """
    lat, lon = _BBOX.center()
    arco: dict[str, object] = {
        "type": "way",
        "id": 23590989,
        "center": {"lat": lat, "lon": lon},
        "tags": {
            "tourism": "attraction",
            "historic": "monument",
            "name": "Arco di Costantino",
        },
    }
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json={"elements": [arco, dict(arco)]})
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert [p["id"] for p in pois] == ["way/23590989"]


@respx.mock
async def test_fetch_pois_node_and_way_with_same_number_do_not_collide() -> None:
    """Un node e un way con lo stesso numero OSM non condividono lo stesso id (#265).

    node e way vivono in namespace OSM separati: senza il tipo di elemento
    nell'id del POI, i rischi verrebbero attribuiti (da #255) al punto sbagliato
    ogni volta che i due numeri combaciano.
    """
    lat, lon = _BBOX.center()
    nodo: dict[str, object] = {
        "type": "node",
        "id": 123,
        "lat": lat,
        "lon": lon,
        "tags": {"amenity": "bank", "name": "Banca (node)"},
    }
    via: dict[str, object] = {
        "type": "way",
        "id": 123,
        "center": {"lat": lat, "lon": lon},
        "tags": {"tourism": "museum", "name": "Museo (way)"},
    }
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json={"elements": [nodo, via]})
    )

    pois = await fetch_pois(_BBOX, "Roma")

    ids = {p["id"] for p in pois}
    assert ids == {"node/123", "way/123"}
    assert len(pois) == 2


@respx.mock
async def test_fetch_pois_keeps_the_nearest_even_if_emitted_last() -> None:
    """Il POI piu' vicino al centro entra anche se Overpass lo emette per ultimo.

    E' il difetto di #254 preso dal punto d'ingresso reale: l'ordine di emissione
    e' quello dei selettori dichiarati, quindi prima un POI oltre il ventesimo
    posto non entrava mai, per quanto vicino fosse.
    """
    lat, lon = _BBOX.center()
    elements: list[dict[str, object]] = [
        {
            "type": "node",
            "id": 1000 + i,
            "lat": lat + 0.01,
            "lon": lon,
            "tags": {"amenity": "bank", "name": f"Lontana {i}"},
        }
        for i in range(MAX_POIS)
    ]
    elements.append(
        {
            "type": "node",
            "id": 9999,
            "lat": lat,
            "lon": lon,
            "tags": {"tourism": "museum", "name": "Museo sul centro"},
        }
    )
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json={"elements": elements})
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert len(pois) == MAX_POIS
    assert pois[0]["id"] == "node/9999"
    assert "Museum" in {p["terminus_class"] for p in pois}


@respx.mock
async def test_fetch_pois_maps_contract_fields() -> None:
    """POI nel contratto retrieval: id/name/lat/lon/osm_tags/terminus_class/citta."""
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=_sample())
    )

    pois = await fetch_pois(_BBOX, "Roma")

    bank = next(p for p in pois if p["id"] == "node/1001")
    assert bank == {
        "id": "node/1001",
        "name": "Banca Intesa Sanpaolo",
        "lat": pytest.approx(41.8902),
        "lon": pytest.approx(12.4922),
        "osm_tags": "amenity=bank",
        "terminus_class": "Bank",
        "citta": "Roma",
    }


@respx.mock
async def test_fetch_pois_with_cut_estrae_il_taglio_osm_dal_payload() -> None:
    """#251: il taglio dichiarato da Overpass in ``osm3s`` diventa TaglioOsm."""
    payload = {**_sample(), "osm3s": {"timestamp_osm_base": "2026-07-26T17:42:03Z"}}
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )

    pois, taglio = await fetch_pois_with_cut(_BBOX, "Roma")

    assert pois  # stesso bacino di fetch_pois, non è questo il punto del test
    assert taglio == {
        "timestamp_osm_base": "2026-07-26T17:42:03Z",
        "overpass_url": DEFAULT_OVERPASS_URL,
    }


@respx.mock
async def test_fetch_pois_with_cut_assente_quando_payload_non_lo_dichiara() -> None:
    """Payload senza ``osm3s``/``timestamp_osm_base``: taglio assente, non un errore."""
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=_sample())
    )

    pois, taglio = await fetch_pois_with_cut(_BBOX, "Roma")

    assert pois
    assert taglio["timestamp_osm_base"] is None
    assert taglio["overpass_url"] == DEFAULT_OVERPASS_URL


@respx.mock
async def test_fetch_pois_scarta_il_taglio_e_si_comporta_come_prima() -> None:
    """fetch_pois resta un involucro che ritorna solo la lista di POI (#251)."""
    payload = {**_sample(), "osm3s": {"timestamp_osm_base": "2026-07-26T17:42:03Z"}}
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert isinstance(pois, list)
    assert pois and "terminus_class" in pois[0]


@respx.mock
async def test_fetch_pois_enriches_terminus_class() -> None:
    """terminus_class deriva da map_to_terminus; tag sconosciuto -> GenericUrbanPOI."""
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=_sample())
    )

    pois = await fetch_pois(_BBOX, "Roma")
    by_id = {p["id"]: p for p in pois}

    assert by_id["node/1002"]["terminus_class"] == "Museum"
    assert by_id["node/1003"]["terminus_class"] == "GenericUrbanPOI"
    assert by_id["way/2001"]["terminus_class"] == "Railway_station"


@respx.mock
async def test_fetch_pois_uses_way_center_and_skips_untagged() -> None:
    """I way usano 'center' per lat/lon; i nodi senza tag sono scartati."""
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=_sample())
    )

    pois = await fetch_pois(_BBOX, "Roma")
    by_id = {p["id"]: p for p in pois}

    assert "node/1004" not in by_id  # nodo senza tag scartato
    assert by_id["way/2001"]["lat"] == pytest.approx(41.8920)
    assert by_id["way/2001"]["lon"] == pytest.approx(12.4940)


@respx.mock
async def test_fetch_pois_caps_at_max() -> None:
    """Non vengono mai restituiti piu' di MAX_POIS elementi."""
    elements = [
        {
            "type": "node",
            "id": 3000 + i,
            "lat": 41.89,
            "lon": 12.49,
            "tags": {"amenity": "bank", "name": f"Bank {i}"},
        }
        for i in range(MAX_POIS + 20)
    ]
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json={"elements": elements})
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert len(pois) == MAX_POIS


@respx.mock
async def test_fetch_pois_retries_once_then_succeeds() -> None:
    """Timeout alla prima chiamata -> un retry con timeout esteso -> successo."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.TimeoutException("slow"),
            httpx.Response(200, json=_sample()),
        ]
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert route.call_count == 2
    assert len(pois) > 0


@respx.mock
async def test_fetch_pois_retries_on_429_then_succeeds() -> None:
    """429 alla prima chiamata -> un retry -> successo (429 e' ritentabile)."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.Response(429, text="rate limited"),
            httpx.Response(200, json=_sample()),
        ]
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert route.call_count == 2
    assert len(pois) > 0


@respx.mock
async def test_fetch_pois_raises_after_retry_exhausted() -> None:
    """Timeout su entrambi i tentativi -> OverpassError (mappabile a 503)."""
    respx.post(DEFAULT_OVERPASS_URL).mock(side_effect=httpx.TimeoutException("slow"))

    with pytest.raises(OverpassError):
        await fetch_pois(_BBOX, "Roma")


@respx.mock
async def test_fetch_pois_raises_on_http_error() -> None:
    """Status 504 (ritentabile) su entrambi i tentativi -> retry esaurito -> errore."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(504, text="gateway timeout")
    )

    with pytest.raises(OverpassError):
        await fetch_pois(_BBOX, "Roma")

    assert route.call_count == 2


@respx.mock
async def test_fetch_pois_does_not_retry_on_non_retryable_status() -> None:
    """Status non-2xx NON ritentabile (400) -> OverpassError immediata, nessun retry."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(400, text="bad request")
    )

    with pytest.raises(OverpassError):
        await fetch_pois(_BBOX, "Roma")

    assert route.call_count == 1


# --- #232: politica di ritentativo esplicita, e cattura offline che puo' attendere ---
# Le pause NON sono mai reali: ogni test inietta uno ``sleep`` che le registra.


def _recording_sleep(attese: list[float]):  # noqa: ANN202  (closure di test)
    async def _sleep(secondi: float) -> None:
        attese.append(secondi)

    return _sleep


@respx.mock
async def test_offline_policy_supera_due_risposte_ritentabili() -> None:
    """Lo scenario reale del 26/07: 504 poi 429 non devono far fallire la cattura.

    Con la politica interattiva (un solo ritentativo) questa sequenza fallisce: e'
    esattamente il difetto di #232, che aveva costretto a un backoff scritto a mano
    fuori dal codice.
    """
    attese: list[float] = []
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.Response(504, text="gateway timeout"),
            httpx.Response(429, text="rate limited"),
            httpx.Response(200, json=_sample()),
        ]
    )

    pois = await fetch_pois(
        _BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep(attese)
    )

    assert route.call_count == 3
    assert len(pois) > 0
    # Pause crescenti dichiarate dalla politica, nell'ordine.
    assert attese == list(OFFLINE_RETRY.pause_s[:2])


@respx.mock
async def test_politica_interattiva_resta_a_un_solo_ritentativo() -> None:
    """Il percorso /analyze resta fail-fast: nessuna regressione di latenza (#232).

    Un utente sta aspettando: due tentativi e poi l'errore, come prima di #232.
    """
    attese: list[float] = []
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(504, text="gateway timeout")
    )

    with pytest.raises(OverpassError):
        await fetch_pois(_BBOX, "Roma", sleep=_recording_sleep(attese))

    assert route.call_count == 2
    assert len(INTERACTIVE_RETRY.pause_s) == 1
    assert len(attese) == 1
    # I timeout restano quelli di prima di #232: la latenza del caso peggiore su
    # /analyze non cambia (30s + 1s + 60s).
    assert INTERACTIVE_RETRY.timeout_s == 30.0
    assert INTERACTIVE_RETRY.retry_timeout_s == 60.0


@respx.mock
async def test_politica_interattiva_ignora_retry_after() -> None:
    """La pausa interattiva resta 1s anche se il server chiede di piu' (#232).

    È il criterio «nessuna regressione di latenza percepita» preso alla lettera:
    su ``/analyze`` un utente sta aspettando, e allungare l'attesa perché
    Overpass lo chiede peggiorerebbe proprio ciò che si vuole tenere basso. Vale
    anche per ``capture_city`` (#31), dove la pausa cade DENTRO la finestra
    cronometrata di ``switch_ms`` (soglia 5000ms): un cap piu' alto avrebbe fatto
    fallire la metrica di una contribuzione della tesi al primo 429 transitorio.
    """
    attese: list[float] = []
    # Politica reale, NON quella azzerata dalla fixture: qui il valore è il punto.
    monkeypatch_free = replace(overpass_client.INTERACTIVE_RETRY, pause_s=(1.0,))
    respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "60"}, text="rate limited"),
            httpx.Response(200, json=_sample()),
        ]
    )

    await fetch_pois(
        _BBOX, "Roma", retry=monkeypatch_free, sleep=_recording_sleep(attese)
    )

    assert attese == [1.0]
    assert INTERACTIVE_RETRY.retry_after_cap_s is None


@respx.mock
async def test_retry_after_oltre_il_tetto_fa_rinunciare_subito() -> None:
    """Se il server chiede piu' del tetto, si rinuncia invece di ritentare presto.

    Ritentare prima di quanto Overpass ha chiesto sarebbe hammering verso un
    servizio pubblico gratuito (#232 lo esclude esplicitamente) e brucerebbe i
    ritentativi restanti in tentativi con probabilita' nulla. Il messaggio dice
    quanto il server ha chiesto, così l'operatore sa quando riprovare.
    """
    attese: list[float] = []
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(
            429, headers={"Retry-After": "3600"}, text="rate limited"
        )
    )

    with pytest.raises(OverpassError, match="3600"):
        await fetch_pois(
            _BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep(attese)
        )

    assert route.call_count == 1  # nessun secondo tentativo
    assert attese == []  # e nessuna attesa spesa


@respx.mock
async def test_ritentativi_lasciano_traccia_nei_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ogni ritentativo è dichiarato (#232): con la politica offline l'attesa
    complessiva arriva a minuti, e senza traccia «processo appeso» e «backoff di
    cortesia in corso» sono indistinguibili — la condizione che il 26/07 ha
    spinto a scrivere il backoff a mano in una shell."""
    respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.Response(504, text="gateway timeout"),
            httpx.Response(200, json=_sample()),
        ]
    )

    with caplog.at_level("WARNING"):
        await fetch_pois(_BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep([]))

    messaggi = [r.getMessage() for r in caplog.records]
    assert any("504" in m and "ritentativo 1/4" in m for m in messaggi), messaggi


@respx.mock
async def test_retry_after_e_onorato_quando_supera_la_pausa_prevista() -> None:
    """``Retry-After: 30`` con pausa prevista di 5s -> si attende 30s (#232)."""
    attese: list[float] = []
    respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "30"}, text="rate limited"),
            httpx.Response(200, json=_sample()),
        ]
    )

    await fetch_pois(_BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep(attese))

    assert attese == [30.0]


@respx.mock
async def test_retry_after_non_accorcia_la_pausa_di_cortesia() -> None:
    """``Retry-After: 1`` non abbassa la pausa sotto quella prevista: verso un
    servizio pubblico gratuito la cortesia e' un minimo, non un massimo (#232)."""
    attese: list[float] = []
    respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "1"}, text="rate limited"),
            httpx.Response(200, json=_sample()),
        ]
    )

    await fetch_pois(_BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep(attese))

    assert attese == [OFFLINE_RETRY.pause_s[0]]


@respx.mock
async def test_retry_after_illeggibile_ricade_sulla_pausa_prevista() -> None:
    """Forma HTTP-date di ``Retry-After``: non interpretata, si usa la pausa
    prevista invece di fallire o di attendere a caso (#232)."""
    attese: list[float] = []
    respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.Response(
                429,
                headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"},
                text="rate limited",
            ),
            httpx.Response(200, json=_sample()),
        ]
    )

    await fetch_pois(_BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep(attese))

    assert attese == [OFFLINE_RETRY.pause_s[0]]


@respx.mock
async def test_status_non_ritentabile_non_attende_mai() -> None:
    """Un 400 non e' transitorio: nessuna pausa, errore immediato (#232)."""
    attese: list[float] = []
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(400, text="bad request")
    )

    with pytest.raises(OverpassError):
        await fetch_pois(
            _BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep(attese)
        )

    assert attese == []


@respx.mock
async def test_offline_policy_esaurita_solleva_overpass_error() -> None:
    """Anche la politica lunga ha un limite: esaurita, errore chiaro (#232)."""
    attese: list[float] = []
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(429, text="rate limited")
    )

    with pytest.raises(OverpassError):
        await fetch_pois(
            _BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep(attese)
        )

    assert route.call_count == 1 + len(OFFLINE_RETRY.pause_s)
    assert attese == list(OFFLINE_RETRY.pause_s)


def test_politica_offline_attende_piu_della_interattiva() -> None:
    """La cattura offline puo' permettersi minuti, l'interattivo no (#232): il
    contratto fra le due politiche e' esplicito e verificato, non implicito."""
    assert sum(OFFLINE_RETRY.pause_s) > sum(INTERACTIVE_RETRY.pause_s)
    assert len(OFFLINE_RETRY.pause_s) > len(INTERACTIVE_RETRY.pause_s)
    # Solo la politica offline onora Retry-After; l'interattiva lo ignora.
    assert INTERACTIVE_RETRY.retry_after_cap_s is None
    assert OFFLINE_RETRY.retry_after_cap_s is not None


def test_il_tetto_non_accorcia_le_pause_dichiarate() -> None:
    """Il tetto vale sulla richiesta del server, non sulla pausa della politica.

    Con ``min(attesa, cap)`` una politica futura con pause piu' lunghe del tetto
    si sarebbe vista accorciare la cortesia in silenzio: invariante esplicitata
    qui invece di restare implicita nei valori attuali (review m1).
    """
    assert OFFLINE_RETRY.retry_after_cap_s is not None
    lunga = replace(OFFLINE_RETRY, pause_s=(300.0,), retry_after_cap_s=60.0)
    assert (
        overpass_client._attesa_prima_del_ritentativo(  # pyright: ignore[reportPrivateUsage]
            None, lunga.pause_s[0], lunga.retry_after_cap_s
        )
        == 300.0
    )


@respx.mock
async def test_fetch_pois_query_uses_key_value_selectors_and_caps() -> None:
    """La query usa selettori k=v con un cap 'out center' per-selettore."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json={"elements": []})
    )

    await fetch_pois(_BBOX, "Roma", ["amenity=bank", "tourism=museum"])

    body = route.calls.last.request.content.decode()
    assert "41.88,12.48,41.9,12.5" in body
    assert 'node["amenity"="bank"]' in body
    assert 'way["tourism"="museum"]' in body
    assert f"out center {PER_SELECTOR_CAP}" in body
    assert "[out:json][timeout:25]" in body
    # due 'out center' per selettore (unione node+way e relation, #314): con 2
    # selettori devono essere esattamente 4 blocchi.
    assert body.count(f"out center {PER_SELECTOR_CAP}") == 4


# --- #314: le relation (multipoligoni) entrano nel bacino di candidati ---
# Molti monumenti iconici sono mappati come relation: il Colosseo e' relation/1834818
# a 9 m dal centro del bbox di Roma, il Duomo di Milano relation/18017026. Con una
# query solo node+way non entravano mai nel campione, per quanto vicini fossero.


@respx.mock
async def test_query_interroga_anche_le_relation_per_ogni_selettore() -> None:
    """Ogni selettore interroga anche le relation, con ``out center``: senza
    ``center`` una relation non ha coordinate e verrebbe scartata dal parsing."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json={"elements": []})
    )

    await fetch_pois(_BBOX, "Roma", ["historic=archaeological_site", "tourism=museum"])

    body = route.calls.last.request.content.decode()
    bbox_str = "41.88,12.48,41.9,12.5"
    for key, value in (("historic", "archaeological_site"), ("tourism", "museum")):
        assert (
            f'relation["{key}"="{value}"]({bbox_str});\nout center {PER_SELECTOR_CAP};'
        ) in body
    # Ogni tipo dichiarato come interrogato compare davvero nella query: la
    # costante registrata nella provenienza degli snapshot non puo' divergere.
    for tipo in overpass_client.TIPI_ELEMENTO:
        assert f"{tipo}[" in body


@respx.mock
async def test_relation_con_tetto_proprio_e_blocco_node_way_invariato() -> None:
    """Le relation hanno un ``out`` separato, il blocco node+way resta identico.

    Due motivi. Overpass stampa un set in ordine di tipo (node, way, relation):
    dentro l'unione col tetto ``out center N`` un selettore denso come
    ``tourism=attraction`` esaurirebbe i posti con node e way prima di arrivare al
    Colosseo, cioe' il difetto che #314 chiude. E il blocco node+way invariato al
    byte vuol dire che il bacino node+way di prima resta lo stesso: il cambio
    AGGIUNGE candidati, non ne sostituisce.
    """
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json={"elements": []})
    )

    await fetch_pois(_BBOX, "Roma", ["amenity=bank", "tourism=museum"])

    body = route.calls.last.request.content.decode()
    bbox_str = "41.88,12.48,41.9,12.5"
    assert (
        f'(\n  node["amenity"="bank"]({bbox_str});\n'
        f'  way["amenity"="bank"]({bbox_str});\n);\n'
        f"out center {PER_SELECTOR_CAP};"
    ) in body
    # Un out per l'unione node+way e uno per le relation, per ciascun selettore.
    assert body.count(f"out center {PER_SELECTOR_CAP};") == 4
    # Le relation NON stanno dentro l'unione col tetto condiviso.
    assert "  relation[" not in body


def _relation(
    rel_id: int, lat: float, lon: float, tags: dict[str, str]
) -> dict[str, object]:
    """Elemento relation come lo restituisce Overpass con ``out center``."""
    return {
        "type": "relation",
        "id": rel_id,
        "center": {"lat": lat, "lon": lon},
        "tags": tags,
    }


def _overpass_che_rispetta_la_query(
    altri: list[dict[str, object]], relations: list[dict[str, object]]
) -> Callable[[httpx.Request], httpx.Response]:
    """``side_effect`` respx: le relation arrivano SOLO se la query le chiede.

    Un mock che restituisce le relation qualunque sia la query verifica il
    parsing, non #314: resterebbe verde anche togliendo il blocco relation da
    ``_build_query``. Cosi' invece il test diventa rosso, come farebbe Overpass.
    """

    def _rispondi(request: httpx.Request) -> httpx.Response:
        chiede_relation = "relation[" in request.content.decode()
        elementi = altri + (relations if chiede_relation else [])
        return httpx.Response(200, json={"elements": elementi})

    return _rispondi


@respx.mock
async def test_relation_diventa_poi_con_id_tipizzato_e_coordinate_dal_center() -> None:
    """Una relation chiesta dalla query passa dal parsing come un way: coordinate
    da ``center``, id ``relation/<n>``, classe TERMINUS dagli stessi selettori e
    priorita'."""
    duomo = _relation(
        18017026,
        45.4641844,
        9.1916105,
        {
            "type": "multipolygon",
            "amenity": "place_of_worship",
            "building": "cathedral",
            "tourism": "attraction",
            "name": "Duomo di Milano",
        },
    )
    respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=_overpass_che_rispetta_la_query([], [duomo])
    )

    pois = await fetch_pois(Bbox(45.46, 9.18, 45.47, 9.20), "Milano")

    assert pois == [
        {
            "id": "relation/18017026",
            "name": "Duomo di Milano",
            "lat": pytest.approx(45.4641844),
            "lon": pytest.approx(9.1916105),
            "osm_tags": "amenity=place_of_worship",
            "terminus_class": "Place_of_worship",
            "citta": "Milano",
        }
    ]


@respx.mock
async def test_relation_vicina_al_centro_entra_nel_campione() -> None:
    """Il caso dell'issue: la relation a pochi metri dal centro entra per prima,
    anche con il bacino pieno di node piu' lontani.

    Overpass finto che restituisce il Colosseo solo se la query chiede le
    relation: senza il blocco relation in ``_build_query`` il campione sarebbe
    fatto dei soli node, cioe' il difetto di #314.
    """
    lat, lon = _BBOX.center()
    nodi: list[dict[str, object]] = [
        {
            "type": "node",
            "id": 5000 + i,
            "lat": lat + 0.005,
            "lon": lon,
            "tags": {"tourism": "attraction", "name": f"Attrazione {i}"},
        }
        for i in range(MAX_POIS)
    ]
    colosseo = _relation(
        1834818,
        lat + 0.00008,
        lon,
        {
            "type": "multipolygon",
            "historic": "archaeological_site",
            "tourism": "attraction",
            "name": "Colosseo",
        },
    )
    respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=_overpass_che_rispetta_la_query(nodi, [colosseo])
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert pois[0]["id"] == "relation/1834818"
    assert pois[0]["name"] == "Colosseo"


@respx.mock
async def test_relation_emessa_da_piu_blocchi_entra_una_volta() -> None:
    """Il Colosseo porta sia ``tourism=attraction`` sia
    ``historic=archaeological_site``: arriva dal blocco di ciascun selettore e
    deve contare una volta sola, come gia' per node e way."""
    lat, lon = _BBOX.center()
    colosseo = _relation(
        1834818,
        lat,
        lon,
        {
            "historic": "archaeological_site",
            "tourism": "attraction",
            "name": "Colosseo",
        },
    )
    respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=_overpass_che_rispetta_la_query([], [colosseo, dict(colosseo)])
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert [p["id"] for p in pois] == ["relation/1834818"]


@respx.mock
async def test_relation_e_way_con_lo_stesso_numero_non_collidono() -> None:
    """Le relation hanno un namespace OSM proprio, come node e way (#265)."""
    lat, lon = _BBOX.center()
    via: dict[str, object] = {
        "type": "way",
        "id": 77,
        "center": {"lat": lat, "lon": lon},
        "tags": {"tourism": "museum", "name": "Museo (way)"},
    }
    rel = _relation(77, lat, lon, {"amenity": "place_of_worship", "name": "Chiesa"})
    respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=_overpass_che_rispetta_la_query([via], [rel])
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert {p["id"] for p in pois} == {"way/77", "relation/77"}


@respx.mock
async def test_parsing_scarta_una_relation_senza_center() -> None:
    """Non-regressione del parsing, non verifica di #314: una relation senza
    ``center`` (es. ``out`` senza center) non ha coordinate utilizzabili e va
    scartata, non piazzata a caso. Passa a prescindere dalla query, di proposito:
    la presenza del blocco relation la verificano i test qui sopra."""
    payload = {
        "elements": [
            {
                "type": "relation",
                "id": 1834818,
                "tags": {"historic": "archaeological_site", "name": "Colosseo"},
            }
        ]
    }
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )

    assert await fetch_pois(_BBOX, "Roma") == []


@respx.mock
async def test_fetch_pois_sets_explicit_user_agent() -> None:
    """UA esplicito sulla richiesta Overpass (non il default httpx): evita il 406."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json={"elements": []})
    )

    await fetch_pois(_BBOX, "Roma", ["amenity=bank"])

    assert (
        route.calls.last.request.headers.get("user-agent")
        == "crime-risk-analyzer (https://github.com/Salvo-Rosolia/crime-risk-analyzer)"
    )


@respx.mock
async def test_fetch_pois_user_agent_includes_contact_url() -> None:
    """La usage policy Overpass richiede un contatto nell'UA (fail-if-removed)."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json={"elements": []})
    )

    await fetch_pois(_BBOX, "Roma", ["amenity=bank"])

    user_agent = route.calls.last.request.headers.get("user-agent")
    assert user_agent is not None
    assert "https://github.com/Salvo-Rosolia/crime-risk-analyzer" in user_agent


@respx.mock
async def test_fetch_pois_raises_on_network_error() -> None:
    """Errore di rete non-timeout (es. connessione) -> OverpassError immediata.

    Politica di default (interattiva): il percorso /analyze non deve guadagnare
    latenza per un blip di trasporto, quindi nessun ritentativo aggiuntivo (#247).
    """
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=httpx.ConnectError("refused")
    )

    with pytest.raises(OverpassError):
        await fetch_pois(_BBOX, "Roma")

    assert route.call_count == 1


# --- #247: blip di trasporto (non-timeout) ritentabili SOLO in cattura offline ---


@respx.mock
async def test_offline_policy_ritenta_su_errore_di_connessione_poi_riesce() -> None:
    """Un ConnectError transitorio non e' piu' definitivo in cattura offline: #232
    aveva chiuso timeout e status transitori, non i blip di trasporto (#247)."""
    attese: list[float] = []
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.ConnectError("connection refused"),
            httpx.Response(200, json=_sample()),
        ]
    )

    pois = await fetch_pois(
        _BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep(attese)
    )

    assert route.call_count == 2
    assert len(pois) > 0
    assert attese == [OFFLINE_RETRY.pause_s[0]]


@respx.mock
async def test_offline_policy_ritenta_su_remote_protocol_error() -> None:
    """Il server che chiude la connessione senza risposta e' transitorio quanto
    un 504: Overpass sotto carico lo fa almeno quanto restituisce 504 (#247)."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.RemoteProtocolError(
                "Server disconnected without sending a response."
            ),
            httpx.Response(200, json=_sample()),
        ]
    )

    pois = await fetch_pois(
        _BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep([])
    )

    assert route.call_count == 2
    assert len(pois) > 0


@respx.mock
async def test_offline_policy_ritenta_su_read_error() -> None:
    """Connessione interrotta a lettura in corso: stesso trattamento (#247)."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.ReadError("connection reset"),
            httpx.Response(200, json=_sample()),
        ]
    )

    pois = await fetch_pois(
        _BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep([])
    )

    assert route.call_count == 2
    assert len(pois) > 0


@respx.mock
async def test_offline_policy_esaurita_su_trasporto_solleva_overpass_error() -> None:
    """Un blip di trasporto persistente si arrende come qualunque altro
    ritentabile esaurito: non resta appeso (#247)."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=httpx.ConnectError("refused")
    )

    with pytest.raises(OverpassError):
        await fetch_pois(_BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep([]))

    assert route.call_count == 1 + len(OFFLINE_RETRY.pause_s)


@respx.mock
async def test_offline_policy_non_ritenta_errori_di_trasporto_non_elencati() -> None:
    """Un errore di trasporto FUORI dall'elenco esplicito resta definitivo anche
    in cattura offline: solo connessione/protocollo remoto/lettura sono blip
    transitori, non qualunque ``httpx.HTTPError`` (#247)."""
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=httpx.LocalProtocolError("malformed request")
    )

    with pytest.raises(OverpassError):
        await fetch_pois(_BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep([]))

    assert route.call_count == 1


@respx.mock
async def test_ritentativo_su_errore_di_trasporto_lascia_traccia_nei_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Il log distingue un blip di trasporto da un vero timeout: altrimenti
    l'operatore legge «timeout» dove c'era una connessione rifiutata (#247)."""
    respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.ConnectError("connection refused"),
            httpx.Response(200, json=_sample()),
        ]
    )

    with caplog.at_level("WARNING"):
        await fetch_pois(_BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep([]))

    messaggi = [r.getMessage() for r in caplog.records]
    trovato = any(
        "errore di trasporto" in m and "ritentativo 1/4" in m for m in messaggi
    )
    assert trovato, messaggi


@respx.mock
async def test_fetch_pois_raises_on_invalid_json() -> None:
    """Risposta 200 ma body non-JSON -> OverpassError."""
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, text="not json")
    )

    with pytest.raises(OverpassError):
        await fetch_pois(_BBOX, "Roma")


# --- parsing edge case (esercitati via API pubblica) ---


@respx.mock
async def test_fetch_pois_tag_priority_amenity_over_shop() -> None:
    """Con piu' chiavi note vince la priorita' (amenity prima di shop)."""
    payload = {
        "elements": [
            {
                "type": "node",
                "id": 1,
                "lat": 41.0,
                "lon": 12.0,
                "tags": {"shop": "mall", "amenity": "bank", "name": "X"},
            }
        ]
    }
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert pois[0]["osm_tags"] == "amenity=bank"
    assert pois[0]["terminus_class"] == "Bank"


@respx.mock
async def test_fetch_pois_picks_first_mapped_selector_not_first_present() -> None:
    """Un tag a priorita' alta ma NON mappato non vince: si sceglie il primo mappato."""
    payload = {
        "elements": [
            {
                "type": "node",
                "id": 11,
                "lat": 41.0,
                "lon": 12.0,
                "tags": {"amenity": "bar", "building": "warehouse", "name": "Deposito"},
            }
        ]
    }
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )

    pois = await fetch_pois(_BBOX, "Roma")

    # amenity=bar e' presente e a priorita' piu' alta ma NON e' nel dict -> si salta;
    # building=warehouse e' mappato -> vince.
    assert pois[0]["osm_tags"] == "building=warehouse"
    assert pois[0]["terminus_class"] == "Warehouse"


@respx.mock
async def test_fetch_pois_unknown_tag_yields_generic() -> None:
    """Elemento con soli tag non mappati -> osm_tags vuoto e GenericUrbanPOI."""
    payload = {
        "elements": [
            {
                "type": "node",
                "id": 7,
                "lat": 41.0,
                "lon": 12.0,
                "tags": {"leisure": "park", "name": "Parco"},
            }
        ]
    }
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert pois[0]["osm_tags"] == ""
    assert pois[0]["terminus_class"] == "GenericUrbanPOI"


@respx.mock
async def test_fetch_pois_element_without_coords_or_center_is_skipped() -> None:
    """Elemento con tag ma senza lat/lon ne' 'center' viene scartato."""
    payload = {
        "elements": [
            {"type": "node", "id": 8, "tags": {"amenity": "bank", "name": "X"}}
        ]
    }
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )

    assert await fetch_pois(_BBOX, "Roma") == []


@respx.mock
async def test_fetch_pois_element_without_type_is_skipped() -> None:
    """Elemento senza ``type`` viene scartato invece di produrre un id ``"/123"``.

    Un fallback silenzioso a stringa vuota riaprirebbe la stessa collisione fra
    ``id`` diversi che #265 chiude: due elementi ugualmente privi di ``type``
    finirebbero entrambi su ``"/<numero>"``.
    """
    payload = {
        "elements": [
            {
                "id": 55,
                "lat": 41.0,
                "lon": 12.0,
                "tags": {"amenity": "bank", "name": "X"},
            }
        ]
    }
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )

    assert await fetch_pois(_BBOX, "Roma") == []


@respx.mock
async def test_fetch_pois_way_without_coords_is_skipped() -> None:
    """Way con center privo di coordinate numeriche viene scartato."""
    payload = {
        "elements": [
            {
                "type": "way",
                "id": 9,
                "center": {"foo": "bar"},
                "tags": {"amenity": "bank", "name": "X"},
            }
        ]
    }
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )

    assert await fetch_pois(_BBOX, "Roma") == []


@respx.mock
async def test_fetch_pois_payload_not_object_raises() -> None:
    """Payload JSON non-oggetto (lista) -> OverpassError."""
    respx.post(DEFAULT_OVERPASS_URL).mock(return_value=httpx.Response(200, json=["x"]))

    with pytest.raises(OverpassError):
        await fetch_pois(_BBOX, "Roma")


@respx.mock
async def test_fetch_pois_missing_elements_raises() -> None:
    """Payload privo della lista 'elements' -> OverpassError."""
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json={"version": 0.6})
    )

    with pytest.raises(OverpassError):
        await fetch_pois(_BBOX, "Roma")


@respx.mock
async def test_fetch_pois_skips_non_dict_elements() -> None:
    """Elementi non-oggetto nella lista vengono ignorati senza errore."""
    payload = {
        "elements": [
            "garbage",
            {
                "type": "node",
                "id": 1,
                "lat": 41.0,
                "lon": 12.0,
                "tags": {"amenity": "bank", "name": "B"},
            },
        ]
    }
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=payload)
    )

    pois = await fetch_pois(_BBOX, "Roma")
    assert len(pois) == 1
    assert pois[0]["id"] == "node/1"


# --- #372: ``remark`` di Overpass e risposte troncate ---
# Quando scatta ``[timeout:25]`` (o la memoria lato server) Overpass risponde
# 200 con un campo ``remark`` e gli elementi trovati FINO A LI': i selettori in
# fondo alla query mancano. Le forme d'interruzione sotto seguono il prefisso
# ``runtime error:``; quelle senza prefisso esercitano le frasi di riserva di
# ``_INDIZI_INTERRUZIONE`` nel caso il prefisso cambiasse.

_REMARK_TIMEOUT = (
    'runtime error: Query timed out in "query" at line 3 after 26 seconds.'
)

_REMARK_MEMORIA = "runtime error: Query run out of memory using about 2048 MB of RAM."

_REMARK_INCOMPLETI = (
    _REMARK_TIMEOUT,
    _REMARK_MEMORIA,
    'runtime error: Query timed out in "recurse" at line 41 after 25 seconds.',
    'runtime error: Query run out of memory in "query" at line 7 using about '
    "2048 MB of RAM.",
    'runtime error: Query ran out of memory in "union" at line 12. It would need '
    "at least 0 MB of RAM to continue.",
    "Runtime error: something went wrong while executing the query.",
    # Senza il prefisso ``runtime error``: rilevati solo dalle frasi di riserva.
    'Error: Query timed out in "query" at line 3 after 26 seconds.',
    "Query ran out of memory",
    "Query run out of memory",
)

# Forme IPOTETICHE, difensive: non e' dimostrato che Overpass le emetta. Se mai
# comparisse un remark che non dichiara un'interruzione, non va ritentato.
_REMARK_INFORMATIVI = (
    "runtime remark: Timeout is 180 and maxsize is 536870912.",
    "runtime remark: The query has been executed with the attic data.",
    "",
)


@pytest.mark.parametrize("remark", _REMARK_INCOMPLETI)
def test_remark_di_interruzione_segnala_risposta_incompleta(remark: str) -> None:
    assert remark_segnala_risposta_incompleta(remark) is True


@pytest.mark.parametrize("remark", _REMARK_INFORMATIVI)
def test_remark_informativo_non_segnala_risposta_incompleta(remark: str) -> None:
    assert remark_segnala_risposta_incompleta(remark) is False


#: Id del campione completo dopo ``select_pois`` (node/1004 non ha nome); la
#: risposta troncata porta solo node/1001.
_ID_CAMPIONE_COMPLETO = ["node/1001", "node/1002", "node/1003", "way/2001"]


def _troncata() -> dict[str, object]:
    """Risposta 200 troncata: il primo elemento del campione e il remark di timeout."""
    sample = _sample()
    elements = cast(list[object], sample["elements"])
    return {**sample, "elements": elements[:1], "remark": _REMARK_TIMEOUT}


@respx.mock
async def test_remark_di_timeout_non_e_accettato_come_campione_completo() -> None:
    """Una risposta troncata non e' un campione completo.

    Ritentativi esauriti -> :class:`OverpassError`.
    """
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=_troncata())
    )

    with pytest.raises(OverpassError) as exc_info:
        await fetch_pois(_BBOX, "Roma")

    messaggio = str(exc_info.value)
    assert "Risposta incompleta di Overpass" in messaggio
    assert _REMARK_TIMEOUT in messaggio
    assert "dopo 2 tentativi" in messaggio
    # Politica interattiva: un tentativo + un ritentativo, poi l'errore.
    assert route.call_count == 1 + len(overpass_client.INTERACTIVE_RETRY.pause_s)


@respx.mock
async def test_remark_di_timeout_esaurisce_anche_la_politica_offline() -> None:
    attese: list[float] = []
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=_troncata())
    )

    with pytest.raises(
        OverpassError, match=r"Risposta incompleta di Overpass.*dopo 5 tentativi"
    ):
        await fetch_pois_with_cut(
            _BBOX, "Roma", retry=OFFLINE_RETRY, sleep=_recording_sleep(attese)
        )

    assert route.call_count == 1 + len(OFFLINE_RETRY.pause_s)
    assert attese == list(OFFLINE_RETRY.pause_s)


@respx.mock
async def test_remark_di_memoria_non_e_descritto_come_timeout() -> None:
    """Un out of memory non e' un timeout, e senza ritentativi non si dice «dopo»."""
    sample = {**_sample(), "remark": _REMARK_MEMORIA}
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=sample)
    )
    senza_ritentativi = replace(INTERACTIVE_RETRY, pause_s=())

    with pytest.raises(OverpassError) as exc_info:
        await fetch_pois(_BBOX, "Roma", retry=senza_ritentativi)

    messaggio = str(exc_info.value)
    assert "timeout" not in messaggio.lower()
    assert "tentativi" not in messaggio
    assert "Risposta incompleta di Overpass" in messaggio
    assert _REMARK_MEMORIA in messaggio
    assert route.call_count == 1


@respx.mock
async def test_remark_di_timeout_poi_risposta_completa_ritenta_e_usa_la_seconda(
    caplog: pytest.LogCaptureFixture,
) -> None:
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        side_effect=[
            httpx.Response(200, json=_troncata()),
            httpx.Response(200, json=_sample()),
        ]
    )

    with caplog.at_level("WARNING"):
        pois = await fetch_pois(_BBOX, "Roma")

    assert route.call_count == 2
    # Il campione e' quello della seconda risposta, non quello troncato.
    assert sorted(p["id"] for p in pois) == _ID_CAMPIONE_COMPLETO
    messaggi = [r.getMessage() for r in caplog.records]
    assert any(
        "risposta incompleta" in m and "ritentativo 1/1" in m for m in messaggi
    ), messaggi


@respx.mock
async def test_remark_informativo_non_fa_fallire_ne_ritentare() -> None:
    sample = {**_sample(), "remark": _REMARK_INFORMATIVI[0]}
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=sample)
    )

    pois = await fetch_pois(_BBOX, "Roma")

    assert route.call_count == 1
    assert sorted(p["id"] for p in pois) == _ID_CAMPIONE_COMPLETO


@respx.mock
async def test_remark_non_stringa_non_fa_fallire() -> None:
    """Un ``remark`` di forma inattesa non e' un'interruzione dichiarata."""
    sample = {**_sample(), "remark": None}
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=sample)
    )

    await fetch_pois(_BBOX, "Roma")

    assert route.call_count == 1


@respx.mock
async def test_capture_non_scrive_snapshot_da_una_risposta_troncata(
    tmp_path: Path,
) -> None:
    """Un campione incompleto non deve finire su disco come se fosse completo."""
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=_troncata())
    )

    async def inner(bbox: Bbox, citta: str) -> tuple[list[Poi], TaglioOsm | None]:
        return await fetch_pois_with_cut(
            bbox, citta, retry=OFFLINE_RETRY, sleep=_recording_sleep([])
        )

    path = tmp_path / "snap.json"
    source = capturing_source(path, inner=inner, zona="Colosseo")

    with pytest.raises(OverpassError, match="incompleta di Overpass"):
        await source(_BBOX, "Roma")

    assert not path.exists()


@pytest.mark.integration
async def test_fetch_pois_integration_real_overpass() -> None:
    """Integrazione reale con Overpass (skip di default; -m integration per girarlo)."""
    pois = await fetch_pois(
        Bbox(41.889, 12.490, 41.892, 12.494), "Roma", ["amenity=bank", "tourism=museum"]
    )
    assert isinstance(pois, list)
