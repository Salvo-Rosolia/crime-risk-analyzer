"""Metriche ISTAT della narrativa (#345, spec 4.9), dall'esito del controllo.

Versione 2 (#365): i dati ISTAT si usano a parole nel blocco [ONTOLOGIA], senza
cifre. Le "frasi ISTAT" sono quelle di qualunque blocco che parlano del dato
(:attr:`~crime_risk_analyzer.istat.cifre.FraseControllata.parla_di_istat`); i
campi che cambiano significato sono elencati in
:class:`~crime_risk_analyzer.eval.schema.IstatMetrics`. Versione 4 (#369): conta
anche le frasi ISTAT escluse da M1; da #378 quante di queste non nominano una
voce delle righe del prompt (campo nuovo, ``None`` sui record di prima: la
versione non cambia).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from crime_risk_analyzer.eval.schema import IstatMetrics
from crime_risk_analyzer.istat.cifre import EsitoControllo, nomina_voce_delle_righe
from crime_risk_analyzer.istat.dati import VOCE_TOTALE

__all__ = [
    "ISTAT_METRICS_VERSION",
    "compute_istat_metrics",
    "frasi_escluse_senza_voce",
    "somma_istat_metrics",
]

#: Versione delle metriche ISTAT scritte da :func:`compute_istat_metrics`. 1 =
#: #345 (cifre nel blocco [ISTAT]), 2 = #365 (dati a parole, senza cifre), 3 =
#: #368 (M1 non misura le frasi ISTAT: stessi conteggi, altro testo gradato), 4 =
#: #369 (M1 esclude solo le frasi ISTAT senza POI ne' rischio, contate in
#: ``frasi_escluse_m1``).
ISTAT_METRICS_VERSION = 4

#: Euristica: la frase dice che la voce non coincide col rischio.
_DICHIARAZIONE = re.compile(
    r"non coincid|ampia del rischio|pi(?:ù|u'?) ampi|pi(?:ù|u'?) ristrett"
    r"|solo (?:in )?parte|solo una parte|parzial|comprende anche"
)

_CONTEGGI = (
    "cifre_totali",
    "cifre_istat",
    "frasi_scartabili",
    "voci_fornite",
    "voci_citate",
    "frasi_istat",
    "frasi_istat_con_luogo",
    "frasi_istat_con_luogo_ereditato",
    "direzioni_totali",
    "direzioni_coerenti",
    "confronti_totali",
    "confronti_coerenti",
    "corrispondenze_non_dichiarate",
    "numeri_in_lettere",
    "codici_voce",
    "frasi_escluse_m1",
)


def frasi_escluse_senza_voce(
    escluse: Sequence[str], esito: EsitoControllo
) -> list[str]:
    """Frasi escluse da M1 che non nominano nessuna voce delle righe ISTAT del
    prompt ne' un rischio collegato (#378), nell'ordine delle escluse.

    Sono candidate da leggere a mano, non un verdetto: un rischio fuori dalla
    base di conoscenza scritto con le parole del dato ISTAT ("secondo i dati
    ISTAT ... sequestri di persona") finisce qui, ma anche una frase sul dato in
    generale o con un sinonimo della voce. Una frase che nomina una voce delle
    righe e anche un rischio inventato non c'e'. Il riconoscimento della voce e'
    quello di :func:`~crime_risk_analyzer.istat.cifre.nomina_voce_delle_righe`
    (leggermente piu' largo del controllo sul totale "delitti denunciati").
    """
    return [f for f in escluse if not nomina_voce_delle_righe(f, esito.righe)]


def compute_istat_metrics(
    esito: EsitoControllo,
    *,
    frasi_escluse_m1: int,
    frasi_escluse_senza_voce: int | None = None,
) -> IstatMetrics:
    """Metriche deterministiche sul testo grezzo esaminato dal controllo.

    ``frasi_escluse_m1`` (#369) arriva da fuori: quali frasi ISTAT M1 esclude
    dipende dai POI e dai rischi della risposta, che il controllo non conosce
    (:func:`~crime_risk_analyzer.eval.metrics.frasi_escluse_m1`). Cosi' anche
    ``frasi_escluse_senza_voce`` (#378, :func:`frasi_escluse_senza_voce`).
    """
    frasi = esito.frasi
    fornite = {r.voce for r in esito.righe if r.voce != VOCE_TOTALE}
    frasi_istat = [f for f in frasi if f.parla_di_istat]
    # Una voce e' citata se una frase ISTAT che il filtro TIENE la nomina.
    citate = {v for f in frasi_istat if f.motivo is None for v in f.voci} & fornite
    non_esatte = {
        r.voce
        for r in esito.righe
        if any(c.corrispondenza != "esatta" for c in r.collegamenti)
    }
    direzioni = [f for f in frasi if f.direzione_coerente is not None]
    confronti = [f for f in frasi if f.confronto_coerente is not None]
    return IstatMetrics(
        versione=ISTAT_METRICS_VERSION,
        cifre_totali=sum(f.cifre for f in frasi),
        cifre_istat=sum(f.cifre_istat for f in frasi),
        frasi_scartabili=esito.frasi_scartate,
        voci_fornite=len(fornite),
        voci_citate=len(citate),
        frasi_istat=len(frasi_istat),
        frasi_istat_con_luogo=sum(1 for f in frasi_istat if f.luogo),
        frasi_istat_con_luogo_ereditato=sum(
            1 for f in frasi_istat if f.luogo_ereditato
        ),
        direzioni_totali=len(direzioni),
        direzioni_coerenti=sum(1 for f in direzioni if f.direzione_coerente),
        confronti_totali=len(confronti),
        confronti_coerenti=sum(1 for f in confronti if f.confronto_coerente),
        corrispondenze_non_dichiarate=sum(
            1
            for f in frasi_istat
            if set(f.voci) & non_esatte and not _DICHIARAZIONE.search(f.testo.lower())
        ),
        numeri_in_lettere=esito.numeri_in_lettere,
        codici_voce=esito.codici_voce,
        frasi_escluse_m1=frasi_escluse_m1,
        frasi_escluse_senza_voce=frasi_escluse_senza_voce,
    )


def somma_istat_metrics(metriche: Iterable[IstatMetrics | None]) -> IstatMetrics | None:
    """Somma dei conteggi fra le ripetizioni (tutte della stessa versione).

    ``frasi_escluse_senza_voce`` (#378) e' ``None`` se manca in una ripetizione.
    """
    presenti = [m for m in metriche if m is not None]
    if not presenti:
        return None
    versioni = {m.versione for m in presenti}
    if len(versioni) != 1:
        raise ValueError(
            f"metriche ISTAT di versioni diverse {sorted(versioni)}: non si sommano"
        )
    somme: dict[str, int] = {
        nome: sum(int(getattr(m, nome)) for m in presenti) for nome in _CONTEGGI
    }
    senza_voce = [m.frasi_escluse_senza_voce for m in presenti]
    return IstatMetrics(
        versione=versioni.pop(),
        frasi_escluse_senza_voce=(
            None
            if any(n is None for n in senza_voce)
            else sum(n for n in senza_voce if n is not None)
        ),
        **somme,
    )
