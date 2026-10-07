"""Metriche ISTAT della narrativa (#345, spec 4.9), dall'esito del controllo cifre."""

from __future__ import annotations

import re
from collections.abc import Iterable

from crime_risk_analyzer.eval.schema import IstatMetrics
from crime_risk_analyzer.istat.cifre import EsitoControllo
from crime_risk_analyzer.istat.dati import VOCE_TOTALE

__all__ = ["compute_istat_metrics", "somma_istat_metrics"]

#: Euristica: la frase dice che la voce non coincide col rischio.
_DICHIARAZIONE = re.compile(
    r"non coincid|ampia del rischio|pi(?:ù|u'?) ampi|pi(?:ù|u'?) ristrett"
    r"|solo (?:in )?parte|solo una parte|parzial|comprende anche"
)

_CONTEGGI = (
    "cifre_totali",
    "cifre_istat_corrette",
    "frasi_scartabili",
    "voci_fornite",
    "voci_citate",
    "frasi_istat",
    "frasi_istat_con_luogo",
    "direzioni_totali",
    "direzioni_coerenti",
    "corrispondenze_non_dichiarate",
    "numeri_in_lettere",
)


def compute_istat_metrics(esito: EsitoControllo) -> IstatMetrics:
    """Metriche deterministiche sul testo grezzo esaminato dal controllo."""
    frasi = esito.frasi
    cifre = sum(f.cifre for f in frasi)
    corrette = sum(f.cifre_istat_corrette for f in frasi)
    fornite = {r.voce for r in esito.righe if r.voce != VOCE_TOTALE}
    # R7 (review 2): una voce e' citata solo se nella frase c'e' una SUA cifra,
    # non solo perche' e' nominata accanto alla cifra di un'altra voce.
    citate = {v for f in frasi for v in f.voci_cifre} & fornite
    frasi_istat = [f for f in frasi if f.blocco == "istat" and f.cifre_istat]
    # A parola intera: "romano" non nomina "Roma".
    luoghi = [
        re.compile(rf"\b{re.escape(luogo)}\b")
        for luogo in sorted({r.luogo_breve.lower() for r in esito.righe})
    ]
    non_esatte = {
        r.voce
        for r in esito.righe
        if any(c.corrispondenza != "esatta" for c in r.collegamenti)
    }
    direzioni = [f for f in frasi if f.direzione_coerente is not None]
    return IstatMetrics(
        cifre_totali=cifre,
        cifre_istat_corrette=corrette,
        precisione_cifre=corrette / cifre if cifre else None,
        frasi_scartabili=esito.frasi_scartate,
        voci_fornite=len(fornite),
        voci_citate=len(citate),
        frasi_istat=len(frasi_istat),
        frasi_istat_con_luogo=sum(
            1
            for f in frasi_istat
            if any(luogo.search(f.testo.lower()) for luogo in luoghi)
        ),
        direzioni_totali=len(direzioni),
        direzioni_coerenti=sum(1 for f in direzioni if f.direzione_coerente),
        corrispondenze_non_dichiarate=sum(
            1
            for f in frasi
            if f.blocco == "istat"
            and set(f.voci) & non_esatte
            and not _DICHIARAZIONE.search(f.testo.lower())
        ),
        numeri_in_lettere=esito.numeri_in_lettere,
    )


def somma_istat_metrics(metriche: Iterable[IstatMetrics | None]) -> IstatMetrics | None:
    """Somma dei conteggi fra le ripetizioni; la precisione si ricalcola."""
    presenti = [m for m in metriche if m is not None]
    if not presenti:
        return None
    somme: dict[str, int] = {
        nome: sum(int(getattr(m, nome)) for m in presenti) for nome in _CONTEGGI
    }
    totali = somme["cifre_totali"]
    return IstatMetrics(
        **somme,
        precisione_cifre=somme["cifre_istat_corrette"] / totali if totali else None,
    )
