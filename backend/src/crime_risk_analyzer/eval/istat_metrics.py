"""ISTAT metrics of the narrative (#345, spec 4.9), from the check outcome.

Version 2 (#365): ISTAT data are used in words in the [ONTOLOGIA] block, without
figures. The "ISTAT sentences" are those of any block that speak of the datum
(:attr:`~crime_risk_analyzer.istat.figures.CheckedSentence.parla_di_istat`); the
fields whose meaning changes are listed in
:class:`~crime_risk_analyzer.eval.schema.IstatMetrics`. Version 4 (#369): also
counts the ISTAT sentences excluded from M1; since #378 how many of these do not name an
item of the prompt rows (new field, ``None`` on earlier records: the
version does not change).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from crime_risk_analyzer.eval.schema import IstatMetrics
from crime_risk_analyzer.istat.data import TOTAL_ITEM
from crime_risk_analyzer.istat.figures import CheckOutcome, names_item_of_rows

__all__ = [
    "ISTAT_METRICS_VERSION",
    "compute_istat_metrics",
    "excluded_sentences_without_item",
    "sum_istat_metrics",
]

#: Version of the ISTAT metrics written by :func:`compute_istat_metrics`. 1 =
#: #345 (figures in the [ISTAT] block), 2 = #365 (data in words, no figures), 3 =
#: #368 (M1 does not measure ISTAT sentences: same counts, other text graded), 4 =
#: #369 (M1 excludes only ISTAT sentences with neither POI nor risk, counted in
#: ``frasi_escluse_m1``).
ISTAT_METRICS_VERSION = 4

#: Heuristic: the sentence says the item does not coincide with the risk.
_DECLARATION = re.compile(
    r"non coincid|ampia del rischio|pi(?:ù|u'?) ampi|pi(?:ù|u'?) ristrett"
    r"|solo (?:in )?parte|solo una parte|parzial|comprende anche"
)

_COUNTS = (
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


def excluded_sentences_without_item(
    excluded: Sequence[str], outcome: CheckOutcome
) -> list[str]:
    """Sentences excluded from M1 that name no item of the ISTAT rows of the
    prompt nor a linked risk (#378), in the order of the excluded ones.

    They are candidates to read by hand, not a verdict: a risk outside the
    knowledge base written with the words of the ISTAT datum ("according to the
    ISTAT data ... kidnappings") ends up here, but so does a sentence about the datum in
    general, with a synonym of the item, a list number or a sentence
    fragment. A sentence that names an item of the rows and also an invented risk
    is not there, nor is an invented variant that shares its root
    ("furti" covers "furti di identita' digitale"). The recognition is that of
    :func:`~crime_risk_analyzer.istat.figures.names_item_of_rows`: items and
    linked risks; the phrase "delitti denunciati" does not count, the label
    "totale dei delitti" does.
    """
    return [f for f in excluded if not names_item_of_rows(f, outcome.righe)]


def compute_istat_metrics(
    outcome: CheckOutcome,
    *,
    frasi_escluse_m1: int,
    frasi_escluse_senza_voce: int | None = None,
) -> IstatMetrics:
    """Deterministic metrics on the raw text examined by the check.

    ``frasi_escluse_m1`` (#369) comes from outside: which ISTAT sentences M1 excludes
    depends on the POIs and risks of the answer, which the check does not know
    (:func:`~crime_risk_analyzer.eval.metrics.m1_excluded_sentences`). So also
    ``frasi_escluse_senza_voce`` (#378, :func:`excluded_sentences_without_item`).
    """
    sentences = outcome.frasi
    provided = {r.voce for r in outcome.righe if r.voce != TOTAL_ITEM}
    istat_sentences = [f for f in sentences if f.parla_di_istat]
    # An item is cited if an ISTAT sentence that the filter KEEPS names it.
    cited = {v for f in istat_sentences if f.motivo is None for v in f.voci} & provided
    inexact = {
        r.voce
        for r in outcome.righe
        if any(c.corrispondenza != "esatta" for c in r.collegamenti)
    }
    directions = [f for f in sentences if f.direzione_coerente is not None]
    comparisons = [f for f in sentences if f.confronto_coerente is not None]
    return IstatMetrics(
        versione=ISTAT_METRICS_VERSION,
        cifre_totali=sum(f.cifre for f in sentences),
        cifre_istat=sum(f.cifre_istat for f in sentences),
        frasi_scartabili=outcome.frasi_scartate,
        voci_fornite=len(provided),
        voci_citate=len(cited),
        frasi_istat=len(istat_sentences),
        frasi_istat_con_luogo=sum(1 for f in istat_sentences if f.luogo),
        frasi_istat_con_luogo_ereditato=sum(
            1 for f in istat_sentences if f.luogo_ereditato
        ),
        direzioni_totali=len(directions),
        direzioni_coerenti=sum(1 for f in directions if f.direzione_coerente),
        confronti_totali=len(comparisons),
        confronti_coerenti=sum(1 for f in comparisons if f.confronto_coerente),
        corrispondenze_non_dichiarate=sum(
            1
            for f in istat_sentences
            if set(f.voci) & inexact and not _DECLARATION.search(f.testo.lower())
        ),
        numeri_in_lettere=outcome.numeri_in_lettere,
        codici_voce=outcome.codici_voce,
        frasi_escluse_m1=frasi_escluse_m1,
        frasi_escluse_senza_voce=frasi_escluse_senza_voce,
    )


def sum_istat_metrics(metrics: Iterable[IstatMetrics | None]) -> IstatMetrics | None:
    """Sum of the counts across repetitions (all of the same version).

    ``frasi_escluse_senza_voce`` (#378) is ``None`` if it is missing in one repetition.
    """
    present = [m for m in metrics if m is not None]
    if not present:
        return None
    versions = {m.versione for m in present}
    if len(versions) != 1:
        raise ValueError(
            f"metriche ISTAT di versioni diverse {sorted(versions)}: non si sommano"
        )
    sums: dict[str, int] = {
        name: sum(int(getattr(m, name)) for m in present) for name in _COUNTS
    }
    without_item = [m.frasi_escluse_senza_voce for m in present]
    return IstatMetrics(
        versione=versions.pop(),
        frasi_escluse_senza_voce=(
            None
            if any(n is None for n in without_item)
            else sum(n for n in without_item if n is not None)
        ),
        **sums,
    )
