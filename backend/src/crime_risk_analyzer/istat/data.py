"""ISTAT data of the package: cached loading and validation (#345, spec 4.1).

Two committed files, produced by hand by ``scripts/istat_refresh.py`` (D2: no
ISTAT API at runtime): ``delitti.json`` (reported offences and rates per place,
item and year) and ``luoghi.json`` (simplified polygons of provinces and
provincial capitals).

Loaded ONCE per process, like ``i18n/terminus_labels``: a data update requires a
restart. The outcome of a FAILED load is cached too, so a missing file does not
cost a disk read for every POI. Missing or invalid files make startup fail only
with the switch on (``main.lifespan``); with it off, grounding proceeds without
data.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from crime_risk_analyzer.models.geo import CityBoundary, boundary_from_geojson

__all__ = [
    "ITALY_CODE",
    "TOTAL_ITEM",
    "IstatData",
    "IstatDataError",
    "OffencesFile",
    "Place",
    "PlaceType",
    "YearValue",
    "clear_cache",
    "data_version",
    "istat_data",
    "istat_data_or_none",
    "load_data",
]

#: Folder of the data files (the package itself). Module variable read at every
#: load: tests replace it with a temporary folder.
_DATA_DIR = Path(__file__).parent
OFFENCES_FILE = "delitti.json"
PLACES_FILE = "luoghi.json"

#: Code of Italy in the dataset (national rate).
ITALY_CODE = "IT"
#: Item for the total of offences: only the frame of the place, never the weight of
#: a risk (D10).
TOTAL_ITEM = "TOT"

PlaceType = Literal["comune", "provincia"]


class IstatDataError(Exception):
    """The ISTAT data files are missing or invalid."""


class YearValue(BaseModel):
    """Values of a place for an item in a year."""

    model_config = ConfigDict(frozen=True)

    delitti: int
    #: ``None`` if ISTAT does not publish it; together with ``tasso_sotto_soglia``
    #: the reason is the "below half of the minimum figure" flag ("less than 0.1").
    tasso: float | None
    tasso_sotto_soglia: bool = False


class OffencesFile(BaseModel):
    """Content of ``delitti.json``."""

    model_config = ConfigDict(frozen=True)

    dataset: str
    titolo: str
    url: str
    estratto_il: str
    licenza: str
    anno: int
    anno_confronto: int
    voci: dict[str, str]
    valori: dict[str, dict[str, dict[str, YearValue | None]]]

    def valore(self, luogo: str, voce: str, anno: int) -> YearValue | None:
        """Values of ``luogo``/``voce`` in ``anno``; ``None`` if missing."""
        return self.valori.get(luogo, {}).get(voce, {}).get(str(anno))


class _PlaceRecord(BaseModel):
    codice: str
    tipo: PlaceType
    nome: str
    nome_breve: str
    provincia: str | None = None
    bbox: tuple[float, float, float, float]
    punto_interno: tuple[float, float]
    geometria: dict[str, object]


class _PlacesFile(BaseModel):
    fonte: str
    url: list[str]
    licenza: str
    generato_il: str
    luoghi: list[_PlaceRecord]


@dataclass(frozen=True)
class Place:
    """Provincial capital or province of the dataset, with its boundary.

    ``nome`` is the citation form ("Comune di Roma"), ``nome_breve`` the one the
    narrative writes in prose ("Roma"). ``bbox`` and ``punto_interno`` are in
    ``(lon, lat)``.
    """

    codice: str
    tipo: PlaceType
    nome: str
    nome_breve: str
    provincia: str | None
    bbox: tuple[float, float, float, float]
    punto_interno: tuple[float, float]
    confine: CityBoundary


@dataclass(frozen=True)
class IstatData:
    """Loaded data: values and places (sorted by type and code)."""

    delitti: OffencesFile
    luoghi: tuple[Place, ...]

    @property
    def versione(self) -> str:
        """Extraction date: identifies the copy of the data used by a response."""
        return self.delitti.estratto_il


def load_data(directory: Path | None = None) -> IstatData:
    """Read and validate the two files; raise :class:`IstatDataError` on failure."""
    base = _DATA_DIR if directory is None else directory
    try:
        offences = OffencesFile.model_validate_json(
            (base / OFFENCES_FILE).read_text(encoding="utf-8")
        )
        places_file = _PlacesFile.model_validate_json(
            (base / PLACES_FILE).read_text(encoding="utf-8")
        )
        places = tuple(
            Place(
                codice=r.codice,
                tipo=r.tipo,
                nome=r.nome,
                nome_breve=r.nome_breve,
                provincia=r.provincia,
                bbox=r.bbox,
                punto_interno=r.punto_interno,
                confine=boundary_from_geojson(r.geometria),
            )
            for r in sorted(places_file.luoghi, key=lambda r: (r.tipo, r.codice))
        )
    except (OSError, ValueError) as exc:
        raise IstatDataError(f"dati ISTAT non caricabili da {base}: {exc}") from exc
    if ITALY_CODE not in offences.valori:
        raise IstatDataError("delitti.json non contiene la riga Italia")
    codes = {place.codice for place in places}
    without_polygon = sorted(set(offences.valori) - {ITALY_CODE} - codes)
    if without_polygon:
        raise IstatDataError(f"luoghi senza poligono: {without_polygon}")
    return IstatData(delitti=offences, luoghi=places)


@lru_cache(maxsize=1)
def _outcome() -> IstatData | IstatDataError:
    try:
        return load_data()
    except IstatDataError as exc:
        return exc


def istat_data() -> IstatData:
    """Cached data; raises if unavailable (startup with the switch on)."""
    outcome = _outcome()
    if isinstance(outcome, IstatDataError):
        raise outcome
    return outcome


def istat_data_or_none() -> IstatData | None:
    """Cached data or ``None``: grounding must not fail without data."""
    outcome = _outcome()
    return None if isinstance(outcome, IstatDataError) else outcome


def data_version() -> str | None:
    """Version of the data in use, ``None`` if unavailable."""
    data = istat_data_or_none()
    return data.versione if data is not None else None


def clear_cache() -> None:
    """Forget the outcome of the load (tests)."""
    _outcome.cache_clear()
