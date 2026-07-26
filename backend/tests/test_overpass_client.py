"""Test del client Overpass -> POI on-demand (#16). Le risposte HTTP sono mockate."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
import respx

from crime_risk_analyzer import overpass_client
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.overpass_client import (
    DEFAULT_OVERPASS_URL,
    INTERACTIVE_RETRY,
    MAX_POIS,
    OFFLINE_RETRY,
    PER_SELECTOR_CAP,
    OverpassError,
    fetch_pois,
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


@respx.mock
async def test_fetch_pois_maps_contract_fields() -> None:
    """POI nel contratto retrieval: id/name/lat/lon/osm_tags/terminus_class/citta."""
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=_sample())
    )

    pois = await fetch_pois(_BBOX, "Roma")

    bank = next(p for p in pois if p["id"] == "1001")
    assert bank == {
        "id": "1001",
        "name": "Banca Intesa Sanpaolo",
        "lat": pytest.approx(41.8902),
        "lon": pytest.approx(12.4922),
        "osm_tags": "amenity=bank",
        "terminus_class": "Bank",
        "citta": "Roma",
    }


@respx.mock
async def test_fetch_pois_enriches_terminus_class() -> None:
    """terminus_class deriva da map_to_terminus; tag sconosciuto -> GenericUrbanPOI."""
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=_sample())
    )

    pois = await fetch_pois(_BBOX, "Roma")
    by_id = {p["id"]: p for p in pois}

    assert by_id["1002"]["terminus_class"] == "Museum"
    assert by_id["1003"]["terminus_class"] == "GenericUrbanPOI"
    assert by_id["2001"]["terminus_class"] == "Railway_station"


@respx.mock
async def test_fetch_pois_uses_way_center_and_skips_untagged() -> None:
    """I way usano 'center' per lat/lon; i nodi senza tag sono scartati."""
    respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json=_sample())
    )

    pois = await fetch_pois(_BBOX, "Roma")
    by_id = {p["id"]: p for p in pois}

    assert "1004" not in by_id  # nodo senza tag scartato
    assert by_id["2001"]["lat"] == pytest.approx(41.8920)
    assert by_id["2001"]["lon"] == pytest.approx(12.4940)


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
    # un 'out center' per selettore: con 2 selettori devono essere
    # esattamente 2 blocchi.
    assert body.count(f"out center {PER_SELECTOR_CAP}") == 2


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
    """Errore di rete non-timeout (es. connessione) -> OverpassError."""
    respx.post(DEFAULT_OVERPASS_URL).mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(OverpassError):
        await fetch_pois(_BBOX, "Roma")


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
    assert pois[0]["id"] == "1"


@pytest.mark.integration
async def test_fetch_pois_integration_real_overpass() -> None:
    """Integrazione reale con Overpass (skip di default; -m integration per girarlo)."""
    pois = await fetch_pois(
        Bbox(41.889, 12.490, 41.892, 12.494), "Roma", ["amenity=bank", "tourism=museum"]
    )
    assert isinstance(pois, list)
