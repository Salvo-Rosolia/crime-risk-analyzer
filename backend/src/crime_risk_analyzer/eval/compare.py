"""Two-arm comparison of evaluation experiments (#32).

GENERIC primitive: given the ``RunRecord``s of TWO experiments (arm A and arm
B), it joins them by ``(citta, zona)`` and computes the DELTA (A - B) of the four
metrics -- ``grounding``, ``hallucination``, ``latency_ms``, ``cost_usd`` --
producing a per-zone table plus an aggregate row (mean), serializable
to CSV and Markdown.

Runs in ERROR (metrics zeroed by the harness) and in FALLBACK (empty narrative
-> metrics not representative of quality) do NOT enter deltas/means: the
corresponding zones are excluded from the aggregate and explicitly reported in
a dedicated section (nothing is discarded or averaged silently). Only ``OK``
runs stay included (#163).

It is not wired to analyze/baseline: the arms are labelled freely
(``label_a``/``label_b``). The ablation (#32) compares ``analyze`` vs
``baseline``; #33 will reuse the same primitive for ``claude`` vs ``groq``.

Reuses the style and the ``load_runs`` helper of :mod:`aggregate` without modifying it.
"""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from crime_risk_analyzer.eval.aggregate import load_runs
from crime_risk_analyzer.eval.metrics import (
    InconsistentExcludedSentencesError,
    RiskAnchoring,
    risk_anchoring,
)
from crime_risk_analyzer.eval.schema import IstatMetrics, Metrics, RunRecord, RunStatus

logger = logging.getLogger(__name__)

#: Label of the aggregate row in the tables.
_MEAN_LABEL = "MEDIA"

#: Statuses that exclude a zone from the comparison: metrics not representative
#: of quality (ERROR = zeroed by the harness; FALLBACK = empty narrative, #163;
#: HARNESS_ERROR = zeroed too, but because of an instrumentation failure
#: downstream of the pipeline). The general rule applies: **everything that is not OK
#: stays out of the means** -- a new status is born without a measure, and including it
#: would make an arm get worse because of a bug. The constraint is verified
#: on the whole enum in ``test_compare.py``.
_EXCLUDED_STATUSES = (RunStatus.ERROR, RunStatus.FALLBACK, RunStatus.HARNESS_ERROR)


def guard_no_overwrite(paths: list[Path], force: bool) -> None:
    """Raise FileExistsError if a target file exists and ``force`` is False.

    Protects from accidental overwrites (e.g. same --out for compare and
    compare-repeated: X.csv would be left orphaned). ``--force`` bypasses the guard.
    """
    if force:
        return
    existing = [str(p) for p in paths if p.exists()]
    if existing:
        raise FileExistsError(
            "file di output gia' esistenti: "
            + ", ".join(existing)
            + ". Usa --force per sovrascrivere."
        )


class MetricValues(BaseModel):
    """Four metrics as floats, for means and deltas.

    Unlike :class:`~crime_risk_analyzer.eval.schema.Metrics` it does not impose
    ``[0,1]``: a delta (A - B) can be negative, and mean ``latency_ms`` is a
    float.
    """

    grounding: float
    hallucination: float
    latency_ms: float
    cost_usd: float


class ZoneComparison(BaseModel):
    """Comparison of a single zone ``(citta, zona)`` between the two arms."""

    citta: str
    zona: str
    a: Metrics
    b: Metrics
    delta: MetricValues


class FailedZone(BaseModel):
    """Zone excluded from the aggregate because an arm is in ``ERROR`` or ``FALLBACK``.

    Reports the status of BOTH arms so the exclusion is traceable
    (which arm failed or fell back), not silent.
    """

    citta: str
    zona: str
    status_a: str
    status_b: str


class VacuousZone(BaseModel):
    """Zone on which an arm produced no narrative (#231).

    It is not an exclusion: the zone stays in the aggregate (the operational measures
    are valid). It signals that on THAT zone the quality metrics of the arm in
    ``arms`` are vacuous, so the resulting mean does not support a verdict.
    """

    citta: str
    zona: str
    #: Labels of the arms that stayed mute on this zone (one or both).
    arms: list[str]


class IstatZoneMetrics(BaseModel):
    """ISTAT metrics (#345) of the two arms on a zone, side by side: no delta."""

    citta: str
    zona: str
    a: IstatMetrics | None
    b: IstatMetrics | None


class RiskAnchoringArm(BaseModel):
    """Risk anchoring of an arm, on a zone or on the whole arm (#359).

    Exploratory and placed alongside M1: the verdict does not use it. Only the
    gradable narratives count (:func:`~crime_risk_analyzer.eval.metrics.risk_anchoring`
    different from ``None``) of the ``OK`` runs from which the text that M1
    measures can be rebuilt: all those without ISTAT data and those with ISTAT metrics
    from version 4, measured on the raw text without the excluded ISTAT sentences
    (#377). The latter are counted in ``run_istat_incluse`` and their excluded sentences
    in ``frasi_istat_escluse``; the ISTAT runs from which the text cannot be rebuilt
    are counted in ``run_istat_escluse`` (see :func:`_record_anchoring`).
    The totals are sums of sentences; the ``quota_*`` are fractions of the measured
    sentences (``None`` if no sentence); ``frasi_misurate_media``,
    ``ancoraggio_rischi`` and ``ancoraggio_rischi_conformi`` are per-narrative means
    on the zone and, for the whole arm, means of the zones (like the
    M1 means of the comparison). ``ancoraggio_rischi`` counts the non-conforming
    narratives as 0; ``ancoraggio_rischi_conformi`` excludes them. ``None`` where there
    is no narrative to average.
    """

    narrative_gradabili: int
    non_conformi: int
    frasi_misurate: int
    frasi_ancorate_rischio: int
    frasi_ancorate_solo_poi: int
    frasi_ancorate_poi_e_rischio: int
    frasi_misurate_media: float | None
    quota_rischio: float | None
    quota_solo_poi: float | None
    ancoraggio_rischi: float | None
    ancoraggio_rischi_conformi: float | None
    run_istat_escluse: int = 0
    run_istat_incluse: int = 0
    frasi_istat_escluse: int = 0


class RiskAnchoringZone(BaseModel):
    """Risk anchoring of the two arms on a zone (#359)."""

    citta: str
    zona: str
    a: RiskAnchoringArm
    b: RiskAnchoringArm


class RiskAnchoringSection(BaseModel):
    """ "Risk anchoring (exploratory)" section of the comparison (#359)."""

    zones: list[RiskAnchoringZone]
    a: RiskAnchoringArm
    b: RiskAnchoringArm
    #: Labels of the arms in which the sentences anchored only by POI names are more
    #: than those that name a POI and a risk together (:func:`poi_only_prevails`):
    #: it makes the pointer to the section appear next to the verdict.
    solo_poi_prevale: list[str]


class QualityVerdict(BaseModel):
    """Answers by itself: "is the quality verdict applicable?" (#238).

    Before this field, a tie (no vacuous zone, but the 4 axes coincide)
    and abstention (vacuous metrics, #231) were indistinguishable without inspecting
    the SHAPE of ``winner`` in the repeated report -- and the non-repeated report had
    no way of answering the same question. A field of the
    :class:`Comparison` model, not bolted-on in the individual writers: any future
    consumer of ``to_json``/``model_dump`` receives it by construction, not by
    discipline of whoever writes the payload.
    """

    applicable: bool
    vacuous_arms: list[str]
    vacuous_zones: list[VacuousZone]
    reason: str = ""


class Comparison(BaseModel):
    """Comparison: compared zones + aggregate + excluded zones (ERROR/FALLBACK)."""

    label_a: str
    label_b: str
    zones: list[ZoneComparison]
    mean_a: MetricValues
    mean_b: MetricValues
    mean_delta: MetricValues
    #: Zones excluded from the aggregate (an arm in ERROR or FALLBACK); empty if none.
    #: Always set by :func:`compare_records`.
    failed: list[FailedZone]
    #: Labels of the STRUCTURALLY VACUOUS arms (#231): no run of the arm
    #: produced narrative. On a mute arm ``grounding``/``hallucination``
    #: fall into the vacuous branch of ``metrics.py`` (1.0/0.0 for absence of text to
    #: judge), so the quality axes are NOT interpretable: whoever reads
    #: the comparison must be warned and no verdict must be issued on those axes.
    #: Empty in the normal case (both arms generate).
    vacuous_arms: list[str] = []
    #: Zones on which an arm stayed mute while not being mute overall
    #: (#231): finer granularity than ``vacuous_arms``, because a single
    #: vacuous zone shifts the mean that decides the verdict. Superset: if an arm
    #: is in ``vacuous_arms``, all its zones are also here.
    vacuous_zones: list[VacuousZone] = []
    #: Declaration of WHAT the comparison manipulates, when the modes of the two arms
    #: make it derivable (#236); empty otherwise -- and then the report stays
    #: identical to before. It is not a conclusion: it says which variable changes
    #: between the arms, while the reading of the quality deltas stays bound to the
    #: :data:`PROXY_CAVEAT`. On the right pair of modes but with diverging
    #: settings (model or temperature) it carries the OPPOSITE warning
    #: (:data:`CONFOUNDED_VARIABLE_HEAD`): the field never claims that the
    #: variable is isolated without having verified it on the records.
    isolated_variable: str = ""
    #: Derived from ``vacuous_arms``/``vacuous_zones`` above, always at construction
    #: time (#238): see :class:`QualityVerdict`.
    quality_verdict: QualityVerdict
    #: ISTAT metrics per zone (#345), only if at least one arm has them. Placed side by
    #: side and never averaged into a verdict (D12).
    istat_metrics: list[IstatZoneMetrics] = []
    #: Warning when the two arms have ISTAT metrics of different versions (#369):
    #: M1 is graded with different rules. Field of the model, like
    #: ``isolated_variable``, so JSON and Markdown say the same thing; empty
    #: otherwise.
    avviso_versioni_istat: str = ""
    #: Warning when the records of the two arms, or within an arm, have different
    #: versions of M1 (#408): grounding/hallucination are graded with different
    #: semantics. It does not reject, it warns; empty otherwise. Field of the model like
    #: ``avviso_versioni_istat``.
    avviso_versioni_m1: str = ""
    #: Risk anchoring separate from the one on POI names (#359), computed
    #: from the records at report time. ``None`` if no arm has a
    #: gradable narrative (e.g. baseline against baseline). It does not enter the
    #: verdict.
    ancoraggio_rischi: RiskAnchoringSection | None = None


@dataclass(frozen=True)
class _MetricSpec:
    """Single source for the columns and formatting of a metric (avoids m2 drift)."""

    name: str
    value_fmt: str
    delta_fmt: str
    get: Callable[[MetricValues], float]


_GROUNDING_SPEC = _MetricSpec("grounding", "{:.3f}", "{:+.3f}", lambda m: m.grounding)
_HALLUCINATION_SPEC = _MetricSpec(
    "hallucination", "{:.3f}", "{:+.3f}", lambda m: m.hallucination
)
_LATENCY_SPEC = _MetricSpec("latency_ms", "{:.0f}", "{:+.0f}", lambda m: m.latency_ms)
_COST_SPEC = _MetricSpec("cost_usd", "{:.6f}", "{:+.6f}", lambda m: m.cost_usd)

#: Order and format of the 4 metrics. Drives BOTH the headers AND the rows:
#: adding a metric here updates header and cells consistently.
_METRIC_SPECS: tuple[_MetricSpec, ...] = (
    _GROUNDING_SPEC,
    _HALLUCINATION_SPEC,
    _LATENCY_SPEC,
    _COST_SPEC,
)

#: "Operational" subset (DIRECT measures): drives the cost/latency table
#: separate from the textual quality proxy metrics (#33). Same specs as the full set
#: -> same format/sign, no duplication of formatting.
_OPERATIONAL_SPECS: tuple[_MetricSpec, ...] = (_LATENCY_SPEC, _COST_SPEC)

#: Methodological caveat printed at the end of the Markdown report (#33). ``grounding``
#: and ``hallucination`` are TEXTUAL PROXIES (estimated from patterns on source tags and
#: on POI names in ``metrics.py``), not human judgements of quality;
#: ``latency_ms`` and ``cost_usd`` are instead direct operational measures. The
#: PER-RUN proxy-vs-human-annotation comparison on these aggregate metrics
#: was removed (#152): ``eval/gold.py`` today validates at another grain
#: (per-risk, not on grounding/hallucination aggregated per run).
PROXY_CAVEAT = (
    "> **Nota metodologica.** `grounding` e `hallucination` sono *proxy "
    "testuali* (copertura delle citazioni e frazione di asserzioni non "
    "ancorate, stimate da pattern sui tag fonte e sui nomi dei POI), non "
    "giudizi umani di qualità: vanno letti come indicatori orientativi, non "
    "come verità. `latency_ms` e `cost_usd` sono invece misure operative "
    "dirette. Un accordo proxy-vs-annotazione umana su queste metriche "
    "aggregate non è oggi validato: `eval/gold.py` (#152) annota a un'altra "
    "grana, per-singolo-rischio citato in narrativa."
)


#: Title of the exploratory section on risk anchoring (#359).
RISK_ANCHORING_HEAD = "### Ancoraggio ai rischi (esplorativo)"

#: Fixed note of the section (#359): what it separates, why it is partly circular and
#: what it cannot say.
RISK_ANCHORING_NOTE = (
    "> **Come leggere questa sezione.** Il `grounding` della tabella principale "
    "conta come ancorata solo una frase che nomina un punto (da M1 v3): un "
    "rischio da solo non basta, perché il prompt impone le etichette dei rischi. "
    "Qui le frasi sono separate per cosa nominano. Una frase è «da rischio» se "
    "nomina almeno un rischio della base di conoscenza (identificativo o "
    "etichetta italiana o inglese), anche senza un punto; «solo POI» se non "
    "nomina rischi ma nomina un punto. Le frasi ancorate dal `grounding` sono "
    "quelle «solo POI» più quelle che nominano punto e rischio insieme (queste "
    "ultime contano in «da rischio» e nel testo sotto la tabella sono «POI e "
    "rischio»). Una narrativa è "
    "non conforme al formato quando manca il blocco misurato. La colonna "
    "«narrative» conta le narrative gradabili, comprese le non conformi. "
    "% = frasi del braccio messe insieme, narrative non conformi escluse; "
    "`ancoraggio_rischi` = quota di frasi da rischio di ogni narrativa, media "
    "per narrativa, poi media delle zone, narrative non conformi contate come 0 "
    "(la colonna «solo conformi» le esclude).\n"
    ">\n"
    "> La misura è in parte circolare: il braccio senza ontologia non conosce le "
    "etichette esatte e può dire lo stesso rischio con altre parole («minacce "
    "terroristiche» invece di «Attacco terroristico»). Misura quindi quanto i "
    "rischi nominati seguono il vocabolario della base di conoscenza, non se "
    "sono corretti: per la correttezza serve l'annotazione umana. Il verdetto "
    "non usa queste misure."
)


#: Sentence of the section when some runs with ISTAT data are left out of it
#: (#359, #377): M1 measured them on a text that cannot be rebuilt from the record.
RISK_ANCHORING_ISTAT_EXCLUDED = (
    "Restano fuori dalla sezione le run con dati ISTAT da cui non si ricostruisce "
    "il testo misurato dal `grounding`: record scritti prima della versione 4 "
    "delle metriche ISTAT, senza il testo del modello (`narrativa_grezza`), senza "
    "le frasi escluse (`frasi_escluse_m1`) o con frasi escluse che non sono nel "
    "testo del modello"
)

#: Warning of the section when it contains runs with ISTAT data (#377): it measures the
#: text that M1 measures, rebuilt from the record (raw text minus ``frasi_escluse_m1``).
RISK_ANCHORING_ISTAT_INCLUDED = (
    "> **Run con dati ISTAT.** Per queste run la sezione misura lo stesso testo "
    "del `grounding`: quello scritto dal modello prima del filtro delle cifre, "
    "che può contenere accenni ai dati ISTAT a parole. Come il `grounding`, non "
    "conta le frasi che parlano del dato ISTAT senza nominare un punto né un "
    "rischio: il loro numero, per braccio, è nella riga qui sotto. Le righe dei "
    "dati ISTAT nel prompt riportano le etichette dei rischi collegati "
    "(«Collegata a: ...»): una frase ISTAT che le riprende conta «da rischio». "
    "La quota può quindi salire per le frasi ISTAT e non perché il modello "
    "nomini rischi per i punti."
)


#: Title of the vacuity warning (#231). Printed BEFORE the tables: whoever reads
#: must know that on these axes the comparison is not interpretable before
#: meeting the numbers, not after. Single source of the wording (the repeated
#: report reuses it to justify the withheld verdict).
VACUOUS_CAVEAT_HEAD = "> ⚠️ **Assi di qualità non applicabili.**"

#: Explanation of why a mute arm does not deserve 1.0/0.0. Shared between the
#: caveat of the tables and the "withheld verdict" section of the repeated report:
#: a single formulation, no drift between the two modules.
VACUOUS_REASON = (
    "`grounding`/`hallucination` cadono nel ramo vacuo di `metrics.py` "
    "(1.0/0.0 perché non c'è testo da giudicare), che non è un merito"
)

#: What to say about the operational measures (latency, cost) when the quality axes
#: are vacuous: they are raw numbers readable in the tables, not a comparison
#: declared on them -- saying "they remain comparable" would promise an
#: outcome that the report neither computes nor prints (#237). Single source of the
#: wording, shared between the caveat of the tables below and the "withheld
#: verdict" section of the repeated report: same reason as the pattern already used for
#: VACUOUS_REASON, so the two formulations do not diverge again.
OPERATIONAL_AXES_NOTE = (
    "i valori operativi (latenza, costo) restano leggibili nelle tabelle, letti "
    "direttamente e non come un confronto dichiarato"
)


#: Title of the isolated-variable declaration (#236). Like the vacuity
#: warning it opens the report: whoever reads must know WHAT distinguishes the two arms
#: before meeting the deltas, not after.
ISOLATED_VARIABLE_HEAD = "> **Variabile isolata.**"

#: Title of the opposite case (#236): the modes WOULD ISOLATE the ontology, but the arms
#: do not run with the same setting (different model or temperature), so
#: between them more than one variable changes. It goes where the declaration would go,
#: for the same reason: saying something false at the top of the report is worse than
#: saying nothing, and staying silent would leave the delta without reading
#: instructions.
CONFOUNDED_VARIABLE_HEAD = "> ⚠️ **Variabile non isolata.**"

#: Warning that ALWAYS accompanies the with/without-ontology pair (#236), in either
#: of the two branches of the note: the operational differences observed between these
#: arms are not a merit. The ablated prompt carries no hazard, vulnerability or
#: citations, so it is shorter by construction and consumes fewer tokens in less
#: time regardless of what it writes. It must be said next to the declaration of the
#: variable because the operational table (#33) places latency and cost side by side as
#: if they were an outcome of the comparison -- and on this pair they are an outcome of
#: the length of the text sent. Consistent with the exclusion of the operational
#: tie-break from the verdict (``winner.decide_winner``, ``operational_tiebreak``).
PROMPT_LENGTH_SIDE_EFFECT = (
    "Le eventuali differenze di `latency_ms`/`cost_usd` tra questi due bracci "
    "NON sono un merito: il prompt senza ontologia è strutturalmente più corto "
    "(non porta hazard, vulnerabilità e citazioni), quindi consuma meno token in "
    "meno tempo a prescindere dalla qualità della prosa. Per questa coppia "
    "velocità e costo non sono spareggi validi e il verdetto non li usa."
)

#: What the quality delta means when the variable IS isolated (#236) and the
#: quality axes are readable. A named constant because it is the most
#: committing claim of the report -- the one a reader quotes -- and because the vacuous
#: branch must be able to REPLACE it, not sit beside it (see
#: :data:`VACUOUS_DELTA_CLAIM`).
ISOLATED_DELTA_CLAIM = (
    "Il delta su `grounding`/`hallucination` misura quindi l'effetto "
    "dell'ancoraggio ontologico nel prompt, a parità di punti, su quanto la prosa "
    "nomina dati verificabili — non la qualità complessiva dell'analisi, e non "
    "con la forza di un giudizio umano (vedi la nota metodologica)."
)

#: Title of the validity warning when the two arms see the same POIs but
#: not all those of the zone (#349): the full arm truncates by budget and
#: the ablated one lists the same subset. Parity is verified; the CHOICE of
#: points however comes from the full arm's cut, i.e. from the ontology, and must be
#: said.
POI_SUBSET_VALIDITY_HEAD = "**Validità: stessi POI, ma non tutti quelli della zona.**"

#: Body of the warning (#349). The direction is NOT determined: the cut keeps the
#: classes with many risks (Police, School, Hospital) and discards those with few
#: (pharmacies, banks), whose risks are close to what a model without
#: ontology would write anyway -- so one cannot say that the choice helps one
#: of the two arms, and it must not be written.
POI_SUBSET_VALIDITY_BODY = (
    "li ha scelti il taglio per budget del braccio completo, per rilevanza "
    "(numero di rischi dell'ontologia), e l'altro braccio elenca gli stessi. Il "
    "verso dell'effetto di questa scelta sul confronto NON è determinato: il "
    "taglio tiene le classi con molti rischi e scarta quelle con pochi, i cui "
    "rischi sono vicini a ciò che un modello senza ontologia scriverebbe "
    "comunque. Va dichiarato nella lettura del delta."
)

#: Replaces :data:`ISOLATED_DELTA_CLAIM` when the comparison has vacuous quality
#: axes (#231): ONE mute zone in an arm is enough. The two blocks that open the
#: report speak of the same axes, so claiming that the delta measures
#: the effect of the ontology and then that those axes are not interpretable in
#: any direction is a contradiction within the same document. The isolation
#: stays true as a property of the DESIGN (the two arms share the setting,
#: it is verified on the records) and must be said: it is the delta that is not
#: readable, not the design that is wrong.
VACUOUS_DELTA_CLAIM = (
    "L'isolamento riguarda però il DISEGNO dei due bracci, non i numeri di "
    "questo confronto: qui `grounding`/`hallucination` cadono nel ramo vacuo "
    "(vedi l'avviso sugli assi di qualità), quindi il delta su quegli assi NON "
    "va letto come effetto dell'ancoraggio ontologico, in nessuna direzione."
)

#: Pair of ``mode``s that manipulates the ontological contribution in the prompt (#236):
#: it changes what the prompt carries to the model. It is the only pair of arms for
#: which the module declares the variable -- ``analyze`` vs ``baseline`` manipulates the
#: presence of the LLM, two models manipulate the model. NECESSARY but not
#: sufficient: that the rest of the setting is shared is verified by
#: :data:`_SHARED_SETTINGS` (model, temperature, context format) and
#: ``compare_records`` (the POI snapshot), not by this pair.
_ONTOLOGY_ISOLATING_MODES = frozenset({"analyze", "no_ontology_prompt"})

#: Title of the declaration for the ontology vs ontology + ISTAT pair (#345).
ISTAT_ISOLATED_VARIABLE_HEAD = "> **Variabile isolata: ISTAT.**"

#: On this pair no automatic winner (D12).
ISTAT_NO_WINNER_REASON = (
    "confronto ontologia vs ontologia + ISTAT: nessun vincitore automatico (D12); "
    "grounding/hallucination servono solo a verificare che ISTAT non peggiori "
    "l'ancoraggio e le metriche ISTAT sono affiancate"
)

#: Limit of the M1 splitter on ISTAT sentences (#369, C1), part of the note.
ISTAT_M1_SPLITTER_LIMIT = (
    "Limite: M1 spezza le frasi a ogni punto, quindi una frase ISTAT con "
    "«d.lgs. 7/2016» o «134.169» diventa più pezzi, e un pezzo senza le parole del "
    "dato ISTAT resta misurato come non ancorato."
)

#: Note under the ISTAT table (#369): what M1 is graded on in the arm with ISTAT
#: and which limits follow from it.
ISTAT_M1_REDUCED_TEXT = (
    "> **M1 su un testo ridotto.** Nel braccio con i dati ISTAT `grounding` e "
    "`hallucination` sono calcolati sul testo del modello prima del filtro, senza "
    "le frasi che parlano del dato ISTAT e non nominano un POI né un rischio, che "
    "escono dal denominatore. Le frasi escluse sono contate nella colonna «frasi "
    "escluse da M1» ed elencate nel "
    "record di ogni run (`frasi_escluse_m1`). Limite: un rischio che non è nella "
    "base di conoscenza, scritto con le parole del dato ISTAT, esce dal "
    "denominatore invece di contare come non ancorato, e va cercato fra le frasi "
    f"escluse. {ISTAT_M1_SPLITTER_LIMIT} Nei record di versione 3 erano escluse "
    "tutte le frasi che parlano del dato, nelle versioni 1 e 2 quelle con cifre "
    "ISTAT."
)

#: Note on the sentences excluded from M1 that name no item of the prompt (#378),
#: under the one on the reduced text: candidates to read by hand, not a verdict.
ISTAT_EXCLUDED_WITHOUT_ITEM_TEXT = (
    "> **Frasi escluse senza voce ISTAT del prompt.** Sono le frasi escluse che "
    "non nominano nessuna voce delle righe ISTAT passate al modello né un rischio "
    "collegato a quelle righe. Le voci si riconoscono per etichetta e per rischio "
    'collegato, con tolleranza sulle radici ("furti" copre anche "furti di '
    'identità digitale"): una variante inventata che condivide la radice di una '
    "voce non è fra le candidate. Sono elencate nei record scritti da #378 in poi "
    "(`frasi_escluse_senza_voce`; dove manca, il conteggio è n/d). Sono candidate "
    "da leggere a mano: possono nominare un rischio che non è nella base di "
    "conoscenza, ma anche parlare del dato in generale, usare un sinonimo della "
    "voce, essere un numero d'elenco o un frammento di frase. Non sono un "
    "conteggio di rischi inventati e non cambiano `grounding`, `hallucination` né "
    "il verdetto. Una frase che nomina una voce delle righe e anche un rischio "
    "inventato non è fra queste."
)

#: Title of the warning when the two arms have ISTAT metrics of different
#: versions (#369, D2): M1 is graded with different rules in the two arms.
ISTAT_VERSIONS_DIFFER_HEAD = "> ⚠️ **Metriche ISTAT di versioni diverse.**"

#: Title of the warning when the records have different versions of M1 (#408),
#: between the two arms or within one: grounding/hallucination are not comparable.
M1_VERSIONS_DIFFER_HEAD = "> ⚠️ **Metriche M1 di versioni diverse.**"

#: Declared side effect: the ISTAT block occupies budget (#345, D14).
ISTAT_BUDGET_SIDE_EFFECT = (
    "Il blocco DATI ISTAT occupa parte del budget di token del prompt: su una zona "
    "densa il braccio con ISTAT puo' ricevere meno POI di quello senza, e anche "
    "questo e' un effetto della variabile, non un difetto del confronto."
)

#: Settings that the two arms must SHARE for the pair of modes
#: to really isolate only the ontological contribution of the prompt: pairs ``(readable
#: name, record access)``. The ``mode`` says what changes in the prompt, not
#: with which generator the prose was written, nor with which form the POI block
#: was rendered, nor with which sampling the text was drawn: a Claude
#: run against a Groq run changes prompt AND model together, a ``per_classe``
#: arm against a ``per_poi`` one changes prompt AND format -- which #273 keeps
#: optional precisely because it is not obvious which of the two makes more points be
#: named -- and two different seeds make two different prose come out of the same
#: prompt. They are all dimensions that act on the axis the proxies measure. The
#: ``snapshot_id`` is not here because ``compare_records`` already enforces it by
#: raising on divergence.
_SHARED_SETTINGS: tuple[tuple[str, Callable[[RunRecord], object]], ...] = (
    ("modello", lambda rec: rec.model_id),
    ("temperatura", lambda rec: rec.provenance.temperature),
    ("formato del contesto", lambda rec: rec.provenance.context_format),
    ("seed di campionamento", lambda rec: rec.provenance.seed),
    # #345: the budget decides how many POIs go into the prompt (F8 of the final
    # review): an old record (budget not recorded) against a new one does not
    # share the setting, even if model and seed coincide.
    (
        "budget di token della richiesta",
        lambda rec: rec.provenance.request_token_budget,
    ),
    ("max_tokens della risposta", lambda rec: rec.provenance.llm_max_tokens),
    # #345: the thesis comparison runs with ISTAT off (D6); if an arm had
    # turned it on the prompt would change too, and that must be said.
    ("dati ISTAT nel prompt", lambda rec: rec.provenance.istat),
)

#: Shared settings of the ISTAT pair: all except ISTAT, which is the variable.
_SETTINGS_WITHOUT_ISTAT = tuple(
    s for s in _SHARED_SETTINGS if s[0] != "dati ISTAT nel prompt"
)


def _single_mode(records: list[RunRecord]) -> str:
    """``mode`` of the arm if there is only one; ``""`` if the arm is mixed or empty."""
    modes = {rec.mode for rec in records}
    return next(iter(modes)) if len(modes) == 1 else ""


def _observed(
    records: list[RunRecord], get: Callable[[RunRecord], object]
) -> list[str]:
    """Distinct values (cited, sorted) of a setting within an arm."""
    return sorted({f"`{get(rec)}`" for rec in records})


def _configured_records(records: list[RunRecord]) -> list[RunRecord]:
    """Records that describe the REAL setting of the experiment (#163).

    Excludes ERROR and FALLBACK, the same statuses that ``compare_records`` keeps
    out of means and deltas. A fallback record does not report the configured
    temperature but the placeholder of ``_structured_response``
    (``Repro(temperature=0.0)``, written by construction when the LLM drops):
    reading it as a setting would make an arm that runs with a single
    temperature look mixed, and declare confounded a variable that nobody
    confounded.
    """
    return [rec for rec in records if rec.status not in _EXCLUDED_STATUSES]


def _setting_mismatch(
    arm_a: list[RunRecord],
    arm_b: list[RunRecord],
    *,
    label_a: str,
    label_b: str,
    settings: tuple[tuple[str, Callable[[RunRecord], object]], ...] = _SHARED_SETTINGS,
) -> str:
    """First of ``settings`` that the arms do NOT share.

    Returns a description with the values observed per arm, or ``""`` if
    the setting is the same on both sides. An arm with MIXED values
    counts as not shared: there is no single value to declare
    shared, so the comparison isolates nothing there either. It also holds for an
    arm whose records have ALL failed (no observable value): there is no
    setting to declare shared -- ``compare_records`` raises first,
    on that case, because no zone would remain to compare.

    ``settings`` defaults to :data:`_SHARED_SETTINGS` (ontology vs without
    ontology pair); the ISTAT pair (#345) passes :data:`_SETTINGS_WITHOUT_ISTAT`,
    because there ISTAT is the variable and not a setting to share.
    """
    for name, get in settings:
        seen_a = _observed(_configured_records(arm_a), get)
        seen_b = _observed(_configured_records(arm_b), get)
        if seen_a != seen_b or len(seen_a) != 1:
            return (
                f"{name} (`{label_a}`: {', '.join(seen_a)}; "
                f"`{label_b}`: {', '.join(seen_b)})"
            )
    return ""


def _paired_configured(
    arm_a: list[RunRecord], arm_b: list[RunRecord]
) -> list[tuple[str, RunRecord, RunRecord]]:
    """Cases ``(citta, zona)`` present in both arms among the records that
    describe the real setting (:func:`_configured_records`), sorted.

    They are the zones that ``compare_records`` really compares: a zone in
    ERROR/FALLBACK is already excluded from means and deltas, and a fallback did not
    generate prose (so not ``poi_nel_prompt`` either).
    """
    index_b = {(r.citta, r.zona): r for r in _configured_records(arm_b)}
    return [
        (f"{rec_a.citta}/{rec_a.zona}", rec_a, index_b[(rec_a.citta, rec_a.zona)])
        for rec_a in sorted(_configured_records(arm_a), key=lambda r: (r.citta, r.zona))
        if (rec_a.citta, rec_a.zona) in index_b
    ]


def _poi_nel_prompt_mismatch(
    arm_a: list[RunRecord],
    arm_b: list[RunRecord],
    *,
    label_a: str,
    label_b: str,
) -> str:
    """Cases in which POI parity in the prompt is NOT verified (#349).

    Twin of :func:`_setting_mismatch` for a setting that lives per case and
    not per arm: which points the prompt listed. The comparison VERIFIES it
    on the records instead of presuming it: for every compared case ``poi_nel_prompt``
    must be there in both records and the SETS must coincide (the order
    diverges by construction: the full one by relevance, the ablated in that of
    retrieval). Returns ``""`` if all is well, otherwise a description case by
    case: different sets, or records without the field, i.e. prior to #349.
    """
    problems: list[str] = []
    for case_key, rec_a, rec_b in _paired_configured(arm_a, arm_b):
        poi_a, poi_b = rec_a.poi_nel_prompt, rec_b.poi_nel_prompt
        if poi_a is None or poi_b is None:
            without_label = [
                f"`{label}`"
                for label, poi in ((label_a, poi_a), (label_b, poi_b))
                if poi is None
            ]
            problems.append(
                f"{case_key}: record senza `poi_nel_prompt` in "
                f"{' e '.join(without_label)}, "
                "cioè precedenti a #349, quindi la parità non è verificabile"
            )
        elif set(poi_a) != set(poi_b):
            problems.append(
                f"{case_key}: insiemi diversi (`{label_a}` {len(poi_a)} POI, "
                f"`{label_b}` {len(poi_b)} POI)"
            )
    return f"POI nel prompt ({'; '.join(problems)})" if problems else ""


def _poi_subset_note(arm_a: list[RunRecord], arm_b: list[RunRecord]) -> str:
    """Validity warning when the same POIs are a subset of the zone.

    Called only on verified parity (:func:`_poi_nel_prompt_mismatch` empty):
    lists the cases in which the points in the prompt are fewer than those of the zone
    (``n_poi``), with N out of M. ``""`` if no case is cut.
    """
    truncated = [
        f"{case_key} {len(rec_a.poi_nel_prompt)} su {rec_a.n_poi}"
        for case_key, rec_a, _rec_b in _paired_configured(arm_a, arm_b)
        if rec_a.poi_nel_prompt is not None and len(rec_a.poi_nel_prompt) < rec_a.n_poi
    ]
    if not truncated:
        return ""
    return (
        f"{POI_SUBSET_VALIDITY_HEAD} Zona per zona, i due bracci vedono N POI su "
        f"M ({'; '.join(truncated)}): {POI_SUBSET_VALIDITY_BODY}"
    )


def is_ontology_isolating_pair(arm_a: list[RunRecord], arm_b: list[RunRecord]) -> bool:
    """True if the modes of the two arms are the pair that manipulates the ontology
    (#236).

    Derived from the RECORDS (their ``mode``), not from the name of the experiments,
    like
    :func:`isolated_variable_note` which reuses it: on any other pair
    it returns ``False`` and nothing changes. A MIXED arm (more than one ``mode``) is
    not recognisable and counts as ``False``.

    The downstream verdict (``repeated_comparison``) also consumes it to exclude
    speed and cost from the tie-break: on this pair they are an effect of the
    prompt length (:data:`PROMPT_LENGTH_SIDE_EFFECT`), not a merit.
    Predicate EXPORTED instead of rechecked there: two recognitions of the
    same pair would diverge precisely on the case that matters.
    """
    modes = frozenset({_single_mode(arm_a), _single_mode(arm_b)})
    return modes == _ONTOLOGY_ISOLATING_MODES


def isolated_variable_note(
    arm_a: list[RunRecord],
    arm_b: list[RunRecord],
    *,
    label_a: str,
    label_b: str,
    quality_axes_vacuous: bool,
) -> str:
    """Declare the manipulated variable, if the modes of the two arms make it known.

    Derived from the RECORDS (their ``mode``), not from the name of the experiments: the
    comparison stays the generic primitive of #32, and on any other pair
    this function returns ``""`` leaving the report unchanged.

    That the arms share model, temperature, context format and seed is
    VERIFIED on the records (:func:`_setting_mismatch`, on :data:`_SHARED_SETTINGS`),
    not deduced from the modes: two runs with different generators change prompt and
    model together, and on that pair the function declares that the variable is NOT
    isolated instead of promising it. The check looks only at the records that
    describe the real setting (:func:`_configured_records`). The same holds
    for the POIs listed in the prompt (#349, :func:`_poi_nel_prompt_mismatch`): the
    full arm truncates by budget, and the variable is isolated only if, case
    by case, the two records save the same set. If it is the same but not
    the whole zone, the note adds the validity warning
    (:data:`POI_SUBSET_VALIDITY_HEAD`).

    The text says what changes and what does NOT change between the arms, and stops
    there: the reading of the quality deltas stays that of the :data:`PROXY_CAVEAT`
    (textual proxies, not human judgements). Declaring the variable serves precisely not
    to read a delta as a measure of the goodness of the analysis.

    ``quality_axes_vacuous`` (from the shared predicate
    :func:`has_vacuous_quality_axes`, the only one that decides whether to print the
    vacuity warning) replaces the claim about the meaning of the delta: the two blocks
    that open the report speak of the SAME axes, and with vacuity in play one
    said that the delta measures the effect of the ontology while the other, two lines
    below, that on those axes there is nothing to read in any direction. The
    design stays isolated -- that is verified on the records -- but its numbers do not.

    All branches close with :data:`PROMPT_LENGTH_SIDE_EFFECT`: that the ablated
    arm is faster and cheaper is a property of the two prompts, so it must be
    said both when the variable is isolated and when it is not, and the operational
    table is printed even when the quality axes are vacuous.
    """
    if not is_ontology_isolating_pair(arm_a, arm_b):
        return ""
    with_label, without_label = (
        (label_a, label_b) if _single_mode(arm_a) == "analyze" else (label_b, label_a)
    )
    mismatch = _setting_mismatch(
        arm_a, arm_b, label_a=label_a, label_b=label_b
    ) or _poi_nel_prompt_mismatch(arm_a, arm_b, label_a=label_a, label_b=label_b)
    if mismatch:
        return (
            f"{CONFOUNDED_VARIABLE_HEAD} Tra i due bracci cambia il PROMPT "
            f"(`{with_label}` riceve gli hazard che l'ontologia associa alle "
            f"classi dei punti, `{without_label}` solo nome e classe dei punti), "
            "ma non condividono "
            f"la stessa impostazione: {mismatch}. Cambia quindi più di una "
            "variabile e il delta su `grounding`/`hallucination` NON è "
            "attribuibile all'ancoraggio ontologico: per isolarlo, rilanciare i "
            f"due bracci con la stessa impostazione. {PROMPT_LENGTH_SIDE_EFFECT}"
        )
    what_changes = (
        f"{ISOLATED_VARIABLE_HEAD} I due bracci condividono modello, "
        "temperatura, formato del contesto, seed di campionamento, snapshot POI, "
        "gli stessi POI nel prompt (verificato sui record, zona per zona) e dati "
        "strutturati della risposta "
        "(`poi[]`, `risk_models`, confidence, quindi gli stessi ancoraggi su cui "
        "i proxy si calcolano). L'unica differenza è il PROMPT: sugli stessi "
        f"punti, `{with_label}` riceve gli hazard che l'ontologia associa alle loro "
        f"classi, `{without_label}` riceve solo nome e classe."
    )
    claim = VACUOUS_DELTA_CLAIM if quality_axes_vacuous else ISOLATED_DELTA_CLAIM
    subset = _poi_subset_note(arm_a, arm_b)
    parts = [
        what_changes,
        claim,
        *([subset] if subset else []),
        PROMPT_LENGTH_SIDE_EFFECT,
    ]
    return " ".join(parts)


def _arm_istat_values(records: list[RunRecord]) -> set[bool]:
    return {rec.provenance.istat for rec in records}


def is_istat_isolating_pair(arm_a: list[RunRecord], arm_b: list[RunRecord]) -> bool:
    """True for the ontology vs ontology + ISTAT pair (#345): two ``analyze``
    arms, each with a single value of ``istat``, different from each other."""
    if _single_mode(arm_a) != "analyze" or _single_mode(arm_b) != "analyze":
        return False
    a, b = _arm_istat_values(arm_a), _arm_istat_values(arm_b)
    return len(a) == 1 and len(b) == 1 and a != b


def istat_isolated_variable_note(
    arm_a: list[RunRecord], arm_b: list[RunRecord], *, label_a: str, label_b: str
) -> str:
    """Declaration of the variable for the ISTAT pair (#345); ``""`` elsewhere."""
    if not is_istat_isolating_pair(arm_a, arm_b):
        return ""
    with_label, without_label = (
        (label_a, label_b) if True in _arm_istat_values(arm_a) else (label_b, label_a)
    )
    mismatch = _setting_mismatch(
        arm_a, arm_b, label_a=label_a, label_b=label_b, settings=_SETTINGS_WITHOUT_ISTAT
    )
    if mismatch:
        return (
            f"{CONFOUNDED_VARIABLE_HEAD} Tra i due bracci cambia il blocco DATI ISTAT "
            f"nel prompt (`{with_label}` lo riceve, `{without_label}` no), "
            "ma non condividono la "
            f"stessa impostazione: {mismatch}. Cambia quindi piu' di una variabile: "
            "per isolare l'effetto dei dati ISTAT, rilanciare i due bracci con la "
            f"stessa impostazione. {ISTAT_BUDGET_SIDE_EFFECT}"
        )
    return (
        f"{ISTAT_ISOLATED_VARIABLE_HEAD} I due bracci condividono modello, "
        "temperatura, formato del contesto, seed di campionamento, budget di token "
        "della richiesta, snapshot POI e dati strutturati della risposta. "
        "L'unica differenza e' il blocco DATI "
        "ISTAT nel prompt, con le regole che lo accompagnano e il controllo delle "
        f"cifre: `{with_label}` lo riceve, `{without_label}` no. "
        "Nessun vincitore automatico (D12): "
        "`grounding`/`hallucination` servono solo a verificare che ISTAT non "
        "peggiori l'ancoraggio, le metriche ISTAT sono affiancate. "
        f"{ISTAT_BUDGET_SIDE_EFFECT}"
    )


def _quote_arms(labels: list[str]) -> tuple[str, str]:
    """(cited labels, agreed verb) for the vacuity messages."""
    quoted = " e ".join(f"`{label}`" for label in dict.fromkeys(labels))
    verbo = "non produce" if len(set(labels)) == 1 else "non producono"
    return quoted, verbo


def vacuity_subject(vacuous_arms: list[str], vacuous_zones: list[VacuousZone]) -> str:
    """Sentence that says WHO stayed mute and WHERE (whole arm or single zones).

    Prefers the per-arm formulation when the arm is mute everywhere: it is
    more informative than listing all its zones.
    """
    if vacuous_arms:
        quoted, verbo = _quote_arms(vacuous_arms)
        return f"Il braccio {quoted} {verbo} narrativa in nessuna run"
    zone_desc = ", ".join(
        f"{z.citta}/{z.zona} ({', '.join(f'`{a}`' for a in z.arms)})"
        for z in vacuous_zones
    )
    return f"Su alcune zone un braccio non ha prodotto narrativa — {zone_desc}"


def has_vacuous_quality_axes(
    vacuous_arms: list[str], vacuous_zones: list[VacuousZone]
) -> bool:
    """True if on this comparison ``grounding``/``hallucination`` cannot be read.

    SINGLE place where it is decided that the quality axes are vacuous (#231), and for
    that reason exported: it is consumed by the warning at the top of the report
    (:func:`to_markdown`), the isolated-variable declaration
    (:func:`isolated_variable_note`) and the withheld verdict of the repeated report.
    Three hand-written conditions could diverge, and they would diverge making the
    document say one thing and its negation on the same axes.

    ONE mute zone in an arm is enough: it enters the mean that the comparison prints
    and that the lexicographic criterion would use to decide.
    """
    return bool(vacuous_arms or vacuous_zones)


def _quality_verdict(
    vacuous_arms: list[str],
    vacuous_zones: list[VacuousZone],
    *,
    istat_pair: bool = False,
) -> QualityVerdict:
    """Build the :class:`QualityVerdict` of a comparison (#238).

    Called only once, inside :func:`compare_records`, so the field
    ends up on the :class:`Comparison` model itself: any present or
    future writer inherits it from ``to_json``/``model_dump`` without rebuilding it by
    hand (the duplication this function eliminates -- see the module
    ``repeated_comparison``, which previously had its own copy).

    ``istat_pair`` (#345): on the ontology vs ontology + ISTAT pair no
    winner is automatic (D12), even when no zone is vacuous -- it is a
    second reason to withhold the verdict, checked only if vacuity
    has not already withheld it.
    """
    withheld = has_vacuous_quality_axes(vacuous_arms, vacuous_zones)
    if not withheld and istat_pair:
        return QualityVerdict(
            applicable=False,
            vacuous_arms=list(vacuous_arms),
            vacuous_zones=list(vacuous_zones),
            reason=ISTAT_NO_WINNER_REASON,
        )
    return QualityVerdict(
        applicable=not withheld,
        vacuous_arms=list(vacuous_arms),
        vacuous_zones=list(vacuous_zones),
        reason=(
            "manca la narrativa su cui i proxy di qualità si pronunciano: "
            "metriche vacue (#231)"
            if withheld
            else ""
        ),
    )


def _vacuous_caveat(vacuous_arms: list[str], vacuous_zones: list[VacuousZone]) -> str:
    """Warning for the tables: why the quality axes cannot be read."""
    return (
        f"{VACUOUS_CAVEAT_HEAD} {vacuity_subject(vacuous_arms, vacuous_zones)}: "
        f"{VACUOUS_REASON}. Su questi assi il confronto NON è interpretabile in "
        f"nessuna direzione; {OPERATIONAL_AXES_NOTE}."
    )


def has_narrative(record: RunRecord) -> bool:
    """True if the record carries a non-empty narrative (#231).

    Single place where it is decided what counts as "has spoken". ``status=OK`` with
    empty narrative is reachable in production -- the client returns
    ``content or ""`` without raising, so the orchestrator answers
    ``fallback=False`` -- hence the status is NOT enough to recognise a mute zone.
    """
    return bool(record.narrativa.strip())


def _record_quality_vacuous(record: RunRecord) -> bool:
    """True if the record's quality metrics are vacuous (#240).

    Reads ``metrics.quality_vacuous`` when available: it is a superset of
    :func:`has_narrative`, because ``metrics.py::_grade`` falls into the vacuous branch
    both on absent narrative and on full narrative but without any POI with a name to
    cite (zone without POIs) -- the boundary that ``has_narrative`` alone declared it
    did not cover. On pre-#240 records (``quality_vacuous is None``, data not
    available) it falls back on ``has_narrative``: same behaviour as before
    the introduction of this field.
    """
    if record.metrics.quality_vacuous is not None:
        return record.metrics.quality_vacuous
    return not has_narrative(record)


def is_vacuous_arm(records: list[RunRecord]) -> bool:
    """True if NO record of the arm has gradable quality metrics (#231).

    An arm is vacuous by construction (``mode='baseline'``: no LLM), because it
    never produced text, or because the zones it covers had no
    anchor to cite (#240: ``_record_quality_vacuous``). In all cases there
    is no material on which the quality proxies can say anything. An arm
    that is silent on SOME zones and speaks on others is NOT vacuous: those zones are
    collected in ``Comparison.vacuous_zones`` and still withhold the verdict.

    An empty arm (no records) is not vacuous: it is not an arm.
    """
    return bool(records) and all(_record_quality_vacuous(rec) for rec in records)


def _to_values(m: Metrics) -> MetricValues:
    """Project a :class:`Metrics` (latency int) into :class:`MetricValues`."""
    return MetricValues(
        grounding=m.grounding,
        hallucination=m.hallucination,
        latency_ms=float(m.latency_ms),
        cost_usd=m.cost_usd,
    )


def _delta(a: Metrics, b: Metrics) -> MetricValues:
    """Per-metric delta A - B (can be negative)."""
    return MetricValues(
        grounding=a.grounding - b.grounding,
        hallucination=a.hallucination - b.hallucination,
        latency_ms=float(a.latency_ms - b.latency_ms),
        cost_usd=a.cost_usd - b.cost_usd,
    )


def _mean(values: list[MetricValues]) -> MetricValues:
    """Per-metric mean over a non-empty list of :class:`MetricValues`."""
    n = len(values)
    return MetricValues(
        grounding=float(sum(v.grounding for v in values) / n),
        hallucination=float(sum(v.hallucination for v in values) / n),
        latency_ms=float(sum(v.latency_ms for v in values) / n),
        cost_usd=float(sum(v.cost_usd for v in values) / n),
    )


def _index_by_zone(records: list[RunRecord]) -> dict[tuple[str, str], RunRecord]:
    """Index the records by ``(citta, zona)``; error on duplicate key."""
    index: dict[tuple[str, str], RunRecord] = {}
    for rec in records:
        key = (rec.citta, rec.zona)
        if key in index:
            raise ValueError(
                f"record duplicato per (citta, zona)={key} nel braccio "
                f"'{rec.experiment}': un braccio deve avere una run per zona"
            )
        index[key] = rec
    return index


def _reject_mixed_istat_versions(records: list[RunRecord], label: str) -> None:
    """Raise :class:`ValueError` if the arm mixes versions of the ISTAT
    metrics (#369).

    M1 of the records with ISTAT is graded on a text that depends on the version,
    so the arm's mean would mix different measures. As for the POIs in the
    prompt (#349), better to reject than to leave a mean that nobody tells apart
    downstream. Records without ISTAT metrics (no row in the prompt) do not count.
    """
    versions = {r.istat_metrics.versione for r in records if r.istat_metrics}
    if len(versions) > 1:
        raise ValueError(
            f"il braccio `{label}` mescola metriche ISTAT di versioni diverse "
            f"{sorted(versions)}: M1 dei record con ISTAT e' gradato su testi "
            "diversi a seconda della versione; rigirare il braccio con lo stesso "
            "codice"
        )


class NoUsableOutputError(ValueError):
    """No valid zone to compare: all records are ERROR/FALLBACK (#239).

    Subclass of :class:`ValueError` (whoever already caught ``ValueError``
    around :func:`compare_records` keeps working) but distinct from the
    other ``ValueError``s that the function raises: those signal a malformed
    INPUT (zones that do not match, duplicate records, diverging
    ``snapshot_id``) and must keep propagating as a traceback -- here instead
    the input is valid, simply no arm produced usable output
    on any zone (real scenario: LLM quota exhausted during an offline
    run, #232). The CLI callers (:func:`compare_experiments`,
    :func:`~crime_risk_analyzer.eval.repeated_comparison.build_repeated_report`)
    catch it to write a report that explains WHAT failed, per zone and
    per arm, instead of letting a bare traceback propagate -- never a verdict
    (see :func:`write_no_usable_output_report`).
    """

    def __init__(self, label_a: str, label_b: str, failed: list[FailedZone]) -> None:
        self.label_a = label_a
        self.label_b = label_b
        self.failed = failed
        super().__init__(
            "nessuna zona valida da confrontare (tutte in ERROR/FALLBACK, "
            "nessun braccio ha prodotto output utilizzabile): "
            f"{[(f.citta, f.zona) for f in failed]}"
        )


def compare_records(
    arm_a: list[RunRecord],
    arm_b: list[RunRecord],
    *,
    label_a: str,
    label_b: str,
    anchoring_records: tuple[list[RunRecord], list[RunRecord]] | None = None,
) -> Comparison:
    """Join two arms by ``(citta, zona)`` and compute the A - B deltas.

    ``anchoring_records`` (#359): records from which to compute the section
    on risk anchoring, if different from ``arm_a``/``arm_b``. The K-repetition report
    passes the repetitions, because the mean-record carries neither the
    narrative of each repetition nor the ``risk_models``.

    The zones in which an arm is in ``ERROR`` (zeroed metrics) or ``FALLBACK``
    (empty narrative -> non-quality metrics) are excluded from compared zones and
    means, and collected in ``Comparison.failed`` (#163). Only ``OK`` stays included.

    The zones on which an arm produced no narrative are marked in
    ``Comparison.vacuous_zones``, and an arm mute on ALL the zones also in
    ``Comparison.vacuous_arms`` (#231): there the quality metrics are vacuous, not
    a merit, and downstream no verdict must be issued on those axes. It is not an
    error and excludes no zones: the operational measures (latency, cost) stay
    valid, but no comparison is declared on them (#237) -- they must be
    read directly in the tables.

    Raises :class:`ValueError` if: an arm has duplicate records for a zone;
    the two arms cover different zones (iso-input violated); a paired zone has
    diverging ``snapshot_id`` between the arms (iso-input at record level); an
    arm mixes ISTAT metrics of different versions (#369, M1 graded on different
    texts: :func:`_reject_mixed_istat_versions`).
    Raises :class:`NoUsableOutputError` (subclass of ``ValueError``, #239) if
    no valid zone remains to compare -- the input is valid, it is the outcome that
    is degenerate.
    """
    index_a = _index_by_zone(arm_a)
    index_b = _index_by_zone(arm_b)
    _reject_mixed_istat_versions(arm_a, label_a)
    _reject_mixed_istat_versions(arm_b, label_b)
    keys_a = set(index_a)
    keys_b = set(index_b)
    if keys_a != keys_b:
        only_a = sorted(keys_a - keys_b)
        only_b = sorted(keys_b - keys_a)
        raise ValueError(
            "le zone dei due bracci non coincidono (confronto iso-input "
            f"violato): solo in A={only_a}, solo in B={only_b}"
        )
    if not keys_a:
        raise ValueError("nessuna zona da confrontare: entrambi i bracci sono vuoti")
    zones: list[ZoneComparison] = []
    failed: list[FailedZone] = []
    vacuous_zones: list[VacuousZone] = []
    istat_zone: list[IstatZoneMetrics] = []
    for key in sorted(keys_a):
        rec_a = index_a[key]
        rec_b = index_b[key]
        # Iso-input at record level: the same (citta, zona) must cite the
        # same snapshot_id in both arms. Defence in depth (records
        # tampered with by hand, or a future snapshot_id derived from the POI content).
        # It does NOT catch a --force: that overwrites the snapshot file but leaves
        # the id unchanged (derived only from (citta, zona)), so a divergence
        # of CONTENT between the arms would not emerge here.
        sid_a = rec_a.provenance.snapshot_id
        sid_b = rec_b.provenance.snapshot_id
        if sid_a != sid_b:
            raise ValueError(
                f"snapshot_id divergente per (citta, zona)={key}: "
                f"A={sid_a!r} B={sid_b!r} (confronto iso-input violato)"
            )
        # ERROR (metrics zeroed by the harness) and FALLBACK (empty narrative ->
        # metrics not representative of quality) are excluded, not averaged
        # (#163). Reported among the failed zones: traced exclusion, not mute.
        if rec_a.status in _EXCLUDED_STATUSES or rec_b.status in _EXCLUDED_STATUSES:
            failed.append(
                FailedZone(
                    citta=rec_a.citta,
                    zona=rec_a.zona,
                    status_a=rec_a.status.value,
                    status_b=rec_b.status.value,
                )
            )
            continue
        # Mute zone (#231): status OK but quality metrics not gradable for an
        # arm -- no text produced, or full narrative on a zone
        # without POIs/anchors to cite (#240). The zone stays compared (the operational
        # measures hold), but its quality metrics are vacuous and
        # cannot support a verdict.
        silent = [
            label
            for label, rec in ((label_a, rec_a), (label_b, rec_b))
            if _record_quality_vacuous(rec)
        ]
        if silent:
            vacuous_zones.append(
                VacuousZone(citta=rec_a.citta, zona=rec_a.zona, arms=silent)
            )
        zones.append(
            ZoneComparison(
                citta=rec_a.citta,
                zona=rec_a.zona,
                a=rec_a.metrics,
                b=rec_b.metrics,
                delta=_delta(rec_a.metrics, rec_b.metrics),
            )
        )
        if rec_a.istat_metrics is not None or rec_b.istat_metrics is not None:
            istat_zone.append(
                IstatZoneMetrics(
                    citta=rec_a.citta,
                    zona=rec_a.zona,
                    a=rec_a.istat_metrics,
                    b=rec_b.istat_metrics,
                )
            )
    if not zones:
        raise NoUsableOutputError(label_a, label_b, failed)
    vacuous = [
        label
        for label, arm in ((label_a, arm_a), (label_b, arm_b))
        if is_vacuous_arm(arm)
    ]
    source_a, source_b = anchoring_records or (arm_a, arm_b)
    return Comparison(
        label_a=label_a,
        label_b=label_b,
        zones=zones,
        mean_a=_mean([_to_values(z.a) for z in zones]),
        mean_b=_mean([_to_values(z.b) for z in zones]),
        mean_delta=_mean([z.delta for z in zones]),
        failed=failed,
        vacuous_arms=vacuous,
        vacuous_zones=vacuous_zones,
        isolated_variable=(
            isolated_variable_note(
                arm_a,
                arm_b,
                label_a=label_a,
                label_b=label_b,
                # The note is computed HERE, not in the renderers, because vacuity is
                # known only after the join: so the field (which also ends up in the
                # JSON) and the Markdown warning cannot tell two different
                # stories.
                quality_axes_vacuous=has_vacuous_quality_axes(vacuous, vacuous_zones),
            )
            or istat_isolated_variable_note(
                arm_a, arm_b, label_a=label_a, label_b=label_b
            )
        ),
        quality_verdict=_quality_verdict(
            vacuous, vacuous_zones, istat_pair=is_istat_isolating_pair(arm_a, arm_b)
        ),
        istat_metrics=istat_zone,
        avviso_versioni_istat=_istat_versions_warning(istat_zone, label_a, label_b),
        avviso_versioni_m1=_m1_versions_warning(
            source_a,
            source_b,
            {(z.citta, z.zona) for z in zones},
            label_a,
            label_b,
        ),
        ancoraggio_rischi=_risk_anchoring_section(
            source_a,
            source_b,
            [(z.citta, z.zona) for z in zones],
            label_a=label_a,
            label_b=label_b,
        ),
    )


#: First version of the ISTAT metrics whose records save the sentences excluded from
#: M1 (#369): from there the text that M1 measures can be rebuilt from the record
#: (#377).
_ISTAT_VERSION_RECONSTRUCTIBLE = 4


def _record_anchoring(record: RunRecord) -> RiskAnchoring | None:
    """Risk anchoring of a record, from the saved data alone (#359).

    The POI names come from ``risk_models[].poi``: ``risk_models`` has one entry
    for every POI, even outside the ontology (``risks=[]``), in the same order as
    ``resp.poi`` (orchestrator invariant), so they are the same names that
    M1 uses.

    Without ISTAT data ``RunRecord.narrativa`` is measured. With ISTAT data M1 grades
    the raw text without the excluded ISTAT sentences (#369): the same text is measured,
    rebuilt from ``narrativa_grezza`` and ``frasi_escluse_m1`` (#377). It must be
    called only on records from which the text can be rebuilt
    (:func:`_istat_not_reconstructible` false).

    Raises:
        InconsistentExcludedSentencesError: the excluded sentences of the record are not
            among the sentences of the raw text.
    """
    with_istat = record.istat_metrics is not None
    return risk_anchoring(
        record.narrativa_grezza if with_istat else record.narrativa,
        mode=record.mode,
        poi_names=[m.poi for m in record.risk_models],
        risk_models=record.risk_models,
        excluded_sentences=(record.frasi_escluse_m1 or []) if with_istat else [],
    )


def _istat_not_reconstructible(record: RunRecord) -> bool:
    """True if the record has ISTAT data but the text measured by M1 cannot
    be rebuilt (#359, #377).

    ``istat_metrics`` is written by the harness exactly when the response
    carries the ISTAT figures check, i.e. when M1 grades the raw text without
    the excluded ISTAT sentences instead of the narrative: it is the same signal,
    more precise than ``provenance.istat`` (ISTAT requested but perhaps without data
    in the prompt). The text can be rebuilt from version 4 of the ISTAT metrics
    (before, M1 excluded other sentences) and only if the record has both the raw text
    and the excluded sentences.
    """
    m = record.istat_metrics
    if m is None:
        return False
    return (
        m.versione < _ISTAT_VERSION_RECONSTRUCTIBLE
        or record.narrativa_grezza is None
        or record.frasi_escluse_m1 is None
    )


def _share(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def _mean_or_none(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _zone_anchoring(records: list[RunRecord]) -> RiskAnchoringArm:
    """Aggregate the gradable narratives of the ``OK`` runs of a zone (#359)."""
    ok = [r for r in records if r.status is RunStatus.OK]
    included: list[RunRecord] = []
    computed: list[RiskAnchoring | None] = []
    for r in ok:
        if _istat_not_reconstructible(r):
            continue
        try:
            computed.append(_record_anchoring(r))
        except InconsistentExcludedSentencesError as exc:
            # An inconsistent record stays out like the non-reconstructible ones: it
            # must not make the whole report fail.
            logger.warning("ancoraggio ai rischi: run %s esclusa: %s", r.run_id, exc)
            continue
        included.append(r)
    istat_included = [r for r in included if r.istat_metrics is not None]
    graded = [r for r in computed if r is not None]
    conforming = [r.ancoraggio_rischi for r in graded if r.conforme]
    measured = sum(r.frasi_misurate for r in graded)
    risk = sum(r.frasi_ancorate_rischio for r in graded)
    poi_only = sum(r.frasi_ancorate_solo_poi for r in graded)
    poi_and_risk = sum(r.frasi_ancorate_poi_e_rischio for r in graded)
    return RiskAnchoringArm(
        narrative_gradabili=len(graded),
        non_conformi=sum(1 for r in graded if not r.conforme),
        frasi_misurate=measured,
        frasi_ancorate_rischio=risk,
        frasi_ancorate_solo_poi=poi_only,
        frasi_ancorate_poi_e_rischio=poi_and_risk,
        frasi_misurate_media=_mean_or_none([float(r.frasi_misurate) for r in graded]),
        quota_rischio=_share(risk, measured),
        quota_solo_poi=_share(poi_only, measured),
        ancoraggio_rischi=_mean_or_none([r.ancoraggio_rischi for r in graded]),
        ancoraggio_rischi_conformi=_mean_or_none(conforming),
        run_istat_escluse=len(ok) - len(included),
        run_istat_incluse=len(istat_included),
        frasi_istat_escluse=sum(len(r.frasi_escluse_m1 or []) for r in istat_included),
    )


def _arm_anchoring(zones: list[RiskAnchoringArm]) -> RiskAnchoringArm:
    """Whole arm: sums of the totals, means of the gradable zones (#359)."""
    measured = sum(z.frasi_misurate for z in zones)
    risk = sum(z.frasi_ancorate_rischio for z in zones)
    poi_only = sum(z.frasi_ancorate_solo_poi for z in zones)
    poi_and_risk = sum(z.frasi_ancorate_poi_e_rischio for z in zones)
    sentence_means = [
        z.frasi_misurate_media for z in zones if z.frasi_misurate_media is not None
    ]
    anchoring_means = [
        z.ancoraggio_rischi for z in zones if z.ancoraggio_rischi is not None
    ]
    conforming_means = [
        z.ancoraggio_rischi_conformi
        for z in zones
        if z.ancoraggio_rischi_conformi is not None
    ]
    return RiskAnchoringArm(
        narrative_gradabili=sum(z.narrative_gradabili for z in zones),
        non_conformi=sum(z.non_conformi for z in zones),
        frasi_misurate=measured,
        frasi_ancorate_rischio=risk,
        frasi_ancorate_solo_poi=poi_only,
        frasi_ancorate_poi_e_rischio=poi_and_risk,
        frasi_misurate_media=_mean_or_none(sentence_means),
        quota_rischio=_share(risk, measured),
        quota_solo_poi=_share(poi_only, measured),
        ancoraggio_rischi=_mean_or_none(anchoring_means),
        ancoraggio_rischi_conformi=_mean_or_none(conforming_means),
        run_istat_escluse=sum(z.run_istat_escluse for z in zones),
        run_istat_incluse=sum(z.run_istat_incluse for z in zones),
        frasi_istat_escluse=sum(z.frasi_istat_escluse for z in zones),
    )


def poi_only_prevails(arm: RiskAnchoringArm) -> bool:
    """True if in the arm the POI-only sentences exceed those with POI and risk.

    The anchored sentences of M1 are only ``solo_poi`` and ``poi_e_rischio`` (#408): the
    comparison is between these two. ``frasi_ancorate_rischio`` is not suitable, because
    it includes the risk sentences without a point, which M1 does not count as anchored.
    Strict comparison (#359): on a tie the pointer does not appear.
    """
    return arm.frasi_ancorate_solo_poi > arm.frasi_ancorate_poi_e_rischio


def _risk_anchoring_section(
    arm_a: list[RunRecord],
    arm_b: list[RunRecord],
    keys: list[tuple[str, str]],
    *,
    label_a: str,
    label_b: str,
) -> RiskAnchoringSection | None:
    """Section on risk anchoring, on the compared zones only (#359)."""

    def of_zone(arm: list[RunRecord], key: tuple[str, str]) -> RiskAnchoringArm:
        return _zone_anchoring([r for r in arm if (r.citta, r.zona) == key])

    zones = [
        RiskAnchoringZone(
            citta=key[0], zona=key[1], a=of_zone(arm_a, key), b=of_zone(arm_b, key)
        )
        for key in keys
    ]
    total_a = _arm_anchoring([z.a for z in zones])
    total_b = _arm_anchoring([z.b for z in zones])
    if not any(
        t.narrative_gradabili or t.run_istat_escluse for t in (total_a, total_b)
    ):
        return None
    return RiskAnchoringSection(
        zones=zones,
        a=total_a,
        b=total_b,
        solo_poi_prevale=[
            label
            for label, arm in ((label_a, total_a), (label_b, total_b))
            if poi_only_prevails(arm)
        ],
    )


def _columns(
    label_a: str, label_b: str, specs: tuple[_MetricSpec, ...] = _METRIC_SPECS
) -> list[str]:
    """Headers: for every metric in ``specs``, value A, value B, delta.

    ``specs`` defaults to the full set (main table); passing
    :data:`_OPERATIONAL_SPECS` generates only the cost/latency columns (#33).
    """
    cols = ["citta", "zona"]
    for spec in specs:
        cols.extend(
            [f"{spec.name}_{label_a}", f"{spec.name}_{label_b}", f"{spec.name}_delta"]
        )
    return cols


def _failed_columns(label_a: str, label_b: str) -> list[str]:
    """Headers of the excluded-zones section (status per arm)."""
    return ["citta", "zona", f"status_{label_a}", f"status_{label_b}"]


def _failed_row(failed: FailedZone) -> list[str]:
    """Row of an excluded zone; aligned with :func:`_failed_columns`."""
    return [failed.citta, failed.zona, failed.status_a, failed.status_b]


def _fmt_row(
    citta: str,
    zona: str,
    a: MetricValues,
    b: MetricValues,
    d: MetricValues,
    specs: tuple[_MetricSpec, ...] = _METRIC_SPECS,
) -> list[str]:
    """A formatted row; the deltas carry the explicit sign (+/-).

    Derived from the same ``specs`` as :func:`_columns`: headers and rows cannot
    misalign (a single source of truth), for any subset.
    """
    cells = [citta, zona]
    for spec in specs:
        cells.append(spec.value_fmt.format(spec.get(a)))
        cells.append(spec.value_fmt.format(spec.get(b)))
        cells.append(spec.delta_fmt.format(spec.get(d)))
    return cells


def _rows(
    comparison: Comparison, specs: tuple[_MetricSpec, ...] = _METRIC_SPECS
) -> list[list[str]]:
    """Per-zone rows (valid zones only) followed by the aggregate row (mean)."""
    rows = [
        _fmt_row(z.citta, z.zona, _to_values(z.a), _to_values(z.b), z.delta, specs)
        for z in comparison.zones
    ]
    rows.append(
        _fmt_row(
            _MEAN_LABEL,
            "",
            comparison.mean_a,
            comparison.mean_b,
            comparison.mean_delta,
            specs,
        )
    )
    return rows


def to_csv(comparison: Comparison) -> str:
    """Serialize the comparison to CSV: RECTANGULAR table (valid zones + MEAN).

    The excluded zones (an arm in ERROR) do NOT enter the CSV, which stays a
    uniform table loadable by pandas/``csv.reader`` without ragged rows; they are
    reported in the Markdown report (:func:`to_markdown`) and stay accessible in
    ``Comparison.failed``: no failure disappears silently.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_columns(comparison.label_a, comparison.label_b))
    for row in _rows(comparison):
        writer.writerow(row)
    return buf.getvalue()


def _markdown_table(cols: list[str], rows: list[list[str]]) -> list[str]:
    """Markdown rows of a table (header + separator + data)."""
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


class NoUsableOutputReport(BaseModel):
    """JSON shape of ``NoUsableOutputError``: ``failed``, never a verdict (#239)."""

    label_a: str
    label_b: str
    failed: list[FailedZone]
    winner: None = None
    quality_verdict_applicable: bool = False


def no_usable_output_markdown(exc: NoUsableOutputError) -> str:
    """Markdown report for a comparison with no usable zone (#239).

    No metrics table, no verdict: only the excluded-zones section
    (same format as the homonymous section of :func:`to_markdown`), so
    whoever reads sees at once which zone and which arm failed and with which
    status, instead of a traceback.
    """
    fcols = _failed_columns(exc.label_a, exc.label_b)
    lines = [
        "# Nessun output utilizzabile",
        "",
        "> ⚠️ **Nessun verdetto.** Ogni zona è esclusa (ogni braccio è in "
        "`ERROR` o `FALLBACK` su ogni zona): non resta nulla da mediare o "
        "confrontare. Tabelle di metriche e verdetto non sono emessi.",
        "",
        "### Zone escluse dal confronto (run in errore)",
    ]
    lines.extend(_markdown_table(fcols, [_failed_row(fz) for fz in exc.failed]))
    return "\n".join(lines) + "\n"


def no_usable_output_csv(exc: NoUsableOutputError) -> str:
    """CSV of the excluded zones: same schema as the section of :func:`to_csv`."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_failed_columns(exc.label_a, exc.label_b))
    for fz in exc.failed:
        writer.writerow(_failed_row(fz))
    return buf.getvalue()


def no_usable_output_json(exc: NoUsableOutputError) -> str:
    """Structured JSON of the failure: ``failed``, ``winner`` always ``None``."""
    return NoUsableOutputReport(
        label_a=exc.label_a, label_b=exc.label_b, failed=exc.failed
    ).model_dump_json(indent=2)


def write_no_usable_output_report(
    results_dir: Path, exc: NoUsableOutputError, stem: str, *, force: bool = False
) -> tuple[Path, Path, Path]:
    """Write ``results/<stem>.{csv,md,json}`` for a comparison with no outcome (#239).

    Same naming convention as :func:`write_comparison`: the CLI callers
    (:func:`compare_experiments`,
    :func:`~crime_risk_analyzer.eval.repeated_comparison.build_repeated_report`)
    give back to their own caller only the two paths of their own
    existing contract, ignoring the third -- neither breaks its own return
    signature for this degenerate case.
    """
    csv_path = results_dir / f"{stem}.csv"
    md_path = results_dir / f"{stem}.md"
    json_path = results_dir / f"{stem}.json"
    guard_no_overwrite([csv_path, md_path, json_path], force)
    csv_path.write_text(no_usable_output_csv(exc), encoding="utf-8", newline="")
    md_path.write_text(no_usable_output_markdown(exc), encoding="utf-8")
    json_path.write_text(no_usable_output_json(exc), encoding="utf-8")
    return csv_path, md_path, json_path


def operational_markdown(comparison: Comparison) -> str:
    """Cost/latency table (operational metrics), SEPARATE from quality (#33).

    Re-presents only the DIRECT measures (``latency_ms``, ``cost_usd``) side by side
    A/B + delta, per zone and on average, reusing the join+delta already in
    ``comparison`` (no recomputation). The quality metrics stay in the main
    table and are textual proxies: see :data:`PROXY_CAVEAT`.
    """
    cols = _columns(comparison.label_a, comparison.label_b, _OPERATIONAL_SPECS)
    lines = ["### Costo e latenza (metriche operative)", ""]
    lines.extend(_markdown_table(cols, _rows(comparison, _OPERATIONAL_SPECS)))
    return "\n".join(lines) + "\n"


#: Columns of the ISTAT table, one cell each in :func:`_istat_cells`.
_ISTAT_COLUMNS = (
    "versione",
    "cifre ISTAT scritte",
    "voci citate/fornite",
    "frasi ISTAT con luogo",
    "luogo ereditato",
    "frasi scartabili",
    "direzioni coerenti",
    "confronti coerenti",
    "corrispondenze non dichiarate",
    "numeri in lettere",
    "codici voce",
    "frasi escluse da M1",
)


def _istat_cells(m: IstatMetrics | None) -> list[str]:
    """Cells of an arm; on version 1 records (#345) the fields born with
    version 2 (#365) did not exist and count as ``n/d``, like the sentences excluded
    from M1 (#369) before version 4."""
    if m is None:
        return ["-"] * len(_ISTAT_COLUMNS)
    v1 = m.versione < 2
    return [
        str(m.versione),
        "n/d" if v1 else str(m.cifre_istat),
        f"{m.voci_citate}/{m.voci_fornite}",
        f"{m.frasi_istat_con_luogo}/{m.frasi_istat}",
        "n/d" if v1 else str(m.frasi_istat_con_luogo_ereditato),
        str(m.frasi_scartabili),
        f"{m.direzioni_coerenti}/{m.direzioni_totali}",
        "n/d" if v1 else f"{m.confronti_coerenti}/{m.confronti_totali}",
        str(m.corrispondenze_non_dichiarate),
        str(m.numeri_in_lettere),
        "n/d" if v1 else str(m.codici_voce),
        "n/d" if m.versione < 4 else str(m.frasi_escluse_m1),
    ]


def _istat_versions_warning(
    zone: list[IstatZoneMetrics], label_a: str, label_b: str
) -> str:
    """Warning if the two arms have ISTAT metrics of different versions (#369, D2).

    Within an arm mixed versions are rejected
    (:func:`_reject_mixed_istat_versions`); between two arms with ISTAT (e.g. two
    models, or an old run against a new one) the comparison remains possible, but
    M1 of the two arms is graded with different rules and the report says so before
    the tables. ``""`` if the versions coincide or an arm has no ISTAT.
    """
    versions_a = {z.a.versione for z in zone if z.a}
    versions_b = {z.b.versione for z in zone if z.b}
    if not versions_a or not versions_b or versions_a == versions_b:
        return ""
    return (
        f"{ISTAT_VERSIONS_DIFFER_HEAD} `{label_a}`: versione "
        f"{', '.join(map(str, sorted(versions_a)))}; `{label_b}`: "
        f"versione {', '.join(map(str, sorted(versions_b)))}. Nei due bracci "
        "`grounding`/`hallucination` escludono le frasi ISTAT con regole diverse: "
        "il delta su quegli assi mescola l'effetto dei bracci con quello della "
        "regola. Per un confronto pulito, rigirare i bracci con lo stesso codice."
    )


def _m1_versions(
    records: list[RunRecord], zone: set[tuple[str, str]]
) -> set[int | None]:
    """M1 versions of the records that really enter the comparison (#408).

    Only the zones actually compared count (not those in ``failed``) and,
    among their records, not those excluded by status nor those with vacuous
    quality: on these ``grounding``/``hallucination`` do not depend on the version.
    """
    return {
        r.metrics.versione
        for r in records
        if (r.citta, r.zona) in zone
        and r.status not in _EXCLUDED_STATUSES
        and r.metrics.quality_vacuous is not True
    }


def _m1_versions_text(versions: set[int | None]) -> str:
    """Sorted versions, ``n/d`` for the records that do not record it (#408)."""
    note = sorted(v for v in versions if v is not None)
    return ", ".join([*map(str, note), *(["n/d"] if None in versions else [])])


def _m1_versions_warning(
    arm_a: list[RunRecord],
    arm_b: list[RunRecord],
    zone: set[tuple[str, str]],
    label_a: str,
    label_b: str,
) -> str:
    """Warning if M1 has different versions, between the arms or within one (#408).

    Like :func:`_istat_versions_warning` it signals without rejecting: grounding and
    hallucination are graded with different semantics, and the report says so before
    the tables. ``""`` if all records share the same version
    (even ``n/d``, i.e. all prior to the field).
    """
    versions_a = _m1_versions(arm_a, zone)
    versions_b = _m1_versions(arm_b, zone)
    all_versions = versions_a | versions_b
    if len(all_versions) <= 1:
        return ""
    if None in all_versions:
        tail = (
            "Con n/d (record scritto prima che la versione fosse registrata) non "
            "si sa se le versioni differiscano davvero: puo' essere un falso "
            "allarme. Se differiscono, il delta su `grounding`/`hallucination` "
            "mescola l'effetto dei bracci con quello della metrica."
        )
    else:
        tail = (
            "`grounding`/`hallucination` sono gradati con semantiche diverse: il "
            "delta su quegli assi mescola l'effetto dei bracci con quello della "
            "metrica. Per un confronto pulito, rigirare i bracci con lo stesso "
            "codice."
        )
    return (
        f"{M1_VERSIONS_DIFFER_HEAD} `{label_a}`: versione "
        f"{_m1_versions_text(versions_a)}; `{label_b}`: versione "
        f"{_m1_versions_text(versions_b)}. {tail}"
    )


def _arm_excluded_sentences(metrics: list[IstatMetrics]) -> str:
    """Total of the sentences excluded from M1 in the zones of an arm (#369) and, among
    these, of those without an ISTAT item of the prompt (#378)."""
    if any(m.versione < 4 for m in metrics):
        return "n/d (record precedenti alla versione 4)"
    excluded = f"{sum(m.frasi_escluse_m1 for m in metrics)} frasi escluse"
    without_item = [m.frasi_escluse_senza_voce for m in metrics]
    if any(n is None for n in without_item):
        return (
            f"{excluded}, di cui n/d senza voce ISTAT del prompt (record senza il "
            "conteggio)"
        )
    total = sum(n for n in without_item if n is not None)
    return f"{excluded}, di cui {total} senza voce ISTAT del prompt"


def istat_markdown(comparison: Comparison) -> str:
    """Table of the ISTAT metrics side by side (#345): no delta, no
    winner. Below, the note on the reduced text on which M1 is graded (#369) with
    the total of the excluded sentences per arm."""
    names = _ISTAT_COLUMNS
    cols = [
        "citta",
        "zona",
        *(f"{n} ({comparison.label_a})" for n in names),
        *(f"{n} ({comparison.label_b})" for n in names),
    ]
    rows = [
        [z.citta, z.zona, *_istat_cells(z.a), *_istat_cells(z.b)]
        for z in comparison.istat_metrics
    ]
    lines = ["### Metriche ISTAT (affiancate, nessun vincitore)", ""]
    lines.extend(_markdown_table(cols, rows))
    arms = [
        (label, [m for m in metrics if m is not None])
        for label, metrics in (
            (comparison.label_a, [z.a for z in comparison.istat_metrics]),
            (comparison.label_b, [z.b for z in comparison.istat_metrics]),
        )
    ]
    totals = [
        f"`{label}`: {_arm_excluded_sentences(metrics)}"
        for label, metrics in arms
        if metrics
    ]
    lines += [
        "",
        ISTAT_M1_REDUCED_TEXT,
        ">",
        f"> Frasi escluse da M1 — {'; '.join(totals)}.",
        "",
        ISTAT_EXCLUDED_WITHOUT_ITEM_TEXT,
    ]
    return "\n".join(lines) + "\n"


def _pct(value: float | None) -> str:
    return "n/d" if value is None else f"{value * 100:.1f}%"


def _num(value: float | None, fmt: str) -> str:
    return "n/d" if value is None else fmt.format(value)


def _anchoring_row(
    citta: str, zona: str, label: str, arm: RiskAnchoringArm
) -> list[str]:
    return [
        citta,
        zona,
        label,
        str(arm.narrative_gradabili),
        _num(arm.frasi_misurate_media, "{:.1f}"),
        _pct(arm.quota_rischio),
        _pct(arm.quota_solo_poi),
        _num(arm.ancoraggio_rischi, "{:.3f}"),
        _num(arm.ancoraggio_rischi_conformi, "{:.3f}"),
        str(arm.non_conformi),
    ]


def risk_anchoring_markdown(comparison: Comparison) -> str:
    """ "Risk anchoring (exploratory)" section (#359); empty if absent."""
    section = comparison.ancoraggio_rischi
    if section is None:
        return ""
    cols = [
        "citta",
        "zona",
        "braccio",
        "narrative",
        "frasi misurate (media)",
        "% da rischio",
        "% solo POI",
        "ancoraggio_rischi",
        "ancoraggio_rischi solo conformi",
        "non conformi al formato",
    ]
    la, lb = comparison.label_a, comparison.label_b
    rows: list[list[str]] = []
    for z in section.zones:
        rows.append(_anchoring_row(z.citta, z.zona, la, z.a))
        rows.append(_anchoring_row(z.citta, z.zona, lb, z.b))
    rows.append(_anchoring_row(_MEAN_LABEL, "", la, section.a))
    rows.append(_anchoring_row(_MEAN_LABEL, "", lb, section.b))
    lines = [RISK_ANCHORING_HEAD, ""]
    lines.extend(_markdown_table(cols, rows))
    lines.append("")
    lines.append(
        f"> Frasi del braccio — `{la}`: {section.a.frasi_misurate} misurate, "
        f"{section.a.frasi_ancorate_rischio} da rischio, "
        f"{section.a.frasi_ancorate_solo_poi} solo POI, "
        f"{section.a.frasi_ancorate_poi_e_rischio} POI e rischio; `{lb}`: "
        f"{section.b.frasi_misurate} misurate, {section.b.frasi_ancorate_rischio} da "
        f"rischio, {section.b.frasi_ancorate_solo_poi} solo POI, "
        f"{section.b.frasi_ancorate_poi_e_rischio} POI e rischio."
    )
    included_runs = [
        f"`{label}`: {arm.run_istat_incluse} run, {arm.frasi_istat_escluse} "
        + (
            "frase ISTAT esclusa"
            if arm.frasi_istat_escluse == 1
            else "frasi ISTAT escluse"
        )
        for label, arm in ((la, section.a), (lb, section.b))
        if arm.run_istat_incluse
    ]
    if included_runs:
        lines += [
            "",
            RISK_ANCHORING_ISTAT_INCLUDED,
            ">",
            f"> Run con dati ISTAT nella sezione — {'; '.join(included_runs)}.",
        ]
    excluded = [
        f"`{label}`: {arm.run_istat_escluse}"
        for label, arm in ((la, section.a), (lb, section.b))
        if arm.run_istat_escluse
    ]
    if excluded:
        lines.append("")
        lines.append(
            f"> {RISK_ANCHORING_ISTAT_EXCLUDED} (run escluse — {', '.join(excluded)})."
        )
    lines.append("")
    lines.append(RISK_ANCHORING_NOTE)
    return "\n".join(lines) + "\n"


def risk_anchoring_pointer(comparison: Comparison) -> str:
    """Lines that point to the section (#359), one per arm; empty if none.

    One line for every arm in which the sentences anchored only by POI names are
    more than those that name a point and a risk (:func:`poi_only_prevails`).
    """
    section = comparison.ancoraggio_rischi
    if section is None:
        return ""
    title = RISK_ANCHORING_HEAD.removeprefix("### ")
    return "\n\n".join(
        f"> Per «{label}» le frasi ancorate solo da un nome di punto superano "
        f"quelle che nominano un punto e un rischio: vedi la sezione «{title}»."
        for label in section.solo_poi_prevale
    )


def to_markdown(comparison: Comparison, *, anchoring_pointer: bool = True) -> str:
    """Markdown report of the comparison.

    Composes: the isolated-variable declaration when derivable (#236),
    main table (4 metrics side by side A/B + delta, per zone + mean),
    separate cost/latency table (#33), the warning on vacuous arms when
    present (#231), methodological caveat on the textual proxies, and -- if present --
    the section of the excluded zones (runs in error).

    The section on risk anchoring (#359) comes before the caveat; the pointer
    (:func:`risk_anchoring_pointer`) follows the main table.
    ``anchoring_pointer=False`` omits it: the K-repetition report puts it
    next to the verdict.
    """
    cols = _columns(comparison.label_a, comparison.label_b)
    lines: list[str] = []
    # Isolated variable (#236): opens the report for the same reason as the
    # vacuity warning -- it says how the deltas are to be read, so it must be read
    # before them.
    if comparison.isolated_variable:
        lines.append(comparison.isolated_variable)
        lines.append("")
    # Different ISTAT versions between the arms (#369): changes the text that M1 grades.
    if comparison.avviso_versioni_istat:
        lines.append(comparison.avviso_versioni_istat)
        lines.append("")
    # Different M1 versions (#408): grounding/hallucination not comparable.
    if comparison.avviso_versioni_m1:
        lines.append(comparison.avviso_versioni_m1)
        lines.append("")
    # Vacuity (#231): the warning opens the report, BEFORE the table. Otherwise
    # whoever reads would meet a quality delta and only afterwards the note that
    # declares it not interpretable -- the order in which one misreads.
    if has_vacuous_quality_axes(comparison.vacuous_arms, comparison.vacuous_zones):
        lines.append(_vacuous_caveat(comparison.vacuous_arms, comparison.vacuous_zones))
        lines.append("")
    lines.extend(_markdown_table(cols, _rows(comparison)))
    pointer = risk_anchoring_pointer(comparison) if anchoring_pointer else ""
    if pointer:
        lines.append("")
        lines.append(pointer)
    # Separate operational view + caveat on the quality proxies (#33).
    lines.append("")
    lines.append(operational_markdown(comparison).rstrip("\n"))
    if comparison.istat_metrics:
        lines.append("")
        lines.append(istat_markdown(comparison).rstrip("\n"))
    anchoring = risk_anchoring_markdown(comparison)
    if anchoring:
        lines.append("")
        lines.append(anchoring.rstrip("\n"))
    lines.append("")
    lines.append(PROXY_CAVEAT)
    if comparison.failed:
        fcols = _failed_columns(comparison.label_a, comparison.label_b)
        lines.append("")
        lines.append("### Zone escluse dal confronto (run in errore)")
        lines.append("| " + " | ".join(fcols) + " |")
        lines.append("| " + " | ".join("---" for _ in fcols) + " |")
        for fz in comparison.failed:
            lines.append("| " + " | ".join(_failed_row(fz)) + " |")
    return "\n".join(lines) + "\n"


def to_json(comparison: Comparison) -> str:
    """Structured JSON report of the comparison (#33).

    Serializes the whole :class:`Comparison`: 4 metrics side by side A/B + delta
    per case (``zones``), aggregate (``mean_a``/``mean_b``/``mean_delta``) and excluded
    zones (``failed``). Machine-readable form of the deliverable; the quality
    metrics stay textual proxies (see :data:`PROXY_CAVEAT`).
    """
    return comparison.model_dump_json(indent=2)


def write_comparison(
    results_dir: Path, comparison: Comparison, stem: str, *, force: bool = False
) -> tuple[Path, Path]:
    """Write ``results/<stem>.{csv,md,json}`` from the comparison.

    Returns the two TABULAR paths ``(csv, md)`` -- stable contract inherited from
    #32 (regeneration of the tables with one command). The ``.json`` (machine-readable
    report required by #33) is a SIBLING artefact: written alongside,
    NOT included in the return value, so as not to break the two-element unpacking of
    the #32 callers (``compare_experiments`` and the ablation tests).

    If one of the three target files exists and ``force`` is ``False`` raises
    :class:`FileExistsError` (anti-overwrite guard, #165).
    """
    csv_path = results_dir / f"{stem}.csv"
    md_path = results_dir / f"{stem}.md"
    json_path = results_dir / f"{stem}.json"
    guard_no_overwrite([csv_path, md_path, json_path], force)
    # newline="": to_csv() already emits \r\n via csv.writer; without this, the
    # write_text text mode would re-translate \n->\r\n on Windows (spurious rows).
    # Same measure as fix #103 in aggregate.write_tables (here replicated
    # on the new file, NOT re-applied to aggregate.py).
    csv_path.write_text(to_csv(comparison), encoding="utf-8", newline="")
    md_path.write_text(to_markdown(comparison), encoding="utf-8")
    # `quality_verdict` (#238) is a field of Comparison like `isolated_variable`:
    # `to_json` already writes it without needing to compose the payload by hand here.
    json_path.write_text(to_json(comparison), encoding="utf-8")
    return csv_path, md_path


def compare_experiments(
    results_dir: Path,
    experiment_a: str,
    experiment_b: str,
    *,
    label_a: str | None = None,
    label_b: str | None = None,
    stem: str | None = None,
    force: bool = False,
) -> tuple[Path, Path]:
    """Load the records of the two experiments from disk, compare and write the tables.

    ``label_a``/``label_b`` default to the experiment name; ``stem`` defaults to
    ``<experiment_a>_vs_<experiment_b>``. ``force`` bypasses the anti-overwrite
    guard on the output files (#165).

    If no zone remains usable (both arms in ERROR/FALLBACK on
    every zone, #239) it still writes a report -- CSV/Markdown/JSON of the excluded
    zones, no verdict -- and re-raises :class:`NoUsableOutputError`, so the
    CLI caller can signal a non-zero exit code without duplicating the
    resolution of ``stem``. The anti-overwrite guard (:class:`FileExistsError`)
    propagates unchanged in this branch too (same behaviour as the
    success path). If instead the report write fails for another reason
    (disk full, permissions: :class:`OSError`), the write error is only
    logged -- ``NoUsableOutputError`` keeps being re-raised, never
    the ``OSError``, so the CLI caller still exits with a clean exit code
    instead of a second unexpected traceback (#239).
    """
    arm_a = load_runs(results_dir, experiment=experiment_a)
    arm_b = load_runs(results_dir, experiment=experiment_b)
    resolved_stem = stem or f"{experiment_a}_vs_{experiment_b}"
    try:
        comparison = compare_records(
            arm_a,
            arm_b,
            label_a=label_a or experiment_a,
            label_b=label_b or experiment_b,
        )
    except NoUsableOutputError as exc:
        try:
            write_no_usable_output_report(results_dir, exc, resolved_stem, force=force)
        except FileExistsError:
            raise
        except OSError:
            logger.exception(
                "impossibile scrivere il report di nessun-output-utilizzabile "
                "per '%s' in %s",
                resolved_stem,
                results_dir,
            )
        raise exc
    return write_comparison(results_dir, comparison, resolved_stem, force=force)
