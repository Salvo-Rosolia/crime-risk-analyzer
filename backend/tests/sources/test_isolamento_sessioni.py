"""Cache di zona e impronta non mescolano sessioni diverse (#416)."""

import dataclasses
from typing import Any, cast

from crime_risk_analyzer import zone_context_cache as cache
from crime_risk_analyzer.context_fingerprint import fingerprint, fonti_attive_id
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.sources.context import bind, current_id, default_set
from crime_risk_analyzer.sources.model import SourceSet
from crime_risk_analyzer.zone_context_cache import ZoneContext


def _altro(id_: str) -> SourceSet:
    return dataclasses.replace(default_set(), id=id_, kind="custom")


def _ctx(marca: str) -> ZoneContext:
    return ZoneContext(
        retrieval=cast(Any, {"citta": "Roma", "zona": marca, "pois": []}),
        grounded=cast(Any, {"zona": marca, "validated_risks": []}),
    )


def _pois() -> list[Poi]:
    poi = cast(
        Poi,
        {"id": "node/1", "name": "A", "terminus_class": "Bank", "lat": 1.0, "lon": 2.0},
    )
    return [poi]


def setup_function() -> None:
    cache.clear()


def test_current_id_default_senza_costruire_il_default() -> None:
    assert current_id() == "default"
    with bind(_altro("x")):
        assert current_id() == "x"


def test_cache_di_sessioni_diverse_non_si_mescola() -> None:
    with bind(_altro("a")):
        cache.put("Roma", "Monti", _ctx("a"), now=0.0)
    with bind(_altro("b")):
        assert cache.get("Roma", "Monti", now=1.0) is None
        cache.put("Roma", "Monti", _ctx("b"), now=0.0)
    with bind(_altro("a")):
        hit = cache.get("Roma", "Monti", now=1.0)
        assert hit is not None and hit["grounded"]["zona"] == "a"
    assert cache.get("Roma", "Monti", now=1.0) is None  # il default non vede nulla


def test_la_cache_del_default_resta_visibile_senza_sessione() -> None:
    cache.put("Roma", "Monti", _ctx("d"), now=0.0)
    assert cache.get("Roma", "Monti", now=1.0) is not None
    with bind(_altro("a")):
        assert cache.get("Roma", "Monti", now=1.0) is None


def test_purge_toglie_solo_le_voci_del_set() -> None:
    with bind(_altro("a")):
        cache.put("Roma", "Monti", _ctx("a"), now=0.0)
    with bind(_altro("b")):
        cache.put("Roma", "Monti", _ctx("b"), now=0.0)
    cache.purge("a")
    with bind(_altro("a")):
        assert cache.get("Roma", "Monti", now=1.0) is None
    with bind(_altro("b")):
        assert cache.get("Roma", "Monti", now=1.0) is not None


def test_fonti_attive_id_none_per_il_default() -> None:
    assert fonti_attive_id() is None
    with bind(_altro("a")):
        assert fonti_attive_id() == "a"


def test_impronta_senza_fonti_e_identica_a_prima() -> None:
    assert fingerprint(_pois()) == fingerprint(_pois(), fonti=None)


def test_impronta_dipende_dal_set() -> None:
    base = fingerprint(_pois())
    a = fingerprint(_pois(), fonti="a")
    b = fingerprint(_pois(), fonti="b")
    assert len({base, a, b}) == 3


def test_impronta_con_istat_e_fonti_non_collide() -> None:
    assert fingerprint(_pois(), istat_versione="v1", fonti="a") != fingerprint(
        _pois(), istat_versione="v1"
    )
    assert fingerprint(_pois(), istat_versione="v1", fonti="a") != fingerprint(
        _pois(), istat_versione="v1", fonti="b"
    )
