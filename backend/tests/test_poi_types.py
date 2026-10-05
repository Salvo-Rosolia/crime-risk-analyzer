"""Test del catalogo dei tipi POI e della normalizzazione di ``tipo_poi`` (#143).

Il catalogo sono le classi TERMINUS che il mapping OSM puo' davvero produrre (i
valori distinti di ``OSM_TO_TERMINUS``), con l'etichetta IT del vocabolario #77.
Nessuna rete: tutto deriva da dati statici del package.
"""

from __future__ import annotations

from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from crime_risk_analyzer import poi_types as poi_types_module
from crime_risk_analyzer.i18n import terminus_labels
from crime_risk_analyzer.i18n.terminus_labels import label_it
from crime_risk_analyzer.main import create_app
from crime_risk_analyzer.orchestrator import BaselineRequest
from crime_risk_analyzer.poi_types import (
    PoiType,
    UnknownPoiTypeError,
    poi_types,
    resolve_poi_type,
)
from crime_risk_analyzer.sparql_module.osm_mapping import (
    GENERIC_FALLBACK,
    OSM_TO_TERMINUS,
)

# --- catalogo ---


def test_catalog_is_exactly_the_distinct_mapped_classes() -> None:
    classes = [t.terminus_class for t in poi_types()]
    assert len(classes) == len(set(classes))
    assert set(classes) == set(OSM_TO_TERMINUS.values())
    # Il fallback dei tag non coperti non e' un tipo selezionabile.
    assert GENERIC_FALLBACK not in classes


def test_catalog_labels_come_from_controlled_vocabulary() -> None:
    for t in poi_types():
        assert t.label_it == label_it(t.terminus_class)
        assert t.label_it


def test_catalog_is_sorted_by_label_casefold() -> None:
    keys = [(t.label_it.casefold(), t.terminus_class) for t in poi_types()]
    assert keys == sorted(keys)


def test_catalog_contains_bank_with_italian_label() -> None:
    assert PoiType(terminus_class="Bank", label_it="Banca") in poi_types()


# --- normalizzazione ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Bank", "Bank"),
        ("bank", "Bank"),
        ("BANK", "Bank"),
        ("  bank  ", "Bank"),
        ("Banca", "Bank"),
        ("banca", "Bank"),
        ("railway_station", "Railway_station"),
        ("Railway station", "Railway_station"),
        ("stazione  ferroviaria", "Railway_station"),
        ("national_police", "National_police"),
        ("polizia di stato", "National_police"),
    ],
)
def test_resolve_poi_type_normalizes_to_canonical(raw: str, expected: str) -> None:
    assert resolve_poi_type(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "\t\n"])
def test_resolve_poi_type_blank_is_no_filter(raw: str | None) -> None:
    assert resolve_poi_type(raw) is None


@pytest.mark.parametrize("raw", ["xyz", "GenericUrbanPOI", "bar", "Bank_robbery"])
def test_resolve_poi_type_unknown_raises(raw: str) -> None:
    with pytest.raises(UnknownPoiTypeError) as exc_info:
        resolve_poi_type(raw)
    assert str(exc_info.value) == f"Tipo POI non riconosciuto: {raw!r}"


def test_resolve_poi_type_error_message_shows_stripped_input() -> None:
    with pytest.raises(UnknownPoiTypeError) as exc_info:
        resolve_poi_type("  xyz ")
    assert str(exc_info.value) == "Tipo POI non riconosciuto: 'xyz'"


def test_every_catalog_entry_resolves_by_class_and_by_label() -> None:
    """Nessuna collisione: ogni nome e ogni etichetta portano alla propria classe."""
    for t in poi_types():
        assert resolve_poi_type(t.terminus_class) == t.terminus_class
        assert resolve_poi_type(t.label_it) == t.terminus_class


# --- endpoint ---


def test_get_poi_types_endpoint_shape_and_order() -> None:
    client = TestClient(create_app())
    resp = cast(httpx.Response, client.get("/poi-types"))  # pyright: ignore[reportUnknownMemberType]
    assert resp.status_code == 200
    body = cast(list[dict[str, str]], resp.json())
    assert all(set(item) == {"terminus_class", "label_it"} for item in body)
    assert body == [t.model_dump() for t in poi_types()]
    assert {"terminus_class": "Bank", "label_it": "Banca"} in body


# --- BaselineRequest: forma del campo ---

_CIRCLE: dict[str, object] = {
    "center": {"lat": 41.89, "lon": 12.49},
    "radius_m": 2000.0,
}


def test_baseline_request_strips_tipo_poi_and_blank_is_none() -> None:
    assert (
        BaselineRequest.model_validate({**_CIRCLE, "tipo_poi": "  bank "}).tipo_poi
        == "bank"
    )
    # Strip prima del tetto: soli spazi oltre max_length restano "assente".
    assert (
        BaselineRequest.model_validate({**_CIRCLE, "tipo_poi": " " * 300}).tipo_poi
        is None
    )


def test_baseline_request_rejects_overlong_tipo_poi() -> None:
    with pytest.raises(ValidationError):
        BaselineRequest.model_validate({**_CIRCLE, "tipo_poi": "x" * 101})


# --- review #143: immutabilita', fail-fast, vocabolario, apostrofi ---


def test_poi_type_is_frozen() -> None:
    """Le voci vivono nella cache di ``poi_types()``: nessuno deve poterle mutare."""
    entry = poi_types()[0]
    with pytest.raises(ValidationError):
        entry.label_it = "manomesso"  # pyright: ignore[reportAttributeAccessIssue]


def test_every_entry_has_a_real_italian_label() -> None:
    """Ogni voce ha una ``label_it`` vera nel vocabolario #77, non il fallback
    EN/nome: e' quanto afferma il docstring di :mod:`poi_types`."""
    records = terminus_labels._records()  # pyright: ignore[reportPrivateUsage]
    for t in poi_types():
        rec = records.get(t.terminus_class)
        assert rec is not None, t.terminus_class
        assert rec["label_it"], t.terminus_class
        assert t.label_it == rec["label_it"]


def test_lookup_fails_fast_on_alias_shared_by_two_classes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clash = (
        PoiType(terminus_class="Alpha", label_it="Comune"),
        PoiType(terminus_class="Beta", label_it="comune"),
    )
    monkeypatch.setattr(poi_types_module, "poi_types", lambda: clash)
    with pytest.raises(RuntimeError, match="ambiguo"):
        poi_types_module._lookup.__wrapped__()  # pyright: ignore[reportPrivateUsage]


def test_lookup_accepts_label_equal_to_its_own_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    same = (PoiType(terminus_class="Cinema", label_it="Cinema"),)
    monkeypatch.setattr(poi_types_module, "poi_types", lambda: same)
    table = poi_types_module._lookup.__wrapped__()  # pyright: ignore[reportPrivateUsage]
    assert table == {"cinema": "Cinema"}


@pytest.mark.parametrize("apostrophe", [0x2019, 0x2018, 0x02BC, 0x0060, 0x00B4])
def test_resolve_poi_type_normalizes_apostrophes(apostrophe: int) -> None:
    assert resolve_poi_type(f"Scuola dell{chr(apostrophe)}infanzia") == "Kindergarten"
    assert resolve_poi_type("scuola dell'infanzia") == "Kindergarten"
