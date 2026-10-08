"""Fold delle K ripetizioni di un braccio (#157, spec-valutazione §2).

Riceve i K RunRecord di un esperimento (K run per ogni (citta, zona), prodotte
da run_experiment --repeat K) e li ripiega in UN record-media per zona + la
deviazione standard (popolazione) per metrica. Il record-media alimenta
l'esistente compare.compare_records (riuso #33); la varianza va nel report
esteso (repeated_comparison).

Politica esclusione (coerente con compare.py, #163): le ripetizioni in ERROR
E in FALLBACK non entrano in media/std (metriche non rappresentative della
qualita': azzerate dall'harness per ERROR, narrativa vuota per FALLBACK). Sono
contate in ZoneVariance.n_dropped, i soli FALLBACK anche in n_fallback; se
NESSUNA ripetizione di una zona e' valida (OK), il record-media eredita
status=ERROR (metriche azzerate) cosi' compare_records raccoglie quella zona
tra le escluse.
"""

from __future__ import annotations

import statistics
from collections import defaultdict

from pydantic import BaseModel

from crime_risk_analyzer.eval.compare import MetricValues
from crime_risk_analyzer.eval.istat_metrics import somma_istat_metrics
from crime_risk_analyzer.eval.schema import (
    IstatMetrics,
    Metrics,
    RunRecord,
    RunStatus,
)


class ZoneVariance(BaseModel):
    """Deviazione standard (popolazione) delle K ripetizioni di una zona."""

    citta: str
    zona: str
    std: MetricValues
    n_reps: int  # ripetizioni valide (OK) usate per media/std
    n_dropped: int  # ripetizioni escluse (tutto ciò che non è OK)
    n_fallback: int  # di cui FALLBACK (sottoinsieme di n_dropped), reliability


class FoldedArm(BaseModel):
    """Esito del fold di un braccio: record-media per zona + varianza per zona.

    ``mean_records`` ha ESATTAMENTE un record per (citta, zona) → consumabile
    da compare.compare_records senza violare il vincolo "una run per zona".
    """

    mean_records: list[RunRecord]
    variances: list[ZoneVariance]


_ZERO_METRICS = Metrics(grounding=0.0, hallucination=0.0, latency_ms=0, cost_usd=0.0)
_ZERO_STD = MetricValues(grounding=0.0, hallucination=0.0, latency_ms=0.0, cost_usd=0.0)


def _group_by_zone(
    records: list[RunRecord],
) -> dict[tuple[str, str], list[RunRecord]]:
    groups: dict[tuple[str, str], list[RunRecord]] = defaultdict(list)
    for rec in records:
        groups[(rec.citta, rec.zona)].append(rec)
    return groups


def _mean_metrics(valid: list[RunRecord]) -> Metrics:
    # quality_vacuous (#240) NON viene propagato/mediato qui: resta il default
    # None di Metrics, anche se una o piu' ripetizioni valide erano vacue. Non
    # esiste una regola di aggregazione dichiarata per un booleano su K
    # ripetizioni (tutte vacue? almeno una? maggioranza?) e deciderne una senza
    # una decisione esplicita sarebbe arbitrario. compare.py::_record_quality_vacuous
    # tratta None come "dato non disponibile" e ricade su has_narrativa per
    # questi record-media, quindi compare-repeated non regredisce: il segnale
    # e' semplicemente meno preciso qui che sul percorso a singola run, per
    # costruzione, non per un bug.
    n = len(valid)
    return Metrics(
        grounding=sum(r.metrics.grounding for r in valid) / n,
        hallucination=sum(r.metrics.hallucination for r in valid) / n,
        # latency arrotondata a int = precisione a cui la latenza viene
        # confrontata/riportata (§2.3 spec). Nel caso multi-zona la media
        # cross-zona (compare._mean) parte pero' da questi valori GIA'
        # arrotondati per-zona, non dalle latenze grezze: lo scostamento
        # risultante e' sub-ms, irrilevante ai fini del verdetto quando le
        # latenze dei bracci differiscono in modo apprezzabile.
        latency_ms=round(sum(r.metrics.latency_ms for r in valid) / n),
        cost_usd=sum(r.metrics.cost_usd for r in valid) / n,
    )


def _std_metrics(valid: list[RunRecord]) -> MetricValues:
    return MetricValues(
        grounding=statistics.pstdev([r.metrics.grounding for r in valid]),
        hallucination=statistics.pstdev([r.metrics.hallucination for r in valid]),
        latency_ms=statistics.pstdev([float(r.metrics.latency_ms) for r in valid]),
        cost_usd=statistics.pstdev([r.metrics.cost_usd for r in valid]),
    )


def _representative_narrativa(group: list[RunRecord]) -> str:
    """Narrativa di UNA ripetizione del gruppo, non una media (#231).

    La media di più testi non esiste, ma la DISPONIBILITÀ di testo sì, ed è
    un'informazione che il record-media deve conservare: a valle è ciò che
    distingue una zona su cui il braccio ha prodotto prosa (gradabile) da una su
    cui è rimasto muto, dove ``grounding``/``hallucination`` valgono 1.0/0.0 per
    vacuità. Azzerarla farebbe leggere come muto OGNI braccio ripiegato.

    Restituisce il testo della prima ripetizione che ne ha prodotto uno; stringa
    vuota se nessuna ha parlato. Non è un campione statistico: serve a rispondere
    a «questa zona ha prodotto narrativa?», non a rappresentarne il contenuto.
    """
    return next((rec.narrativa for rec in group if rec.narrativa.strip()), "")


def _poi_nel_prompt_coerente(
    citta: str, zona: str, valid: list[RunRecord]
) -> list[str] | None:
    """I POI nel prompt comuni alle ripetizioni valide di una zona (#349).

    La selezione dei POI e' deterministica, quindi le K ripetizioni di uno stesso
    esperimento hanno lo stesso insieme: se divergono, o se alcune hanno il campo
    e altre no (record precedenti a #349 mescolati a record nuovi), l'esperimento
    mescola versioni diverse del prompt. Solleva :class:`ValueError`, come
    ``compare_records`` sull'input malformato (zone duplicate, ``snapshot_id``
    divergente) e come l'harness sui record legacy (#165.4): un avviso
    lascerebbe comunque una media che mescola una ripetizione con 9-12 POI e due
    con 20, e a valle nessuno la distinguerebbe. Tutte senza campo = ``None``,
    e il confronto dira' che la parita' non e' verificabile.
    """
    valori = [r.poi_nel_prompt for r in valid]
    if all(v is None for v in valori):
        return None
    presenti = [v for v in valori if v is not None]
    if len(presenti) < len(valori):
        raise ValueError(
            f"fold_arm: ripetizioni di {citta}/{zona} con e senza poi_nel_prompt "
            "(record precedenti a #349 mescolati a record nuovi): non si mediano "
            "prompt con insiemi di POI diversi; rigirare tutte le ripetizioni"
        )
    if len({frozenset(v) for v in presenti}) > 1:
        raise ValueError(
            f"fold_arm: ripetizioni di {citta}/{zona} con poi_nel_prompt diversi: "
            "non si mediano prompt con insiemi di POI diversi; rigirare tutte le "
            "ripetizioni con lo stesso codice"
        )
    return presenti[0]


def _mean_record(
    source: RunRecord,
    metrics: Metrics,
    status: RunStatus,
    narrativa: str = "",
    istat_metrics: IstatMetrics | None = None,
    poi_nel_prompt: list[str] | None = None,
) -> RunRecord:
    """Record-media di una zona; riusa la provenienza (snapshot_id) di ``source``.

    ``narrativa`` è rappresentativa, non mediata: vedi
    :func:`_representative_narrativa`. ``istat_metrics`` (#345) e' invece la
    SOMMA delle K ripetizioni (``istat_metrics.somma_istat_metrics``): conteggi,
    non media, cosi' sommarla fra ripetizioni resta corretto.

    Dei campi ISTAT del record si ripiega SOLO ``istat_metrics``:
    ``istat_frasi_scartate`` e ``narrativa_grezza`` restano ai default (0 e
    ``None``) sul record-media. Le frasi tolte sono gia' contate nella somma
    (``IstatMetrics.frasi_scartabili``), e il grezzo, come la narrativa, non si
    media; chi li vuole per ripetizione li legge sui record delle ripetizioni.

    ``poi_nel_prompt`` (#349) e' quello, unico, delle ripetizioni valide
    (:func:`_poi_nel_prompt_coerente`): serve a ``compare_records`` per
    verificare la parita' dei POI fra i bracci anche sul percorso a K.
    """
    return RunRecord(
        run_id=f"{source.experiment}__{source.citta}__{source.zona}__mean".lower(),
        experiment=source.experiment,
        citta=source.citta,
        zona=source.zona,
        mode=source.mode,
        model_id=source.model_id,
        status=status,
        metrics=metrics,
        narrativa=narrativa,
        n_poi=source.n_poi,
        poi_nel_prompt=poi_nel_prompt,
        istat_metrics=istat_metrics,
        provenance=source.provenance,
    )


def fold_arm(records: list[RunRecord]) -> FoldedArm:
    """Ripiega le K ripetizioni per zona in record-media + varianza.

    Solleva :class:`ValueError` se ``records`` e' vuoto, o se le ripetizioni
    valide di una zona hanno ``poi_nel_prompt`` diversi o misti presente/assente
    (#349, :func:`_poi_nel_prompt_coerente`).
    """
    if not records:
        raise ValueError("fold_arm: nessun record da ripiegare")
    groups = _group_by_zone(records)
    mean_records: list[RunRecord] = []
    variances: list[ZoneVariance] = []
    for citta, zona in sorted(groups):
        group = groups[(citta, zona)]
        # Solo OK entra in media/std, espresso in positivo e non come elenco di
        # status da escludere: un valore nuovo dell'enum (``HARNESS_ERROR``)
        # nasce con metriche azzerate, e una lista di esclusioni dimenticata lo
        # farebbe mediare come se fosse una misura. Il criterio e' verificato
        # sull'enum intero in ``test_repeat.py``.
        valid = [r for r in group if r.status is RunStatus.OK]
        n_fallback = sum(1 for r in group if r.status == RunStatus.FALLBACK)
        n_dropped = len(group) - len(valid)
        if not valid:
            mean_records.append(_mean_record(group[0], _ZERO_METRICS, RunStatus.ERROR))
            variances.append(
                ZoneVariance(
                    citta=citta,
                    zona=zona,
                    std=_ZERO_STD,
                    n_reps=0,
                    n_dropped=n_dropped,
                    n_fallback=n_fallback,
                )
            )
            continue
        # Il record-media prende status OK anche se il gruppo conteneva FALLBACK:
        # i fallback sono gia' esclusi da media/std (#163) e il loro segnale
        # viaggia via ZoneVariance.n_fallback (reso visibile nel report, #165.3).
        # Cambiare qui lo status altererebbe la selezione zone di compare_records.
        mean_records.append(
            _mean_record(
                valid[0],
                _mean_metrics(valid),
                RunStatus.OK,
                _representative_narrativa(valid),
                somma_istat_metrics(r.istat_metrics for r in valid),
                _poi_nel_prompt_coerente(citta, zona, valid),
            )
        )
        variances.append(
            ZoneVariance(
                citta=citta,
                zona=zona,
                std=_std_metrics(valid),
                n_reps=len(valid),
                n_dropped=n_dropped,
                n_fallback=n_fallback,
            )
        )
    return FoldedArm(mean_records=mean_records, variances=variances)
