"""Metriche deterministiche di valutazione (#34).

Metriche strutturali sulla AnalyzeResponse. ``grounding``/``hallucination`` sono
PROXY testuali (vedi caveat EN/IT nella spec): misurano se le asserzioni di rischio
citano i dati ancorati (nomi POI/hazard, label EN/IT #77).

**Semantica M1 (#229, ``METRICS_VERSION == 2``).** Il proxy grada SOLO le asserzioni
del PRIMO blocco della narrativa, quello in cui il modello attribuisce rischi ai punti:
nel braccio di prodotto e' ``[ONTOLOGIA]``, l'unico layer con backing strutturato dal
grounding (``grounding.py`` emette solo il tag ``ONTOLOGIA``); nel braccio di ablazione
(#236) e' ``[SINTESI-LLM]``, che backing non ne ha per costruzione — ed e' il punto
dell'esperimento, misurare quanto quel blocco resti ancorato quando i dati ancorati non
arrivano nel prompt. L'``overview`` di sintesi e il blocco
``[CONTESTO]`` sono INTERPRETAZIONE dell'LLM (conoscenza generale, non un dato
ontologico): la loro qualita'/fabbricazione NON e' gradabile da un proxy deterministico
di ancoraggio e oggi non ha nessuna misura dedicata (vedi sotto), oltre a essere frenata
a monte dal prompt (regola 2 + ``[CONTESTO]`` "senza inventare"). L'attribuzione della
fonte e' per BLOCCO (header #196), non per tag inline: il proxy v1 (pre-#229) cercava
``[TAG]`` nella singola frase e, con i tag ora solo negli header, era mal-calibrato su
output reale — motivo del cambio (non una regressione).

**Cosa NON e' validato.** L'accordo fra questo proxy e un giudizio umano d'insieme non
e' misurato da nessuna parte: la correlazione per-run (#109) e' stata RIMOSSA con #152 e
non sostituita da un equivalente diretto. ``eval/gold.py`` valida a un'altra grana — la
fonte del singolo rischio citato nel blocco misurato
(:func:`~crime_risk_analyzer.eval.gold.collect_kept_risks`) — che e' una domanda
diversa. Un claim forte su questi numeri resta quindi privo di un ancoraggio umano.

**Come il braccio entra nel calcolo (#236).** Dal ``mode`` della run si ricava la sola
riga-etichetta da cercare (:data:`_MEASURED_TOKEN_BY_MODE`); la formula non cambia, e
due narrative identiche sotto le due etichette prendono lo stesso punteggio —
altrimenti il confronto tra i bracci misurerebbe l'etichetta invece dell'ancoraggio.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from crime_risk_analyzer.eval.pricing import cost_usd
from crime_risk_analyzer.eval.schema import Metrics, Mode
from crime_risk_analyzer.orchestrator import AnalyzeResponse
from crime_risk_analyzer.rag.generation import (
    ONTOLOGY_TOKEN,
    RiskModel,
    parse_source_prose,
)
from crime_risk_analyzer.rag.no_ontology_generation import LLM_SYNTHESIS_TOKEN

#: Generazione della SEMANTICA del proxy grounding/hallucination (#229). ``1`` era il
#: proxy inline-tag (pre-#229): cercava ``[TAG]`` nella singola frase, ma la struttura
#: a blocchi #196 mette il tag SOLO nell'header -> su output reale il proxy v1 era
#: mal-calibrato. ``2`` e' M1 block-aware: grada SOLO le asserzioni del blocco
#: [ONTOLOGIA] (l'unico layer con backing strutturato dal grounding), delegando
#: l'interpretazione [CONTESTO] al gold umano (#152). Espone la versione cosi' che un
#: confronto (compare.py/winner.py #157) non mescoli silenziosamente generazioni di
#: metrica: i valori pre-#229 su output reale non sono confrontabili con questi.
METRICS_VERSION = 2

#: Riga-etichetta del blocco che il proxy grada, PER BRACCIO (#236). Il braccio
#: senza ontologia etichetta il suo blocco per cio' che e' — una sintesi del
#: modello, non un dato ontologico — quindi cercare in ogni braccio la stessa
#: stringa lo misurerebbe su un blocco che non emette: 0.0/1.0 per NON-ATTRIBUZIONE
#: su ogni run, e il confronto C3 deciso dal nome dell'etichetta. Cambia SOLO la
#: sottostringa cercata: la formula di grounding/hallucination e' la stessa.
#: ``baseline`` non genera prosa (ramo vacuo di :func:`_grade`) ma resta mappato:
#: la copertura esaustiva dei ``Mode`` e' verificata da un test, cosi' un braccio
#: nuovo non puo' entrare senza dichiarare su cosa viene misurato.
_MEASURED_TOKEN_BY_MODE: dict[Mode, str] = {
    "analyze": ONTOLOGY_TOKEN,
    "baseline": ONTOLOGY_TOKEN,
    "no_ontology_prompt": LLM_SYNTHESIS_TOKEN,
}

#: Braccio assunto quando il chiamante non lo dichiara: quello storico. Tiene
#: invariato ogni punto di misura scritto prima di #236.
_DEFAULT_MODE: Mode = "analyze"


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"[.\n]", text) if s.strip()]


def _non_empty_lower(tokens: Iterable[str]) -> set[str]:
    """Token lowercase senza i vuoti/whitespace.

    Un POI OSM senza tag `name` arriva con name="" e, poiché `"" in s` è sempre
    vero, renderebbe OGNI frase "ancorata" neutralizzando la discriminazione
    (riaprirebbe cat.2 e vanificherebbe l'esclusione del filler). Cfr. review
    #163 I1.
    """
    return {t.lower() for t in tokens if t.strip()}


def _poi_anchors(poi_names: Iterable[str]) -> set[str]:
    """Ancoraggi-POI: i nomi dei punti, lowercase, senza i nomi vuoti."""
    return _non_empty_lower(poi_names)


def _hazard_anchors(risk_models: Iterable[RiskModel]) -> set[str]:
    """Ancoraggi-hazard: identifier + etichette EN/IT (#77), lowercase."""
    tokens: list[str] = []
    for model in risk_models:
        for risk in model.risks:
            tokens.append(risk.hazard)
            if risk.hazard_label_it:
                tokens.append(risk.hazard_label_it)
            if risk.hazard_label_en:
                tokens.append(risk.hazard_label_en)
    return _non_empty_lower(tokens)


def _anchors(resp: AnalyzeResponse) -> set[str]:
    """Token ancorati: nomi POI + hazard (identifier + etichette EN/IT), lowercase.

    Include le etichette italiane controllate (#77) così il match regge quando la
    narrativa cita l'hazard in italiano (chiude il caveat EN/IT delle metriche).
    I token vuoti (es. POI senza nome) sono scartati: non devono ancorare tutto.
    Unione delle due famiglie che :func:`risk_anchoring` tiene separate (#359).
    """
    return _poi_anchors(p.name for p in resp.poi) | _hazard_anchors(resp.risk_models)


def hazards_cited_in(narrativa: str, mode: Mode) -> str:
    """Testo lowercase del blocco misurato: verifica un hazard/etichetta con `in`.

    Riusata da ``eval/gold.py`` (#152, vedi Task 3 ``collect_kept_risks``): il
    campionatore dell'annotazione per-rischio deve escludere un hazard
    presente nel set grounded (``RunRecord.risk_models``, costruito PRIMA
    della generazione LLM, identico fra ``analyze``/``baseline``) ma mai
    citato in narrativa — altrimenti misurerebbe il set candidato invece di
    "cosa l'LLM ha mantenuto", esattamente cio' che la spec chiede.

    Ritorna il testo intero (non un insieme di token pre-estratti) perche' il
    chiamante ha già in mano gli hazard candidati da testare (dal
    ``risk_models`` del record) — stessa idea di :func:`_grounded`, ma
    sull'intero blocco invece che per-frase. Stesso ``parse_source_prose`` e
    la stessa sottostringa per-braccio di :func:`_ontology_assertions`.
    """
    return parse_source_prose(
        narrativa or "", measured_token=_MEASURED_TOKEN_BY_MODE[mode]
    ).ontologia.lower()


def _ontology_assertions(
    resp: AnalyzeResponse, mode: Mode, narrativa: str | None = None
) -> list[str]:
    """Asserzioni gradabili dal proxy (M1, #229): le frasi del blocco misurato.

    :func:`~crime_risk_analyzer.rag.generation.parse_source_prose` isola il CORPO del
    blocco dalla narrativa a blocchi (#196): l'header e' gia' escluso dal parser,
    l'``overview`` e il blocco ``[CONTESTO]`` finiscono in campi separati e NON entrano
    qui (interpretazione -> gold umano). Ogni frase-corpo del blocco e' una asserzione
    del braccio: il denominatore di grounding/hallucination. Una narrativa senza il
    blocco atteso (vuota o non compliant) ritorna ``[]``: la distinzione tra ramo VACUO
    e NON-ATTRIBUZIONE e' fatta in :func:`_grade`.

    Quale riga-etichetta apra quel blocco dipende dal braccio
    (:data:`_MEASURED_TOKEN_BY_MODE`): ``[ONTOLOGIA]`` dove l'ontologia c'e'
    davvero, ``[SINTESI-LLM]`` nel braccio ablato (#236).

    ``narrativa`` (#345) sostituisce ``resp.narrativa`` quando fornita: l'harness
    la usa per gradare M1 sul testo grezzo senza le frasi con cifre ISTAT.
    """
    testo = resp.narrativa if narrativa is None else narrativa
    return _measured_sentences(testo, mode)


def _measured_sentences(narrativa: str | None, mode: Mode) -> list[str]:
    """Frasi del blocco misurato del braccio ``mode``; ``[]`` se il blocco manca."""
    prose = parse_source_prose(
        narrativa or "", measured_token=_MEASURED_TOKEN_BY_MODE[mode]
    ).ontologia
    return _sentences(prose)


def _names_any(sentence: str, anchors: set[str]) -> bool:
    """True se la frase nomina almeno un ancoraggio (match per sottostringa)."""
    low = sentence.lower()
    return any(a in low for a in anchors)


def _grounded(assertions: list[str], anchors: set[str]) -> list[str]:
    """Asserzioni ontologiche ancorate: nominano un dato reale (POI/hazard, label)."""
    return [s for s in assertions if _names_any(s, anchors)]


def _grade(
    resp: AnalyzeResponse, mode: Mode, narrativa: str | None = None
) -> tuple[int, int] | None:
    """``(grounded, assertions)`` del blocco misurato, o ``None`` se non gradabile.

    ``None`` = ramo VACUO (grounding 1.0 / hallucination 0.0), riservato ai casi in cui
    il proxy non ha legittimamente nulla da gradare:
    - narrativa vuota (fallback strutturato: nessun output LLM da giudicare);
    - nessun ancoraggio disponibile (``_anchors`` vuoto: nessun dato da citare).

    Il caso "narrativa PIENA con dati da citare ma SENZA asserzioni nel blocco misurato"
    (es. modello che non emette l'header atteso, o lo emette vuoto) NON e' vacuo: e'
    NON-ATTRIBUZIONE e vale ``(0, 1)`` -> grounding 0.0 / hallucination 1.0. Cosi' un
    modello non puo' ottenere un punteggio perfetto omettendo l'header (l'asse
    hallucination e' il criterio PRIMARIO di ``winner.py``, #157): l'evasione perde
    invece di vincere. Ci ricade anche una run che emette l'header dell'ALTRO braccio:
    l'etichetta attesa e' quella del suo ``mode``, non una qualsiasi.

    ``resp.narrativa`` e' ``str | None`` da #259 (fase 1: narrativa non ancora
    generata): una narrativa ``None`` e' trattata come vuota, stesso ramo VACUO —
    l'harness gira solo su pipeline che oggi producono sempre una stringa.

    ``narrativa`` (#345): passata a :func:`_ontology_assertions` al posto di
    ``resp.narrativa``.
    """
    testo = resp.narrativa if narrativa is None else narrativa
    if not (testo or "").strip():
        return None
    anchors = _anchors(resp)
    if not anchors:
        return None
    assertions = _ontology_assertions(resp, mode, testo)
    if not assertions:
        return (0, 1)
    return (len(_grounded(assertions, anchors)), len(assertions))


def grounding(resp: AnalyzeResponse, *, mode: Mode = _DEFAULT_MODE) -> float:
    """Frazione di ASSERZIONI del blocco misurato ancorate ai dati [0,1] (M1, #229).

    Asserzione = frase del blocco misurato (:func:`_ontology_assertions`); grounded =
    asserzione che nomina un ancoraggio (POI/hazard, label EN/IT #77). Rami vacui
    (:func:`_grade` -> ``None``: narrativa vuota o nessun ancoraggio da citare) → 1.0.
    Narrativa piena con dati da citare ma senza asserzioni nel blocco (header
    assente/vuoto) → 0.0 (non-attribuzione, non "vacua"). ``overview``/``[CONTESTO]``
    sono esclusi (interpretazione, delegata al gold).

    ``mode`` seleziona la riga-etichetta del blocco da gradare
    (:data:`_MEASURED_TOKEN_BY_MODE`, #236): stesso calcolo, altra sottostringa
    cercata. Default = braccio storico ``analyze``.
    """
    graded = _grade(resp, mode)
    if graded is None:
        return 1.0
    grounded, assertions = graded
    return grounded / assertions


def hallucination(resp: AnalyzeResponse, *, mode: Mode = _DEFAULT_MODE) -> float:
    """Frazione di ASSERZIONI del blocco misurato NON ancorate ai dati [0,1] (M1, #229).

    Complemento di :func:`grounding` sullo stesso denominatore (le asserzioni del blocco
    misurato): ``hallucination == 1 - grounding`` su ogni ramo (a meno
    dell'arrotondamento in virgola mobile). Una frase in quel blocco che asserisce
    un rischio senza ancoraggio reale e' fabbricazione e conta come allucinazione
    (invariante #109 preservato DENTRO il layer con backing). Rami vacui → 0.0;
    narrativa piena senza asserzioni nel blocco → 1.0 (non-attribuzione).
    La fabbricazione nell'interpretazione ``[CONTESTO]`` NON e' rilevata dal proxy
    e non ha oggi nessuna validazione umana dedicata: l'annotazione gold di #152
    (:mod:`crime_risk_analyzer.eval.gold`) verifica la fonte dei rischi CITATI nel
    blocco misurato, che e' una domanda diversa da "il ``[CONTESTO]`` ha inventato
    qualcosa?". Il buco e' dichiarato, non pianificato.

    ``mode`` come in :func:`grounding`.
    """
    graded = _grade(resp, mode)
    if graded is None:
        return 0.0
    grounded, assertions = graded
    return (assertions - grounded) / assertions


@dataclass(frozen=True)
class RiskAnchoring:
    """Scomposizione delle frasi del blocco misurato per tipo di ancoraggio (#359).

    Affiancata a M1, mai al suo posto: a parita' di narrativa, nomi dei POI e
    ``risk_models``, stesso blocco e stesse frasi di :func:`_grade`, ma le frasi
    ancorate sono divise fra quelle che nominano un rischio e quelle che nominano
    soltanto un punto. Sui record con dati ISTAT la condizione non vale (M1
    grada ``testo_senza_cifre_istat``, che il record non salva): il report di
    confronto li esclude. ``conforme`` e' ``False``
    quando la narrativa e' piena ma il blocco misurato manca o e' vuoto (formato
    non rispettato): in quel caso tutti i conteggi sono zero.
    """

    frasi_misurate: int
    frasi_ancorate_rischio: int
    frasi_ancorate_solo_poi: int
    conforme: bool

    @property
    def ancoraggio_rischi(self) -> float:
        """``frasi_ancorate_rischio / frasi_misurate``; 0.0 senza frasi misurate.

        Lo zero sul formato non rispettato segue M1, che sullo stesso caso da'
        grounding 0.0 (non-attribuzione): ometterlo non deve convenire.
        """
        if not self.frasi_misurate:
            return 0.0
        return self.frasi_ancorate_rischio / self.frasi_misurate


def risk_anchoring(
    narrativa: str | None,
    *,
    mode: Mode,
    poi_names: Iterable[str],
    risk_models: Iterable[RiskModel],
) -> RiskAnchoring | None:
    """Quante frasi del blocco misurato nominano un rischio, e quante solo un POI.

    Il proxy M1 (:func:`grounding`) conta ancorata una frase che nomina un
    ancoraggio QUALSIASI: un nome di POI basta. Qui le due famiglie restano
    separate: una frase che nomina almeno un hazard (identifier o etichetta
    EN/IT) e' ancorata dal rischio, anche se nomina pure un punto; una che non
    nomina hazard ma nomina un punto e' ancorata solo dal POI.

    Prende i dati e non una ``AnalyzeResponse`` perche' si calcola anche sui
    record gia' scritti (``RunRecord``), senza rifare run. Sui record precedenti
    a #77 le etichette EN/IT sono ricostruite dal vocabolario di oggi alla
    lettura (``RiskItem``) e possono differire da quelle usate allora da M1.
    Stessi rami di
    :func:`_grade`: ``None`` (non gradabile) su narrativa vuota o senza alcun
    ancoraggio; narrativa piena senza blocco misurato -> ``conforme=False`` e
    conteggi a zero.
    """
    if not (narrativa or "").strip():
        return None
    poi = _poi_anchors(poi_names)
    hazards = _hazard_anchors(risk_models)
    if not (poi | hazards):
        return None
    frasi = _measured_sentences(narrativa, mode)
    if not frasi:
        return RiskAnchoring(0, 0, 0, conforme=False)
    da_rischio = [f for f in frasi if _names_any(f, hazards)]
    solo_poi = [f for f in frasi if not _names_any(f, hazards) and _names_any(f, poi)]
    return RiskAnchoring(
        frasi_misurate=len(frasi),
        frasi_ancorate_rischio=len(da_rischio),
        frasi_ancorate_solo_poi=len(solo_poi),
        conforme=True,
    )


def latency_ms(resp: AnalyzeResponse) -> int:
    """Latenza end-to-end (passthrough da AnalyzeResponse)."""
    return resp.latenza_ms


def cost_usd_of(resp: AnalyzeResponse) -> float:
    """Costo stimato; 0 se non c'è LLM (baseline/fallback → llm_used vuoto)."""
    if not resp.llm_used:
        return 0.0
    return cost_usd(resp.llm_used, resp.tokens_input, resp.tokens_output)


def compute_metrics(
    resp: AnalyzeResponse,
    *,
    mode: Mode = _DEFAULT_MODE,
    narrativa_m1: str | None = None,
) -> Metrics:
    """Assembla le quattro metriche dalla AnalyzeResponse.

    ``mode`` e' il braccio della run: decide su quale blocco i due proxy testuali
    si pronunciano (#236). L'harness lo passa dal ``ExperimentConfig``, unico
    posto che lo conosce.

    ``narrativa_m1`` (#345): testo su cui gradare M1 al posto di ``resp.narrativa``.
    Sui record con ISTAT l'harness passa il testo grezzo senza le frasi con cifre
    ISTAT: M1 resta un controllo di non peggioramento dell'ancoraggio, formula e
    ``METRICS_VERSION`` invariate.

    ``quality_vacuous`` (#240) espone se questo record e' caduto nel ramo VACUO di
    :func:`_grade` (narrativa vuota o nessun ancoraggio da citare): grounding/
    hallucination valgono comunque 1.0/0.0 su quel ramo, ma non misurano qualita'
    reale. Prima di #240 questa distinzione era visibile solo nel report di
    confronto (#231); qui diventa un campo del record cosi' che aggregate.py e
    compare.py possano marcarla anche fuori da quel report (tabella per-run, CSV,
    e i bracci/zone vacui del confronto stesso).

    ``_grade`` e' chiamato una sola volta qui (non tre, una per metrica): e'
    deterministico quindi non era un bug, ma le tre invocazioni indipendenti di
    prima erano lavoro ripetuto senza motivo.
    """
    graded = _grade(resp, mode, narrativa_m1)
    if graded is None:
        grounding_value, hallucination_value = 1.0, 0.0
    else:
        grounded, assertions = graded
        grounding_value = grounded / assertions
        hallucination_value = (assertions - grounded) / assertions
    return Metrics(
        grounding=grounding_value,
        hallucination=hallucination_value,
        quality_vacuous=graded is None,
        latency_ms=latency_ms(resp),
        cost_usd=cost_usd_of(resp),
    )
