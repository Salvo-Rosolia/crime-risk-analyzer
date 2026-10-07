"""Luogo ISTAT di un punto (#345, spec 4.3 / D5).

Prima i comuni capoluogo, poi le province: il dato del comune e' il piu' vicino al
POI che ISTAT pubblica. Filtro sul riquadro prima del ray casting (214 luoghi).
Fuori da ogni poligono (mare, estero, buchi della semplificazione) -> ``None``.
L'ordine dei luoghi e' quello del caricamento (tipo, codice): fra due poligoni
sovrapposti dello stesso tipo vince il codice minore, sempre lo stesso.
"""

from __future__ import annotations

from crime_risk_analyzer.istat.dati import (
    DatiIstat,
    Luogo,
    TipoLuogo,
    dati_istat_o_none,
)
from crime_risk_analyzer.models.geo import point_in_multipolygon

__all__ = ["luogo_di"]

_PRIORITA: tuple[TipoLuogo, ...] = ("comune", "provincia")


def _nel_riquadro(luogo: Luogo, lat: float, lon: float) -> bool:
    min_lon, min_lat, max_lon, max_lat = luogo.bbox
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


def luogo_di(lat: float, lon: float, *, dati: DatiIstat | None = None) -> Luogo | None:
    """Comune capoluogo o provincia che contiene ``(lat, lon)``, o ``None``."""
    sorgente = dati if dati is not None else dati_istat_o_none()
    if sorgente is None:
        return None
    for tipo in _PRIORITA:
        for luogo in sorgente.luoghi:
            if (
                luogo.tipo == tipo
                and _nel_riquadro(luogo, lat, lon)
                and point_in_multipolygon((lon, lat), luogo.confine)
            ):
                return luogo
    return None
