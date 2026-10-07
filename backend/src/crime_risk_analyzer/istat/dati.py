"""Dati ISTAT del package: caricamento con cache e validazione (#345, spec 4.1).

Due file committati, prodotti a mano da ``scripts/istat_refresh.py`` (D2: niente
API ISTAT a runtime): ``delitti.json`` (delitti denunciati e tassi per luogo, voce
e anno) e ``luoghi.json`` (poligoni semplificati di province e comuni capoluogo).

Caricati UNA volta per processo, come ``i18n/terminus_labels``: un aggiornamento
dei dati richiede il riavvio. In cache c'e' anche l'esito di un caricamento
FALLITO, cosi' un file mancante non costa una lettura del disco per ogni POI.
File mancanti o non validi fanno fallire l'avvio solo con l'interruttore acceso
(``main.lifespan``); spento, il grounding prosegue senza dati.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from crime_risk_analyzer.models.geo import CityBoundary, boundary_from_geojson

__all__ = [
    "CODICE_ITALIA",
    "VOCE_TOTALE",
    "DatiIstat",
    "FileDelitti",
    "IstatDatiError",
    "Luogo",
    "TipoLuogo",
    "ValoreAnno",
    "carica_dati",
    "dati_istat",
    "dati_istat_o_none",
    "svuota_cache",
    "versione_dati",
]

#: Cartella dei file dati (il package stesso). Variabile di modulo letta a ogni
#: caricamento: i test la sostituiscono con una cartella temporanea.
_CARTELLA = Path(__file__).parent
FILE_DELITTI = "delitti.json"
FILE_LUOGHI = "luoghi.json"

#: Codice dell'Italia nel dataset (tasso nazionale).
CODICE_ITALIA = "IT"
#: Voce del totale dei delitti: solo cornice del luogo, mai peso di un rischio (D10).
VOCE_TOTALE = "TOT"

TipoLuogo = Literal["comune", "provincia"]


class IstatDatiError(Exception):
    """I file dei dati ISTAT mancano o non sono validi."""


class ValoreAnno(BaseModel):
    """Valori di un luogo per una voce in un anno."""

    model_config = ConfigDict(frozen=True)

    delitti: int
    #: ``None`` se ISTAT non lo pubblica; con ``tasso_sotto_soglia`` il motivo e'
    #: il flag "sotto la meta' della cifra minima" ("meno di 0,1").
    tasso: float | None
    tasso_sotto_soglia: bool = False


class FileDelitti(BaseModel):
    """Contenuto di ``delitti.json``."""

    model_config = ConfigDict(frozen=True)

    dataset: str
    titolo: str
    url: str
    estratto_il: str
    licenza: str
    anno: int
    anno_confronto: int
    voci: dict[str, str]
    valori: dict[str, dict[str, dict[str, ValoreAnno | None]]]

    def valore(self, luogo: str, voce: str, anno: int) -> ValoreAnno | None:
        """Valori di ``luogo``/``voce`` nell'``anno``; ``None`` se mancano."""
        return self.valori.get(luogo, {}).get(voce, {}).get(str(anno))


class _LuogoRecord(BaseModel):
    codice: str
    tipo: TipoLuogo
    nome: str
    nome_breve: str
    provincia: str | None = None
    bbox: tuple[float, float, float, float]
    punto_interno: tuple[float, float]
    geometria: dict[str, object]


class _FileLuoghi(BaseModel):
    fonte: str
    url: list[str]
    licenza: str
    generato_il: str
    luoghi: list[_LuogoRecord]


@dataclass(frozen=True)
class Luogo:
    """Comune capoluogo o provincia del dataset, col suo confine.

    ``nome`` e' la forma della citazione ("Comune di Roma"), ``nome_breve`` quella
    che la narrativa scrive in prosa ("Roma"). ``bbox`` e ``punto_interno`` sono
    in ``(lon, lat)``.
    """

    codice: str
    tipo: TipoLuogo
    nome: str
    nome_breve: str
    provincia: str | None
    bbox: tuple[float, float, float, float]
    punto_interno: tuple[float, float]
    confine: CityBoundary


@dataclass(frozen=True)
class DatiIstat:
    """Dati caricati: valori e luoghi (ordinati per tipo e codice)."""

    delitti: FileDelitti
    luoghi: tuple[Luogo, ...]

    @property
    def versione(self) -> str:
        """Data di estrazione: identifica la copia dei dati usata da una risposta."""
        return self.delitti.estratto_il


def carica_dati(cartella: Path | None = None) -> DatiIstat:
    """Legge e valida i due file; solleva :class:`IstatDatiError` se non si puo'."""
    base = _CARTELLA if cartella is None else cartella
    try:
        delitti = FileDelitti.model_validate_json(
            (base / FILE_DELITTI).read_text(encoding="utf-8")
        )
        file_luoghi = _FileLuoghi.model_validate_json(
            (base / FILE_LUOGHI).read_text(encoding="utf-8")
        )
        luoghi = tuple(
            Luogo(
                codice=r.codice,
                tipo=r.tipo,
                nome=r.nome,
                nome_breve=r.nome_breve,
                provincia=r.provincia,
                bbox=r.bbox,
                punto_interno=r.punto_interno,
                confine=boundary_from_geojson(r.geometria),
            )
            for r in sorted(file_luoghi.luoghi, key=lambda r: (r.tipo, r.codice))
        )
    except (OSError, ValueError) as exc:
        raise IstatDatiError(f"dati ISTAT non caricabili da {base}: {exc}") from exc
    if CODICE_ITALIA not in delitti.valori:
        raise IstatDatiError("delitti.json non contiene la riga Italia")
    codici = {luogo.codice for luogo in luoghi}
    senza_poligono = sorted(set(delitti.valori) - {CODICE_ITALIA} - codici)
    if senza_poligono:
        raise IstatDatiError(f"luoghi senza poligono: {senza_poligono}")
    return DatiIstat(delitti=delitti, luoghi=luoghi)


@lru_cache(maxsize=1)
def _esito() -> DatiIstat | IstatDatiError:
    try:
        return carica_dati()
    except IstatDatiError as exc:
        return exc


def dati_istat() -> DatiIstat:
    """Dati in cache; solleva se non disponibili (avvio con interruttore acceso)."""
    esito = _esito()
    if isinstance(esito, IstatDatiError):
        raise esito
    return esito


def dati_istat_o_none() -> DatiIstat | None:
    """Dati in cache o ``None``: il grounding non deve fallire senza dati."""
    esito = _esito()
    return None if isinstance(esito, IstatDatiError) else esito


def versione_dati() -> str | None:
    """Versione dei dati in uso, ``None`` se non disponibili."""
    dati = dati_istat_o_none()
    return dati.versione if dati is not None else None


def svuota_cache() -> None:
    """Dimentica l'esito del caricamento (test)."""
    _esito.cache_clear()
