"""Blocco DATI ISTAT dello user_content (#345, spec 4.4-4.5).

Zona: prima le cornici (una per luogo con almeno una voce), poi le voci, una sola
volta per (luogo, voce), ordinate per POI coinvolti decrescenti (a parita': codice
della voce, poi del luogo). Se il blocco non sta nel limite si tolgono voci
partendo da quelle con MENO POI coinvolti; le cornici restano per ultime (cadono
con l'ultima voce del loro luogo) e una nota dice quante voci sono rimaste fuori.

POI: cornice e voci di quel punto, senza "POI coinvolti".

La stima dei token arriva dal chiamante (``generation._estimate_tokens``): questo
modulo non importa ``rag`` per non creare cicli.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

from crime_risk_analyzer.istat.righe import IstatPoi, RigaIstat, formatta_riga

__all__ = [
    "INTESTAZIONE_DATI_ISTAT",
    "BloccoIstat",
    "blocco_istat_poi",
    "blocco_istat_zona",
    "ha_righe_istat",
    "nota_taglio",
]

#: Prima riga del blocco: dice al modello che cosa sono i dati e di chi sono.
INTESTAZIONE_DATI_ISTAT = (
    "DATI ISTAT (delitti denunciati dalle forze di polizia all'autorita' "
    "giudiziaria; dati del comune capoluogo o della provincia indicati tra "
    "parentesi quadre, non della zona ne' dei singoli POI):"
)


class BloccoIstat(BaseModel):
    """Testo del blocco e righe effettivamente rese (servono al controllo cifre)."""

    model_config = ConfigDict(frozen=True)

    testo: str = ""
    righe: tuple[RigaIstat, ...] = ()
    voci_tagliate: int = 0


def nota_taglio(n: int) -> str:
    """Riga di trasparenza quando ``n`` voci restano fuori per budget."""
    if n == 1:
        return "NB: per limiti di lunghezza 1 voce ISTAT non e' riportata."
    return f"NB: per limiti di lunghezza {n} voci ISTAT non sono riportate."


def _istat(poi: Mapping[str, Any]) -> IstatPoi | None:
    valore = poi.get("istat")
    return valore if isinstance(valore, IstatPoi) and valore.righe else None


def ha_righe_istat(pois: Sequence[Mapping[str, Any]]) -> bool:
    """True se almeno un POI porta righe ISTAT."""
    return any(_istat(poi) is not None for poi in pois)


def _aggrega(
    pois: Sequence[Mapping[str, Any]],
) -> tuple[list[RigaIstat], list[tuple[RigaIstat, int]]]:
    cornici: dict[str, RigaIstat] = {}
    voci: dict[tuple[str, str], RigaIstat] = {}
    coinvolti: dict[tuple[str, str], set[str]] = {}
    for poi in pois:
        istat = _istat(poi)
        if istat is None:
            continue
        cornici.setdefault(istat.cornice.luogo_codice, istat.cornice)
        for riga in istat.righe:
            chiave = (riga.luogo_codice, riga.voce)
            esistente = voci.get(chiave)
            if esistente is None:
                voci[chiave] = riga
            else:
                gia = {c.hazard for c in esistente.collegamenti}
                nuovi = tuple(c for c in riga.collegamenti if c.hazard not in gia)
                voci[chiave] = esistente.model_copy(
                    update={"collegamenti": esistente.collegamenti + nuovi}
                )
            coinvolti.setdefault(chiave, set()).add(str(poi.get("poi_id", "")))
    ordine = sorted(voci, key=lambda k: (-len(coinvolti[k]), k[1], k[0]))
    return list(cornici.values()), [(voci[k], len(coinvolti[k])) for k in ordine]


def _rendi(
    cornici: list[RigaIstat], voci: list[tuple[RigaIstat, int]], tagliate: int
) -> tuple[str, tuple[RigaIstat, ...]]:
    luoghi = {riga.luogo_codice for riga, _ in voci}
    cornici_rese = [c for c in cornici if c.luogo_codice in luoghi]
    linee = [INTESTAZIONE_DATI_ISTAT]
    linee.extend(formatta_riga(c) for c in cornici_rese)
    linee.extend(formatta_riga(riga, poi_coinvolti=n) for riga, n in voci)
    if tagliate:
        linee.append(nota_taglio(tagliate))
    return "\n".join(linee), (*cornici_rese, *(riga for riga, _ in voci))


def blocco_istat_zona(
    pois: Sequence[Mapping[str, Any]],
    *,
    stima_token: Callable[[str], int],
    limite_token: int | None,
) -> BloccoIstat:
    """Blocco di zona sui ``pois`` (gia' quelli inclusi nel prompt)."""
    cornici, voci = _aggrega(pois)
    totale = len(voci)
    while voci:
        testo, righe = _rendi(cornici, voci, totale - len(voci))
        if limite_token is None or stima_token(testo) <= limite_token:
            return BloccoIstat(
                testo=testo, righe=righe, voci_tagliate=totale - len(voci)
            )
        voci = voci[:-1]
    return BloccoIstat(voci_tagliate=totale)


def blocco_istat_poi(istat: IstatPoi | None) -> BloccoIstat:
    """Blocco del singolo POI: cornice e voci, senza conteggio di POI."""
    if istat is None or not istat.righe:
        return BloccoIstat()
    righe = (istat.cornice, *istat.righe)
    testo = "\n".join([INTESTAZIONE_DATI_ISTAT, *(formatta_riga(r) for r in righe)])
    return BloccoIstat(testo=testo, righe=righe)
