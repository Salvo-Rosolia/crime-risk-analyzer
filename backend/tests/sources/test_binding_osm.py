"""Binding OSM, etichette e catalogo POI letti dal set attivo (#413).

Con il set di default tutto resta identico alle costanti; con un set custom le
stesse funzioni leggono il binding e le etichette del set, e due set diversi non
si mescolano (cache comprese).
"""

from __future__ import annotations

import dataclasses
import urllib.parse
from typing import cast

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from rdflib import Graph

from crime_risk_analyzer import main as main_module
from crime_risk_analyzer.errors import register_exception_handlers
from crime_risk_analyzer.i18n import terminus_labels
from crime_risk_analyzer.i18n.terminus_labels import (
    controlled_vocab_for,
    label_en,
    label_it,
)
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.overpass_client import (
    DEFAULT_OVERPASS_URL,
    _extract_osm_tag,  # pyright: ignore[reportPrivateUsage]
    _parse_elements,  # pyright: ignore[reportPrivateUsage]
    fetch_pois,
)
from crime_risk_analyzer.poi_types import (
    PoiType,
    UnknownPoiTypeError,
    poi_types,
    resolve_poi_type,
)
from crime_risk_analyzer.sources import routes
from crime_risk_analyzer.sources.build import build_source_set
from crime_risk_analyzer.sources.context import (
    DEFAULT_ID,
    bind,
    current_labels,
    current_osm,
    default_set,
)
from crime_risk_analyzer.sources.model import OsmBinding, SourceSet
from crime_risk_analyzer.sources.parsing import ParsedSources
from crime_risk_analyzer.sources.report import SourceValidationError
from crime_risk_analyzer.sources.session import SessionStore
from crime_risk_analyzer.sources.vocabulary import TERMINUS_VOCABULARY
from crime_risk_analyzer.sparql_module.osm_mapping import (
    ORDINE_FAMIGLIE,
    OSM_SELECTORS,
    OSM_TO_TERMINUS,
    SELETTORI_CEDEVOLI,
)

SID = "sessione-di-prova-AAAA"


def _custom(id_: str = "c1", **campi: object) -> SourceSet:
    osm = OsmBinding(
        osm_to_class={
            "amenity=bank": "Banca",
            "shop=kiosk": "Gas_station",
            "tourism=attraction": "Monumento",
            "historic=ruins": "Rovina",
        },
        ordine_famiglie=("shop", "amenity", "tourism", "historic"),
        selettori_cedevoli={"tourism=attraction": "historic"},
    )
    labels = {
        "Banca": ("Istituto di credito", "Bank"),
        "Monumento": ("Monumento", "Monument"),
        "Rovina": ("", "Ruin"),
    }
    base = dataclasses.replace(
        default_set(), id=id_, kind="custom", osm=osm, labels=labels
    )
    return dataclasses.replace(base, **campi)  # pyright: ignore[reportArgumentType]


def _parsed_con(labels: dict[str, tuple[str, str]]) -> ParsedSources:
    """Fonti gia' lette con una classe per etichetta (binding minimo)."""
    return ParsedSources(
        graph=Graph(),
        vocabulary=TERMINUS_VOCABULARY,
        classes=frozenset(labels),
        labels=labels,
        osm_to_class={f"amenity=t{i}": c for i, c in enumerate(labels)},
        ordine_famiglie=("amenity",),
        istat=None,  # pyright: ignore[reportArgumentType]
        mappatura={},
        voci_rottura=frozenset(),
        versione="v",
    )


# --- default identico ---


def test_default_binding_e_le_costanti() -> None:
    osm = current_osm()
    assert dict(osm.osm_to_class) == OSM_TO_TERMINUS
    assert osm.ordine_famiglie == ORDINE_FAMIGLIE
    assert dict(osm.selettori_cedevoli) == SELETTORI_CEDEVOLI
    assert osm.selectors == OSM_SELECTORS
    assert current_labels() is None


def test_default_etichette_dal_json() -> None:
    # Valori letterali del JSON TERMINUS, non un confronto del codice con se stesso.
    assert label_it("Bank") == "Banca"
    assert label_en("Bank") == "Bank"
    # classe assente dal JSON: fallback sul nome normalizzato (IT ed EN uguali)
    assert label_it("Boh_sconosciuto") == "Boh sconosciuto"
    assert label_en("Boh_sconosciuto") == "Boh sconosciuto"
    # set custom senza etichette proprie: stesse risposte del default
    with bind(dataclasses.replace(default_set(), id="x", labels=None)):
        assert label_it("Bank") == "Banca"
        assert label_en("Bank") == "Bank"


def test_default_etichetta_it_vuota_ripiega_su_en(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = {
        "identifier": "Xyz",
        "label_en": "Xyz en",
        "label_it": "",
        "category": "",
    }
    monkeypatch.setattr(terminus_labels, "_records", lambda: {"Xyz": record})
    assert label_it("Xyz") == "Xyz en"


def test_default_estrazione_tag_invariata() -> None:
    tags = {"tourism": "attraction", "historic": "archaeological_site"}
    assert _extract_osm_tag(tags) == "historic=archaeological_site"


# --- binding OSM del set ---


def test_estrazione_tag_usa_ordine_e_cedevoli_del_set() -> None:
    tags = {"amenity": "bank", "shop": "kiosk"}
    assert _extract_osm_tag(tags) == "amenity=bank"  # default: amenity prima
    with bind(_custom()):
        assert _extract_osm_tag(tags) == "shop=kiosk"  # ordine del set: shop prima
        cedevole = {"tourism": "attraction", "historic": "ruins"}
        assert _extract_osm_tag(cedevole) == "historic=ruins"


def test_tag_non_nel_binding_del_set_non_si_estrae() -> None:
    with bind(_custom()):
        assert _extract_osm_tag({"amenity": "hospital"}) == ""


def test_classe_dei_poi_dal_binding_del_set() -> None:
    payload = {
        "elements": [
            {
                "type": "node",
                "id": 1,
                "lat": 41.9,
                "lon": 12.5,
                "tags": {"amenity": "bank", "name": "B"},
            }
        ]
    }
    with bind(_custom()):
        pois = _parse_elements(payload, "Roma")
    assert [p["terminus_class"] for p in pois] == ["Banca"]
    assert [p["terminus_class"] for p in _parse_elements(payload, "Roma")] == ["Bank"]


# --- etichette ---


def test_etichette_dal_set() -> None:
    with bind(_custom()):
        assert label_it("Banca") == "Istituto di credito"
        assert label_en("Banca") == "Bank"
        assert current_labels() is not None


def test_etichetta_it_vuota_ripiega_su_en() -> None:
    with bind(_custom()):
        assert label_it("Rovina") == "Ruin"


def test_classe_senza_etichetta_mostra_il_nome_con_gli_spazi() -> None:
    with bind(_custom()):
        assert label_it("Gas_station") == "Gas station"
        assert label_en("Gas_station") == "Gas station"
        assert label_it("Bank") == "Bank"  # non e' del set: niente JSON TERMINUS


def test_vocabolario_controllato_segue_il_set() -> None:
    with bind(_custom()):
        assert controlled_vocab_for(["Banca", "Gas_station"]) == [
            "Istituto di credito",
            "Gas station",
        ]


def test_set_custom_con_labels_none_usa_il_json() -> None:
    with bind(_custom(labels=None)):
        assert label_it("Bank") == "Banca"


# --- catalogo /poi-types ---


def test_catalogo_del_set_custom() -> None:
    with bind(_custom()):
        tipi = poi_types()
    assert {t.terminus_class for t in tipi} == {
        "Banca",
        "Gas_station",
        "Monumento",
        "Rovina",
    }
    assert PoiType(terminus_class="Banca", label_it="Istituto di credito") in tipi
    etichette = [t.label_it.casefold() for t in tipi]
    assert etichette == sorted(etichette)


def test_catalogo_di_set_diversi_non_si_mescola() -> None:
    altro = _custom(
        "c2",
        osm=OsmBinding(
            osm_to_class={"amenity=bank": "Bank2"},
            ordine_famiglie=("amenity",),
            selettori_cedevoli={},
        ),
        labels={"Bank2": ("Banca due", "Bank two")},
    )
    default_prima = poi_types()
    with bind(_custom("c1")):
        a = poi_types()
        assert resolve_poi_type("istituto di credito") == "Banca"
    with bind(altro):
        b = poi_types()
        with pytest.raises(UnknownPoiTypeError):
            resolve_poi_type("istituto di credito")
        assert resolve_poi_type("banca due") == "Bank2"
    assert {t.terminus_class for t in b} == {"Bank2"}
    assert a != b
    assert poi_types() == default_prima
    assert resolve_poi_type("stazione ferroviaria") == "Railway_station"
    with bind(_custom("c1")):
        with pytest.raises(UnknownPoiTypeError):
            resolve_poi_type("stazione ferroviaria")


def test_catalogo_custom_non_e_servito_dalla_cache_del_default() -> None:
    # Un set custom non e' mai servito dalla cache del default, anche se la cache
    # e' gia' piena.
    poi_types()
    with bind(_custom("default-lookalike")):
        assert {t.terminus_class for t in poi_types()} != set(OSM_TO_TERMINUS.values())


def _client(store: SessionStore) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(main_module.router)
    app.dependency_overrides[routes.get_sessions] = lambda: store
    return TestClient(app)


def test_endpoint_poi_types_con_set_custom_e_default() -> None:
    store = SessionStore(ttl_seconds=100, max_sessions=4)
    store.activate(SID, _custom(), [])
    client = _client(store)

    custom = cast(
        httpx.Response,
        client.get("/poi-types", headers={"X-Session-Id": SID}),  # pyright: ignore[reportUnknownMemberType]
    )
    default = cast(httpx.Response, client.get("/poi-types"))  # pyright: ignore[reportUnknownMemberType]

    assert custom.status_code == 200
    assert {t["terminus_class"] for t in custom.json()} == {
        "Banca",
        "Gas_station",
        "Monumento",
        "Rovina",
    }
    assert {t["terminus_class"] for t in default.json()} == set(
        OSM_TO_TERMINUS.values()
    )


def test_endpoint_poi_types_con_sessione_scaduta_410() -> None:
    t = [0.0]
    store = SessionStore(ttl_seconds=100, max_sessions=4, clock=lambda: t[0])
    store.activate(SID, _custom(), [])
    client = _client(store)
    t[0] = 101.0

    r = cast(
        httpx.Response,
        client.get("/poi-types", headers={"X-Session-Id": SID}),  # pyright: ignore[reportUnknownMemberType]
    )

    assert r.status_code == 410
    assert r.json()["detail"]["errore"] == "fonti_scadute"


# --- Overpass: selettori del set ---


@respx.mock
async def test_fetch_pois_senza_selettori_usa_quelli_del_set_attivo() -> None:
    route = respx.post(DEFAULT_OVERPASS_URL).mock(
        return_value=httpx.Response(200, json={"elements": []})
    )
    with bind(_custom()):
        await fetch_pois(Bbox(41.88, 12.48, 41.90, 12.50), "Roma")
    query = urllib.parse.unquote_plus(route.calls.last.request.content.decode())
    for selettore in ("amenity=bank", "shop=kiosk", "historic=ruins"):
        chiave, _, valore = selettore.partition("=")
        assert f'["{chiave}"="{valore}"]' in query
    assert '"hospital"' not in query  # selettore del default, non del set


# --- ambiguita' degli alias: rifiutata alla costruzione del set ---


def test_alias_ambigui_del_set_sono_un_errore_di_validazione() -> None:
    parsed = _parsed_con(
        {
            "Alfa": ("Comune", "Alpha"),
            "Beta": ("comune", "Beta en"),
            "Gamma": ("Alfa", ""),
        }
    )
    with pytest.raises(SourceValidationError) as exc:
        build_source_set(parsed)
    errori = exc.value.report.errors
    assert {p.code for p in errori} == {"alias_tipo_poi_ambiguo"}
    messaggi = " ".join(p.message for p in errori)
    for classe in ("Alfa", "Beta", "Gamma"):
        assert classe in messaggi


def test_alias_non_ambigui_del_set_si_costruiscono() -> None:
    ss = build_source_set(
        _parsed_con({"Alfa": ("Alfa", "A"), "Beta": ("Beta due", "B")})
    )
    assert ss.id != DEFAULT_ID
    assert ss.kind == "custom"
