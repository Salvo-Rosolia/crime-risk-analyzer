"""Confronto a due bracci di esperimenti di valutazione (#32).

Primitiva GENERICA: dati i ``RunRecord`` di DUE esperimenti (braccio A e braccio
B), li unisce per ``(citta, zona)`` e calcola il DELTA (A - B) delle quattro
metriche — ``grounding``, ``hallucination``, ``latency_ms``, ``cost_usd`` —
producendo una tabella per-zona più una riga aggregata (media), serializzabile
in CSV e Markdown.

Le run in ERROR (metriche azzerate dall'harness) e in FALLBACK (narrativa vuota
→ metriche non rappresentative della qualità) NON entrano in delta/medie: le
zone corrispondenti sono escluse dall'aggregato e riportate esplicitamente in
una sezione dedicata (nulla è scartato o mediato in silenzio). Solo le run
``OK`` restano incluse (#163).

Non è cablata su analyze/baseline: i bracci sono etichettati liberamente
(``label_a``/``label_b``). L'ablation (#32) confronta ``analyze`` vs
``baseline``; #33 riuserà la stessa primitiva per ``claude`` vs ``groq``.

Riusa lo stile e l'helper ``load_runs`` di :mod:`aggregate` senza modificarlo.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from crime_risk_analyzer.eval.aggregate import load_runs
from crime_risk_analyzer.eval.schema import Metrics, RunRecord, RunStatus

#: Etichetta della riga aggregata nelle tabelle.
_MEAN_LABEL = "MEDIA"

#: Status che escludono una zona dal confronto: metriche non rappresentative
#: della qualità (ERROR = azzerate dall'harness; FALLBACK = narrativa vuota, #163).
_EXCLUDED_STATUSES = (RunStatus.ERROR, RunStatus.FALLBACK)


def guard_no_overwrite(paths: list[Path], force: bool) -> None:
    """Solleva FileExistsError se un file target esiste e ``force`` e' False.

    Protegge da sovrascritture accidentali (es. stesso --out per compare e
    compare-repeated: X.csv resterebbe orfano). ``--force`` bypassa la guardia.
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
    """Quattro metriche come float, per medie e delta.

    A differenza di :class:`~crime_risk_analyzer.eval.schema.Metrics` non impone
    ``[0,1]``: un delta (A - B) può essere negativo, e ``latency_ms`` medio è un
    float.
    """

    grounding: float
    hallucination: float
    latency_ms: float
    cost_usd: float


class ZoneComparison(BaseModel):
    """Confronto di una singola zona ``(citta, zona)`` tra i due bracci."""

    citta: str
    zona: str
    a: Metrics
    b: Metrics
    delta: MetricValues


class FailedZone(BaseModel):
    """Zona esclusa dall'aggregato perché un braccio è in ``ERROR`` o ``FALLBACK``.

    Riporta lo status di ENTRAMBI i bracci così l'esclusione è tracciabile
    (quale braccio è fallito o in fallback), non silenziosa.
    """

    citta: str
    zona: str
    status_a: str
    status_b: str


class VacuousZone(BaseModel):
    """Zona su cui un braccio non ha prodotto narrativa (#231).

    Non è un'esclusione: la zona resta nell'aggregato (le misure operative sono
    valide). Segnala che su QUELLA zona le metriche di qualità del braccio in
    ``arms`` sono vacue, quindi la media che ne discende non regge un verdetto.
    """

    citta: str
    zona: str
    #: Label dei bracci rimasti muti su questa zona (uno o entrambi).
    arms: list[str]


class QualityVerdict(BaseModel):
    """Risponde da sola: "il verdetto di qualità è applicabile?" (#238).

    Prima di questo campo, pareggio (nessuna zona vacua, ma i 4 assi coincidono)
    e astensione (metriche vacue, #231) erano indistinguibili senza ispezionare
    la FORMA di ``winner`` nel report ripetuto — e il report non ripetuto non
    aveva alcun modo di rispondere alla stessa domanda. Campo del modello
    :class:`Comparison`, non bolted-on nei singoli writer: qualunque futuro
    consumatore di ``to_json``/``model_dump`` lo riceve per costruzione, non per
    disciplina di chi scrive il payload.
    """

    applicable: bool
    vacuous_arms: list[str]
    vacuous_zones: list[VacuousZone]
    reason: str = ""


class Comparison(BaseModel):
    """Confronto: zone comparate + aggregato + zone escluse (ERROR/FALLBACK)."""

    label_a: str
    label_b: str
    zones: list[ZoneComparison]
    mean_a: MetricValues
    mean_b: MetricValues
    mean_delta: MetricValues
    #: Zone escluse dall'aggregato (un braccio in ERROR o FALLBACK); vuota se nessuna.
    #: Sempre valorizzata da :func:`compare_records`.
    failed: list[FailedZone]
    #: Label dei bracci STRUTTURALMENTE VACUI (#231): nessuna run del braccio ha
    #: prodotto narrativa. Su un braccio muto ``grounding``/``hallucination``
    #: cadono nel ramo vacuo di ``metrics.py`` (1.0/0.0 per assenza di testo da
    #: giudicare), quindi gli assi di qualità NON sono interpretabili: chi legge
    #: il confronto va avvertito e nessun verdetto va emesso su quegli assi.
    #: Vuota nel caso normale (entrambi i bracci generano).
    vacuous_arms: list[str] = []
    #: Zone su cui un braccio è rimasto muto pur non essendo muto in assoluto
    #: (#231): granularità più fine di ``vacuous_arms``, perché una sola zona
    #: vacua sposta la media che decide il verdetto. Sovrainsieme: se un braccio
    #: è in ``vacuous_arms``, tutte le sue zone sono anche qui.
    vacuous_zones: list[VacuousZone] = []
    #: Dichiarazione di COSA il confronto manipola, quando i modi dei due bracci
    #: la rendono derivabile (#236); vuota altrimenti — e allora il report resta
    #: identico a prima. Non è una conclusione: dice quale variabile cambia tra i
    #: bracci, mentre la lettura dei delta di qualità resta vincolata al
    #: :data:`PROXY_CAVEAT`. Sulla coppia di modi giusta ma con impostazioni
    #: divergenti (modello o temperatura) porta l'avviso OPPOSTO
    #: (:data:`CONFOUNDED_VARIABLE_HEAD`): il campo non afferma mai che la
    #: variabile è isolata senza averlo verificato sui record.
    isolated_variable: str = ""
    #: Derivato da ``vacuous_arms``/``vacuous_zones`` qui sopra, sempre in fase
    #: di costruzione (#238): vedi :class:`QualityVerdict`.
    quality_verdict: QualityVerdict


@dataclass(frozen=True)
class _MetricSpec:
    """Fonte unica per colonne e formattazione di una metrica (evita drift m2)."""

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

#: Ordine e formato delle 4 metriche. Guida SIA le intestazioni SIA le righe:
#: aggiungere una metrica qui aggiorna header e celle in modo coerente.
_METRIC_SPECS: tuple[_MetricSpec, ...] = (
    _GROUNDING_SPEC,
    _HALLUCINATION_SPEC,
    _LATENCY_SPEC,
    _COST_SPEC,
)

#: Sottoinsieme "operativo" (misure DIRETTE): guida la tabella costo/latenza
#: separata dalle metriche-proxy di qualità (#33). Stesse spec del set completo
#: → stesso formato/segno, nessuna duplicazione di formattazione.
_OPERATIONAL_SPECS: tuple[_MetricSpec, ...] = (_LATENCY_SPEC, _COST_SPEC)

#: Caveat metodologico stampato in coda al report Markdown (#33). ``grounding``
#: e ``hallucination`` sono PROXY TESTUALI (stimati da pattern sui tag fonte e
#: sui nomi POI/hazard in ``metrics.py``), non giudizi umani di qualità;
#: ``latency_ms`` e ``cost_usd`` sono invece misure operative dirette. L'accordo
#: proxy-vs-annotazione umana è validato a parte (``eval/gold.py``, #109).
PROXY_CAVEAT = (
    "> **Nota metodologica.** `grounding` e `hallucination` sono *proxy "
    "testuali* (copertura delle citazioni e frazione di asserzioni non "
    "ancorate, stimate da pattern sui tag fonte e sui nomi POI/hazard), non "
    "giudizi umani di qualità: vanno letti come indicatori orientativi, non "
    "come verità. `latency_ms` e `cost_usd` sono invece misure operative "
    "dirette. L'accordo proxy-vs-annotazione umana è validato separatamente "
    "(`eval/gold.py`, #109)."
)


#: Titolo dell'avviso di vacuità (#231). Stampato PRIMA delle tabelle: chi legge
#: deve sapere che su questi assi il confronto non è interpretabile prima di
#: incontrare i numeri, non dopo. Fonte unica del wording (lo riusa il report
#: ripetuto per motivare il verdetto trattenuto).
VACUOUS_CAVEAT_HEAD = "> ⚠️ **Assi di qualità non applicabili.**"

#: Spiegazione del perché un braccio muto non merita 1.0/0.0. Condivisa tra il
#: caveat delle tabelle e la sezione «verdetto trattenuto» del report ripetuto:
#: una sola formulazione, nessun drift tra i due moduli.
VACUOUS_REASON = (
    "`grounding`/`hallucination` cadono nel ramo vacuo di `metrics.py` "
    "(1.0/0.0 perché non c'è testo da giudicare), che non è un merito"
)


#: Titolo della dichiarazione di variabile isolata (#236). Come l'avviso di
#: vacuità apre il report: chi legge deve sapere COSA distingue i due bracci
#: prima di incontrare i delta, non dopo.
ISOLATED_VARIABLE_HEAD = "> **Variabile isolata.**"

#: Titolo del caso opposto (#236): i modi ISOLEREBBERO l'ontologia, ma i bracci
#: non girano con la stessa impostazione (modello o temperatura diversi), quindi
#: tra loro cambia più di una variabile. Va dove andrebbe la dichiarazione, per
#: la stessa ragione: dire il falso in cima al report è peggio che non dire
#: nulla, e tacere lascerebbe il delta senza istruzioni di lettura.
CONFOUNDED_VARIABLE_HEAD = "> ⚠️ **Variabile non isolata.**"

#: Avviso che accompagna SEMPRE la coppia con/senza ontologia (#236), in qualunque
#: dei due rami della nota: le differenze operative osservate tra questi bracci
#: non sono un merito. Il prompt ablato non porta hazard, vulnerabilità e
#: citazioni, quindi è più corto per costruzione e consuma meno token in meno
#: tempo a prescindere da cosa scriva. Va detto accanto alla dichiarazione della
#: variabile perché la tabella operativa (#33) affianca latenza e costo come
#: fossero un esito del confronto — e su questa coppia sono un esito della
#: lunghezza del testo inviato. Coerente con l'esclusione dello spareggio
#: operativo dal verdetto (``winner.decide_winner``, ``operational_tiebreak``).
PROMPT_LENGTH_SIDE_EFFECT = (
    "Le eventuali differenze di `latency_ms`/`cost_usd` tra questi due bracci "
    "NON sono un merito: il prompt senza ontologia è strutturalmente più corto "
    "(non porta hazard, vulnerabilità e citazioni), quindi consuma meno token in "
    "meno tempo a prescindere dalla qualità della prosa. Per questa coppia "
    "velocità e costo non sono spareggi validi e il verdetto non li usa."
)

#: Cosa il delta di qualità significa quando la variabile È isolata (#236) e gli
#: assi di qualità sono leggibili. Costante nominata perché è l'affermazione più
#: impegnativa del report — quella che un lettore cita — e perché il ramo vacuo
#: deve poterla SOSTITUIRE, non affiancare (vedi :data:`VACUOUS_DELTA_CLAIM`).
ISOLATED_DELTA_CLAIM = (
    "Il delta su `grounding`/`hallucination` misura quindi l'effetto "
    "dell'ancoraggio ontologico su quanto la prosa nomina dati verificabili — "
    "non la qualità complessiva dell'analisi, e non con la forza di un giudizio "
    "umano (vedi la nota metodologica)."
)

#: Sostituisce :data:`ISOLATED_DELTA_CLAIM` quando il confronto ha assi di qualità
#: vacui (#231): basta UNA zona muta in un braccio. I due blocchi che aprono il
#: report parlano degli stessi assi, quindi affermare che il delta misura
#: l'effetto dell'ontologia e poi che quegli assi non sono interpretabili in
#: nessuna direzione è una contraddizione dentro lo stesso documento. L'isolamento
#: resta vero come proprietà del DISEGNO (i due bracci condividono l'impostazione,
#: è verificato sui record) e va detto: è il delta a non essere leggibile, non il
#: disegno a essere sbagliato.
VACUOUS_DELTA_CLAIM = (
    "L'isolamento riguarda però il DISEGNO dei due bracci, non i numeri di "
    "questo confronto: qui `grounding`/`hallucination` cadono nel ramo vacuo "
    "(vedi l'avviso sugli assi di qualità), quindi il delta su quegli assi NON "
    "va letto come effetto dell'ancoraggio ontologico, in nessuna direzione."
)

#: Coppia di ``mode`` che manipola il contributo ontologico nel prompt (#236):
#: cambia cosa il prompt porta al modello. È l'unica coppia di bracci per cui il
#: modulo dichiara la variabile — ``analyze`` vs ``baseline`` manipola la
#: presenza dell'LLM, due modelli manipolano il modello. NECESSARIA ma non
#: sufficiente: che il resto dell'impostazione sia condiviso lo verificano
#: :data:`_SHARED_SETTINGS` (modello, temperatura, formato del contesto) e
#: ``compare_records`` (lo snapshot POI), non questa coppia.
_ONTOLOGY_ISOLATING_MODES = frozenset({"analyze", "no_ontology_prompt"})

#: Impostazioni che i due bracci devono CONDIVIDERE perché la coppia di modi
#: isoli davvero il solo contributo ontologico del prompt: coppie ``(nome
#: leggibile, accesso al record)``. Il ``mode`` dice cosa cambia nel prompt, non
#: con quale generatore la prosa è stata scritta, né con quale forma il blocco POI
#: è stato reso, né con quale campionamento il testo è stato estratto: una run
#: Claude contro una run Groq cambia prompt E modello insieme, un braccio
#: ``per_classe`` contro uno ``per_poi`` cambia prompt E formato — che #273 tiene
#: opzionale proprio perché non è ovvio quale dei due faccia nominare più punti —
#: e due semi diversi fanno estrarre dallo stesso prompt due prose diverse. Sono
#: tutte dimensioni che agiscono sull'asse che i proxy misurano. Lo
#: ``snapshot_id`` non è qui perché ``compare_records`` lo impone già sollevando
#: su divergenza.
_SHARED_SETTINGS: tuple[tuple[str, Callable[[RunRecord], object]], ...] = (
    ("modello", lambda rec: rec.model_id),
    ("temperatura", lambda rec: rec.provenance.temperature),
    ("formato del contesto", lambda rec: rec.provenance.context_format),
    ("seed di campionamento", lambda rec: rec.provenance.seed),
)


def _single_mode(records: list[RunRecord]) -> str:
    """``mode`` del braccio se è uno solo; ``""`` se il braccio è misto o vuoto."""
    modes = {rec.mode for rec in records}
    return next(iter(modes)) if len(modes) == 1 else ""


def _observed(
    records: list[RunRecord], get: Callable[[RunRecord], object]
) -> list[str]:
    """Valori distinti (citati, ordinati) di un'impostazione dentro un braccio."""
    return sorted({f"`{get(rec)}`" for rec in records})


def _configured_records(records: list[RunRecord]) -> list[RunRecord]:
    """Record che descrivono l'impostazione REALE dell'esperimento (#163).

    Esclude ERROR e FALLBACK, gli stessi status che ``compare_records`` tiene
    fuori da medie e delta. Un record di fallback non riporta la temperatura
    configurata ma il placeholder di ``_structured_response``
    (``Repro(temperature=0.0)``, scritto per costruzione quando l'LLM cade):
    leggerlo come impostazione farebbe apparire misto un braccio che gira con
    un'unica temperatura, e dichiarare confusa una variabile che nessuno ha
    confuso.
    """
    return [rec for rec in records if rec.status not in _EXCLUDED_STATUSES]


def _setting_mismatch(
    arm_a: list[RunRecord], arm_b: list[RunRecord], *, label_a: str, label_b: str
) -> str:
    """Prima impostazione di :data:`_SHARED_SETTINGS` che i bracci NON condividono.

    Ritorna una descrizione con i valori osservati per braccio, o ``""`` se
    l'impostazione è la stessa da entrambi i lati. Un braccio con valori MISTI
    conta come mancata condivisione: non esiste un valore unico da dichiarare
    condiviso, quindi il confronto non isola nulla nemmeno lì. Vale anche per un
    braccio i cui record sono TUTTI falliti (nessun valore osservabile): non c'è
    un'impostazione da dichiarare condivisa — ``compare_records`` solleva prima,
    su quel caso, perché non resterebbe alcuna zona da confrontare.
    """
    for name, get in _SHARED_SETTINGS:
        seen_a = _observed(_configured_records(arm_a), get)
        seen_b = _observed(_configured_records(arm_b), get)
        if seen_a != seen_b or len(seen_a) != 1:
            return (
                f"{name} (`{label_a}`: {', '.join(seen_a)}; "
                f"`{label_b}`: {', '.join(seen_b)})"
            )
    return ""


def is_ontology_isolating_pair(arm_a: list[RunRecord], arm_b: list[RunRecord]) -> bool:
    """True se i modi dei due bracci sono la coppia che manipola l'ontologia (#236).

    Derivato dai RECORD (il loro ``mode``), non dal nome degli esperimenti, come
    :func:`isolated_variable_note` che lo riusa: su qualunque altra coppia
    ritorna ``False`` e nulla cambia. Un braccio MISTO (più di un ``mode``) non
    è riconoscibile e vale ``False``.

    Lo consuma anche il verdetto a valle (``repeated_comparison``) per escludere
    velocità e costo dallo spareggio: su questa coppia sono un effetto della
    lunghezza del prompt (:data:`PROMPT_LENGTH_SIDE_EFFECT`), non un merito.
    Predicato ESPORTATO invece di ricontrollato là: due riconoscimenti della
    stessa coppia divergerebbero proprio sul caso che conta.
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
    """Dichiara la variabile manipolata, se i modi dei due bracci la rendono nota.

    Derivata dai RECORD (il loro ``mode``), non dal nome degli esperimenti: il
    confronto resta la primitiva generica di #32, e su qualunque altra coppia
    questa funzione ritorna ``""`` lasciando il report invariato.

    Che i bracci condividano modello, temperatura, formato del contesto e seed è
    VERIFICATO sui record (:func:`_setting_mismatch`, su :data:`_SHARED_SETTINGS`),
    non dedotto dai modi: due run con generatori diversi cambiano prompt e modello
    insieme, e su quella coppia la funzione dichiara che la variabile NON è
    isolata invece di prometterlo. Il controllo guarda i soli record che
    descrivono l'impostazione reale (:func:`_configured_records`).

    Il testo dice cosa cambia e cosa NON cambia tra i bracci, e si ferma lì: la
    lettura dei delta di qualità resta quella del :data:`PROXY_CAVEAT` (proxy
    testuali, non giudizi umani). Dichiarare la variabile serve proprio a non
    leggere un delta come una misura della bontà dell'analisi.

    ``quality_axes_vacuous`` (dal predicato condiviso
    :func:`has_vacuous_quality_axes`, l'unico che decide se stampare l'avviso di
    vacuità) sostituisce l'affermazione sul significato del delta: i due blocchi
    che aprono il report parlano degli STESSI assi, e con la vacuità in gioco uno
    diceva che il delta misura l'effetto dell'ontologia mentre l'altro, due righe
    sotto, che su quegli assi non c'è nulla da leggere in nessuna direzione. Il
    disegno resta isolato — quello è verificato sui record — ma i suoi numeri no.

    Tutti i rami chiudono con :data:`PROMPT_LENGTH_SIDE_EFFECT`: che il braccio
    ablato sia più rapido ed economico è una proprietà dei due prompt, quindi va
    detto sia quando la variabile è isolata sia quando non lo è, e la tabella
    operativa è stampata anche quando gli assi di qualità sono vacui.
    """
    if not is_ontology_isolating_pair(arm_a, arm_b):
        return ""
    con, senza = (
        (label_a, label_b) if _single_mode(arm_a) == "analyze" else (label_b, label_a)
    )
    mismatch = _setting_mismatch(arm_a, arm_b, label_a=label_a, label_b=label_b)
    if mismatch:
        return (
            f"{CONFOUNDED_VARIABLE_HEAD} Tra i due bracci cambia il PROMPT "
            f"(`{con}` riceve gli hazard che l'ontologia associa alle classi dei "
            f"punti, `{senza}` solo nome e classe dei punti), ma non condividono "
            f"la stessa impostazione: {mismatch}. Cambia quindi più di una "
            "variabile e il delta su `grounding`/`hallucination` NON è "
            "attribuibile all'ancoraggio ontologico: per isolarlo, rilanciare i "
            f"due bracci con la stessa impostazione. {PROMPT_LENGTH_SIDE_EFFECT}"
        )
    what_changes = (
        f"{ISOLATED_VARIABLE_HEAD} I due bracci condividono modello, "
        "temperatura, formato del contesto, seed di campionamento, snapshot POI "
        "e dati strutturati della risposta "
        "(`poi[]`, `risk_models`, confidence, quindi gli stessi ancoraggi su cui "
        f"i proxy si calcolano). L'unica differenza è il PROMPT: `{con}` riceve "
        f"gli hazard che l'ontologia associa alle classi dei punti, `{senza}` "
        "riceve solo nome e classe dei punti."
    )
    claim = VACUOUS_DELTA_CLAIM if quality_axes_vacuous else ISOLATED_DELTA_CLAIM
    return f"{what_changes} {claim} {PROMPT_LENGTH_SIDE_EFFECT}"


def _quote_arms(labels: list[str]) -> tuple[str, str]:
    """(label citate, verbo concordato) per i messaggi di vacuità."""
    quoted = " e ".join(f"`{label}`" for label in dict.fromkeys(labels))
    verbo = "non produce" if len(set(labels)) == 1 else "non producono"
    return quoted, verbo


def vacuity_subject(vacuous_arms: list[str], vacuous_zones: list[VacuousZone]) -> str:
    """Frase che dice CHI è rimasto muto e DOVE (braccio intero o singole zone).

    Preferisce la formulazione per braccio quando il braccio è muto ovunque: è
    più informativa di elencarne tutte le zone.
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
    """True se su questo confronto ``grounding``/``hallucination`` non si leggono.

    UNICO punto in cui si decide che gli assi di qualità sono vacui (#231), e per
    questo esportato: lo consumano l'avviso in cima al report
    (:func:`to_markdown`), la dichiarazione di variabile isolata
    (:func:`isolated_variable_note`) e il verdetto trattenuto del report ripetuto.
    Tre condizioni scritte a mano potrebbero divergere, e divergerebbero facendo
    dire al documento una cosa e la sua negazione sugli stessi assi.

    Basta UNA zona muta in un braccio: entra nella media che il confronto stampa
    e che il criterio lessicografico userebbe per decidere.
    """
    return bool(vacuous_arms or vacuous_zones)


def _quality_verdict(
    vacuous_arms: list[str], vacuous_zones: list[VacuousZone]
) -> QualityVerdict:
    """Costruisce il :class:`QualityVerdict` di un confronto (#238).

    Chiamata una sola volta, dentro :func:`compare_records`, cosi' il campo
    finisce sul modello :class:`Comparison` stesso: qualunque writer presente o
    futuro lo eredita da ``to_json``/``model_dump`` senza ricostruirlo a mano
    (la duplicazione che questa funzione elimina — vedi il modulo
    ``repeated_comparison``, che prima aveva la sua propria copia).
    """
    withheld = has_vacuous_quality_axes(vacuous_arms, vacuous_zones)
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
    """Avviso per le tabelle: perché gli assi di qualità non si leggono."""
    return (
        f"{VACUOUS_CAVEAT_HEAD} {vacuity_subject(vacuous_arms, vacuous_zones)}: "
        f"{VACUOUS_REASON}. Su questi assi il confronto NON è interpretabile in "
        "nessuna direzione; restano confrontabili le misure operative (latenza, "
        "costo)."
    )


def has_narrativa(record: RunRecord) -> bool:
    """True se il record porta narrativa non vuota (#231).

    Unico punto in cui si decide cosa conta come «ha parlato». ``status=OK`` con
    narrativa vuota è raggiungibile in produzione — il client ritorna
    ``content or ""`` senza sollevare, quindi l'orchestrator risponde
    ``fallback=False`` — perciò lo status NON basta a riconoscere una zona muta.
    """
    return bool(record.narrativa.strip())


def is_vacuous_arm(records: list[RunRecord]) -> bool:
    """True se NESSUN record del braccio ha prodotto narrativa (#231).

    Un braccio è vacuo per costruzione (``mode='baseline'``: nessun LLM) o
    perché non ha mai prodotto testo. In entrambi i casi non esiste materiale su
    cui i proxy di qualità possano dire qualcosa. Un braccio che tace su ALCUNE
    zone e parla su altre NON è vacuo: quelle zone sono raccolte in
    ``Comparison.vacuous_zones`` e trattengono comunque il verdetto.

    Un braccio vuoto (nessun record) non è vacuo: non è un braccio.

    Confine dichiarato: rileva l'assenza di TESTO, non ogni ramo vacuo di
    ``metrics.py``. Una narrativa piena ma senza ancoraggi da citare (zona senza
    POI) è anch'essa gradata 1.0/0.0 per vacuità e NON è intercettata qui.
    """
    return bool(records) and not any(has_narrativa(rec) for rec in records)


def _to_values(m: Metrics) -> MetricValues:
    """Proietta una :class:`Metrics` (latency int) in :class:`MetricValues`."""
    return MetricValues(
        grounding=m.grounding,
        hallucination=m.hallucination,
        latency_ms=float(m.latency_ms),
        cost_usd=m.cost_usd,
    )


def _delta(a: Metrics, b: Metrics) -> MetricValues:
    """Delta per-metrica A - B (può essere negativo)."""
    return MetricValues(
        grounding=a.grounding - b.grounding,
        hallucination=a.hallucination - b.hallucination,
        latency_ms=float(a.latency_ms - b.latency_ms),
        cost_usd=a.cost_usd - b.cost_usd,
    )


def _mean(values: list[MetricValues]) -> MetricValues:
    """Media per-metrica su una lista non vuota di :class:`MetricValues`."""
    n = len(values)
    return MetricValues(
        grounding=float(sum(v.grounding for v in values) / n),
        hallucination=float(sum(v.hallucination for v in values) / n),
        latency_ms=float(sum(v.latency_ms for v in values) / n),
        cost_usd=float(sum(v.cost_usd for v in values) / n),
    )


def _index_by_zone(records: list[RunRecord]) -> dict[tuple[str, str], RunRecord]:
    """Indicizza i record per ``(citta, zona)``; errore su chiave duplicata."""
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


def compare_records(
    arm_a: list[RunRecord],
    arm_b: list[RunRecord],
    *,
    label_a: str,
    label_b: str,
) -> Comparison:
    """Unisce due bracci per ``(citta, zona)`` e calcola i delta A - B.

    Le zone in cui un braccio è in ``ERROR`` (metriche azzerate) o ``FALLBACK``
    (narrativa vuota → metriche non di qualità) sono escluse da zone comparate e
    medie, e raccolte in ``Comparison.failed`` (#163). Solo ``OK`` resta incluso.

    Le zone su cui un braccio non ha prodotto narrativa sono marcate in
    ``Comparison.vacuous_zones``, e un braccio muto su TUTTE le zone anche in
    ``Comparison.vacuous_arms`` (#231): lì le metriche di qualità sono vacue, non
    un merito, e a valle nessun verdetto va emesso su quegli assi. Non è un
    errore e non esclude zone: le misure operative (latenza, costo) restano
    valide e confrontabili.

    Solleva :class:`ValueError` se: un braccio ha record duplicati per una zona;
    i due bracci coprono zone diverse (iso-input violato); una zona appaiata ha
    ``snapshot_id`` divergente tra i bracci (iso-input a livello di record); non
    resta alcuna zona valida da confrontare.
    """
    index_a = _index_by_zone(arm_a)
    index_b = _index_by_zone(arm_b)
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
    for key in sorted(keys_a):
        rec_a = index_a[key]
        rec_b = index_b[key]
        # Iso-input a livello di record: la stessa (citta, zona) deve citare lo
        # stesso snapshot_id in entrambi i bracci. Difesa-in-profondità (record
        # manomessi a mano, o un futuro snapshot_id derivato dal contenuto POI).
        # NON intercetta un --force: quello sovrascrive il file snapshot ma lascia
        # l'id invariato (derivato solo da (citta, zona)), quindi una divergenza
        # di CONTENUTO tra i bracci non emergerebbe qui.
        sid_a = rec_a.provenance.snapshot_id
        sid_b = rec_b.provenance.snapshot_id
        if sid_a != sid_b:
            raise ValueError(
                f"snapshot_id divergente per (citta, zona)={key}: "
                f"A={sid_a!r} B={sid_b!r} (confronto iso-input violato)"
            )
        # ERROR (metriche azzerate dall'harness) e FALLBACK (narrativa vuota →
        # metriche non rappresentative della qualità) sono esclusi, non mediati
        # (#163). Riportati tra le zone fallite: esclusione tracciata, non muta.
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
        # Zona muta (#231): status OK ma nessun testo prodotto da un braccio. La
        # zona resta comparata (le misure operative valgono), ma le sue metriche
        # di qualità sono vacue e non possono sostenere un verdetto.
        silent = [
            label
            for label, rec in ((label_a, rec_a), (label_b, rec_b))
            if not has_narrativa(rec)
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
    if not zones:
        raise ValueError(
            "nessuna zona valida da confrontare (tutte in ERROR/FALLBACK, "
            "nessun braccio ha prodotto output utilizzabile): "
            f"{[(f.citta, f.zona) for f in failed]}"
        )
    vacuous = [
        label
        for label, arm in ((label_a, arm_a), (label_b, arm_b))
        if is_vacuous_arm(arm)
    ]
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
        isolated_variable=isolated_variable_note(
            arm_a,
            arm_b,
            label_a=label_a,
            label_b=label_b,
            # La nota è calcolata QUI, non nei renderer, perché la vacuità è nota
            # solo dopo il join: così il campo (che finisce anche nel JSON) e
            # l'avviso del Markdown non possono raccontare due storie diverse.
            quality_axes_vacuous=has_vacuous_quality_axes(vacuous, vacuous_zones),
        ),
        quality_verdict=_quality_verdict(vacuous, vacuous_zones),
    )


def _columns(
    label_a: str, label_b: str, specs: tuple[_MetricSpec, ...] = _METRIC_SPECS
) -> list[str]:
    """Intestazioni: per ogni metrica in ``specs``, valore A, valore B, delta.

    ``specs`` default all'insieme completo (tabella principale); passando
    :data:`_OPERATIONAL_SPECS` genera le sole colonne costo/latenza (#33).
    """
    cols = ["citta", "zona"]
    for spec in specs:
        cols.extend(
            [f"{spec.name}_{label_a}", f"{spec.name}_{label_b}", f"{spec.name}_delta"]
        )
    return cols


def _failed_columns(label_a: str, label_b: str) -> list[str]:
    """Intestazioni della sezione zone escluse (status per braccio)."""
    return ["citta", "zona", f"status_{label_a}", f"status_{label_b}"]


def _failed_row(failed: FailedZone) -> list[str]:
    """Riga di una zona esclusa; allineata a :func:`_failed_columns`."""
    return [failed.citta, failed.zona, failed.status_a, failed.status_b]


def _fmt_row(
    citta: str,
    zona: str,
    a: MetricValues,
    b: MetricValues,
    d: MetricValues,
    specs: tuple[_MetricSpec, ...] = _METRIC_SPECS,
) -> list[str]:
    """Una riga formattata; i delta portano il segno esplicito (+/-).

    Derivata dallo stesso ``specs`` di :func:`_columns`: header e righe non
    possono disallinearsi (una sola fonte di verità), qualunque sottoinsieme.
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
    """Righe per-zona (solo zone valide) seguite dalla riga aggregata (media)."""
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
    """Serializza il confronto in CSV: tabella RETTANGOLARE (zone valide + MEDIA).

    Le zone escluse (un braccio in ERROR) NON entrano nel CSV, che resta una
    tabella uniforme caricabile da pandas/``csv.reader`` senza righe ragged; sono
    riportate nel report Markdown (:func:`to_markdown`) e restano accessibili in
    ``Comparison.failed``: nessun fallimento sparisce in silenzio.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_columns(comparison.label_a, comparison.label_b))
    for row in _rows(comparison):
        writer.writerow(row)
    return buf.getvalue()


def _markdown_table(cols: list[str], rows: list[list[str]]) -> list[str]:
    """Righe markdown di una tabella (header + separatore + dati)."""
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


def operational_markdown(comparison: Comparison) -> str:
    """Tabella costo/latenza (metriche operative), SEPARATA dalla qualità (#33).

    Ri-presenta le sole misure DIRETTE (``latency_ms``, ``cost_usd``) affiancate
    A/B + delta, per-zona e in media, riusando il join+delta già in
    ``comparison`` (nessun ricalcolo). Le metriche di qualità restano nella
    tabella principale e sono proxy testuali: vedi :data:`PROXY_CAVEAT`.
    """
    cols = _columns(comparison.label_a, comparison.label_b, _OPERATIONAL_SPECS)
    lines = ["### Costo e latenza (metriche operative)", ""]
    lines.extend(_markdown_table(cols, _rows(comparison, _OPERATIONAL_SPECS)))
    return "\n".join(lines) + "\n"


def to_markdown(comparison: Comparison) -> str:
    """Report Markdown del confronto.

    Compone: la dichiarazione della variabile isolata quando è derivabile (#236),
    tabella principale (4 metriche affiancate A/B + delta, per-zona + media),
    tabella costo/latenza separata (#33), l'avviso sui bracci vacui quando
    presenti (#231), caveat metodologico sui proxy testuali, e — se presenti — la
    sezione delle zone escluse (run in errore).
    """
    cols = _columns(comparison.label_a, comparison.label_b)
    lines: list[str] = []
    # Variabile isolata (#236): apre il report per la stessa ragione dell'avviso
    # di vacuità — dice come vanno letti i delta, quindi va letta prima di essi.
    if comparison.isolated_variable:
        lines.append(comparison.isolated_variable)
        lines.append("")
    # Vacuità (#231): l'avviso apre il report, PRIMA della tabella. Al contrario
    # chi legge incontrerebbe un delta di qualità e solo dopo la nota che lo
    # dichiara non interpretabile — l'ordine in cui si sbaglia a leggere.
    if has_vacuous_quality_axes(comparison.vacuous_arms, comparison.vacuous_zones):
        lines.append(_vacuous_caveat(comparison.vacuous_arms, comparison.vacuous_zones))
        lines.append("")
    lines.extend(_markdown_table(cols, _rows(comparison)))
    # Vista operativa separata + caveat sui proxy di qualità (#33).
    lines.append("")
    lines.append(operational_markdown(comparison).rstrip("\n"))
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
    """Report JSON strutturato del confronto (#33).

    Serializza l'intero :class:`Comparison`: 4 metriche affiancate A/B + delta
    per-caso (``zones``), aggregato (``mean_a``/``mean_b``/``mean_delta``) e zone
    escluse (``failed``). Forma machine-readable del deliverable; le metriche di
    qualità restano proxy testuali (vedi :data:`PROXY_CAVEAT`).
    """
    return comparison.model_dump_json(indent=2)


def write_comparison(
    results_dir: Path, comparison: Comparison, stem: str, *, force: bool = False
) -> tuple[Path, Path]:
    """Scrive ``results/<stem>.{csv,md,json}`` dal confronto.

    Ritorna i due path TABELLARI ``(csv, md)`` — contratto stabile ereditato da
    #32 (rigenerazione delle tabelle con un comando). Il ``.json`` (report
    machine-readable richiesto da #33) è un artefatto SIBLING: scritto accanto,
    NON incluso nel valore di ritorno, per non rompere l'unpacking a due dei
    chiamanti #32 (``compare_experiments`` e i test dell'ablation).

    Se uno dei tre file target esiste e ``force`` è ``False`` solleva
    :class:`FileExistsError` (guardia anti-sovrascrittura, #165).
    """
    csv_path = results_dir / f"{stem}.csv"
    md_path = results_dir / f"{stem}.md"
    json_path = results_dir / f"{stem}.json"
    guard_no_overwrite([csv_path, md_path, json_path], force)
    # newline="": to_csv() emette gia' \r\n via csv.writer; senza questo, il
    # text-mode di write_text ritradurrebbe \n->\r\n su Windows (righe spurie).
    # Stesso accorgimento del fix #103 in aggregate.write_tables (qui replicato
    # sul file nuovo, NON ri-applicato ad aggregate.py).
    csv_path.write_text(to_csv(comparison), encoding="utf-8", newline="")
    md_path.write_text(to_markdown(comparison), encoding="utf-8")
    # `quality_verdict` (#238) e' un campo di Comparison come `isolated_variable`:
    # `to_json` lo scrive gia' senza bisogno di comporre il payload a mano qui.
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
    """Carica i record dei due esperimenti da disco, confronta e scrive le tabelle.

    ``label_a``/``label_b`` default al nome dell'esperimento; ``stem`` default a
    ``<experiment_a>_vs_<experiment_b>``. ``force`` bypassa la guardia
    anti-sovrascrittura sui file di output (#165).
    """
    arm_a = load_runs(results_dir, experiment=experiment_a)
    arm_b = load_runs(results_dir, experiment=experiment_b)
    comparison = compare_records(
        arm_a,
        arm_b,
        label_a=label_a or experiment_a,
        label_b=label_b or experiment_b,
    )
    resolved_stem = stem or f"{experiment_a}_vs_{experiment_b}"
    return write_comparison(results_dir, comparison, resolved_stem, force=force)
