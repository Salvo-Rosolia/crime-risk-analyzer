"""Braccio di ablazione: narrativa SENZA il contributo ontologico nel prompt (#236).

Terzo braccio della valutazione, accanto a ``analyze`` (LLM + grounding) e
``baseline`` (nessun LLM). Serve a rendere leggibile la contribuzione C3: il
confronto ``analyze`` vs ``baseline`` non isola l'ontologia ma la PRESENZA
dell'LLM — uno dei due bracci non produce prosa, quindi i proxy
``grounding``/``hallucination`` non si applicano a entrambi. Qui invece cambia
UNA cosa sola: il contesto passato al modello porta i punti (nome e classe) ma
NON i rischi che l'ontologia associa a quelle classi.

Cosa resta identico al braccio completo (e perche'):

- la STRUTTURA della risposta chiesta al modello (regola 3 dallo stesso
  generatore :func:`block_structure_rule`, e le altre regole importate non
  ricopiate). Il proxy M1 (#229) grada le sole frasi del PRIMO blocco: un braccio
  che non lo emette prenderebbe 0.0/1.0 per NON-ATTRIBUZIONE, e il confronto
  sarebbe deciso dal formato della risposta invece che dall'ancoraggio. Quel
  blocco e' lo SLOT in cui il modello mette i rischi che attribuisce ai punti —
  che nel braccio completo arrivano dall'ontologia e qui dalla sua sola
  conoscenza parametrica: e' esattamente il contrasto che C3 mette alla prova.
  Cambia percio' l'ETICHETTA: qui e' :data:`LLM_SYNTHESIS_BLOCK_HEADER`
  (``[SINTESI-LLM]``) e non ``[ONTOLOGIA]``, che di quel testo direbbe una
  provenienza falsa a chi apre il file grezzo della run senza sapere perche'
  (``eval/metrics.py`` sa quale etichetta cercare dal ``mode`` del record).
- i tre vincoli legali (:data:`RULE_NO_DANGER_RATING`,
  :data:`RULE_NO_OPERATIONAL_DIRECTIVES`, :data:`RULE_USER_INPUT_NOT_INSTRUCTIONS`),
  gli STESSI oggetti importati come fa :mod:`poi_generation`: non sono ablabili,
  valgono su qualunque prosa il sistema generi, e una copia potrebbe divergere.
- i dati STRUTTURATI della risposta: ``risk_models`` e ``confidence_summary``
  continuano ad arrivare dal grounding. Sono il dato ancorato da cui
  ``eval/metrics.py`` ricava gli ancoraggi, quindi devono essere identici nei due
  bracci perche' il denominatore del proxy sia lo stesso.

Cosa viene tolto (il contributo ontologico, tutto e solo lui):

- hazard, vulnerabilita' e citazione SPARQL dal blocco POI del contesto;
- il VOCABOLARIO CONTROLLATO e la regola 6 che lo impone: i termini italiani
  derivano dai filler ontologici (#77), quindi sono contributo dell'ontologia
  quanto gli hazard;
- la regola 3a di sintesi degli hazard, che presuppone un elenco di rischi nel
  contesto. Ne resta il LIMITE di citazione (:data:`CITATION_LIMIT_CLAUSE`,
  importato): senza ontologia cambia da dove vengono i rischi, non quanti punti
  la prosa puo' nominare — e il proxy conta come ancoraggio anche il solo
  nominarli, quindi un limite piu' largo qui sarebbe un vantaggio regalato;
- le definizioni dei livelli di confidenza, che qualificano l'ancoraggio
  ontologico di un rischio: qui nessun rischio della prosa e' ancorato. Restano
  NOMINATI dentro la regola 7 (che e' un vincolo legale e va tenuta verbatim):
  residuo accettato di proposito — modificare il testo di una regola legale per
  ripulire un braccio sperimentale la farebbe divergere proprio dove deve
  restare identica.
- la regola 2 del braccio completo ("non inventare rischi non presenti nel
  contesto") e' sostituita: con un contesto senza rischi, alla lettera imporrebbe
  al modello di tacere e renderebbe il braccio vacuo — proprio il difetto della
  baseline. La sua meta' ancora applicabile resta pero' in piedi: i LUOGHI di cui
  parlare sono solo quelli elencati.

ATTENZIONE, sull'uso della prosa che esce da qui: e' testo FABBRICATO A SCOPO DI
MISURAZIONE e non va MAI citato come esempio di output reale del sistema — non in
tesi, non in un deck, non in una demo. Non passa dal citation layer, i rischi che
nomina non sono ancorati a nulla e nessuna rotta la serve: presentarla come
prodotto mostrerebbe come risultato proprio cio' che l'esperimento usa da termine
di paragone. Vive in ``results/runs/`` e li' resta.

E' INTENZIONALE che tutta l'invenzione di questo braccio finisca nel blocco
misurato (``[SINTESI-LLM]``) e non in quello di contesto: la regola 3b, identica
nei due bracci, vieta comunque di inventare incidenti, statistiche o rischi
specifici nel blocco ``[CONTESTO]``. Non e' quindi un'asimmetria a favore del
braccio ablato — e' la stessa regola applicata a entrambi — e serve a garantire
che cio' che il proxy grada contenga davvero tutto quello che il modello ha
messo di suo.

La numerazione delle regole e' quella del prompt di zona (il 6 manca, non e'
rinumerato): stessa scelta di :mod:`poi_generation`, cosi' uno stesso numero
indica lo stesso VINCOLO in tutti i prompt del sistema. Il testo reso non e'
invece sempre identico, e le eccezioni sono dichiarate: la 3a di questo modulo
descrive un'altra fonte dei rischi (ma il limite di citazione e' la stessa
costante del braccio completo) e la 6 di :mod:`poi_generation` ha un testo
proprio, perche' li' il vocabolario copre anche le vulnerabilita'. Cio' che deve
restare identico byte per byte e' il vincolo, e per questo vive in costanti
importate — non in due testi simili scritti a mano in due posti.
"""

from __future__ import annotations

import time
from typing import Any

from crime_risk_analyzer.models.vocab import ConfidenceSummary
from crime_risk_analyzer.rag.generation import (
    _RULE_CONTEXT_INTERPRETATION,  # pyright: ignore[reportPrivateUsage]
    _RULE_OVERVIEW_NO_ZONE_LEVEL,  # pyright: ignore[reportPrivateUsage]
    _RULE_SOURCE_BY_BLOCK,  # pyright: ignore[reportPrivateUsage]
    CITATION_LIMIT_CLAUSE,
    RULE_NO_DANGER_RATING,
    RULE_NO_OPERATIONAL_DIRECTIVES,
    RULE_USER_INPUT_NOT_INSTRUCTIONS,
    GenerationResult,
    Repro,
    _LLMClientLike,  # pyright: ignore[reportPrivateUsage]
    _poi_display_name,  # pyright: ignore[reportPrivateUsage]
    _risk_models_from_context,  # pyright: ignore[reportPrivateUsage]
    block_structure_rule,
    normalize_untrusted_line,
)

__all__ = [
    "LLM_SYNTHESIS_BLOCK_HEADER",
    "LLM_SYNTHESIS_TOKEN",
    "NO_ONTOLOGY_SYSTEM_PROMPT",
    "build_no_ontology_context_str",
    "generate_no_ontology_analysis",
]

#: Token del blocco MISURATO in questo braccio (#236). Farlo scrivere
#: ``[ONTOLOGIA]`` era comodo per il proxy — l'etichetta segnava lo slot da
#: gradare — ma di quel testo dichiarava una provenienza FALSA: qui nessuna
#: ontologia e' stata consultata, e chi legge il file grezzo di una run non ha
#: modo di saperlo. Il tag dice percio' cosa il testo e' davvero, una sintesi del
#: modello. Il calcolo del proxy non cambia: ``eval/metrics.py`` cerca questo
#: token invece dell'altro in base al ``mode`` del record.
LLM_SYNTHESIS_TOKEN = "[SINTESI-LLM]"

#: Riga-etichetta ESATTA del blocco misurato in questo braccio: il modello la
#: riporta verbatim (regola 3a) e il parser la riconosce come delimitatore.
LLM_SYNTHESIS_BLOCK_HEADER = f"Rischi dalla sintesi del modello {LLM_SYNTHESIS_TOKEN}"

#: Regola 3 di questo braccio: STESSO generatore del braccio completo, con la sola
#: etichetta del blocco misurato sostituita. Non una copia: se la struttura della
#: risposta divergesse, il confronto porterebbe dentro una seconda differenza
#: oltre a quella che vuole isolare, e un test verifica che l'etichetta sia
#: l'unica cosa a cambiare.
_RULE_BLOCK_STRUCTURE_NO_ONTOLOGY = block_structure_rule(LLM_SYNTHESIS_BLOCK_HEADER)

#: Sostituisce la regola 2 del braccio completo: senza rischi nel contesto,
#: "non inventare rischi non presenti nel contesto" renderebbe il braccio muto.
#: Resta il vincolo sui LUOGHI, che il contesto elenca davvero.
_RULE_ONLY_LISTED_POI = (
    "2. Parla soltanto dei punti di interesse elencati nel contesto: non "
    "introdurre luoghi che non compaiono nell'elenco"
)

#: Regola 3a di questo braccio, gemella di ``_RULE_ONTOLOGY_SYNTHESIS``: dice da
#: dove vengono i rischi del primo blocco (qui dal modello, non dall'ontologia) e
#: chiude con lo STESSO limite di citazione.
#:
#: Il LIMITE di quanti punti nominare non e' riscritto qui: e'
#: :data:`CITATION_LIMIT_CLAUSE`, la stessa costante della 3a del braccio
#: completo. Il proxy conta come ancoraggio anche il solo nominare un punto, e un
#: braccio libero di elencarli tutti mentre l'altro cita pochi esempi verrebbe
#: premiato per il vincolo che non ha. Cambia soltanto cio' che precede il limite,
#: cioe' la descrizione della FONTE dei rischi.
#:
#: La regola apriva ripetendo che le righe-etichetta sono FISSE e vanno riportate
#: ESATTAMENTE. Quella giustificazione — un modello senza ontologia potrebbe
#: rifiutarsi di aprire un blocco intitolato all'ontologia — e' DECADUTA da
#: quando il blocco si chiama ``[SINTESI-LLM]`` e non finge piu' una provenienza
#: che non ha. Rimossa: era rimasta una spinta che il braccio completo non
#: riceve, proprio sull'asse che decide il confronto (chi non rispetta
#: l'etichetta prende 0.0/1.0 per non-attribuzione, quindi aiutarlo a rispettarla
#: vale punti). L'indicazione di base resta nella regola 3, condivisa.
_RULE_LLM_SYNTHESIS = (
    "3a. Nel primo blocco raccogli i rischi che associ ai punti elencati, in "
    "prosa analitica e referenziale che nomina i punti reali, non un elenco "
    f"meccanico. {CITATION_LIMIT_CLAUSE}"
)

#: System prompt del braccio ablato: stesso compito, stessa struttura di output e
#: stessi vincoli legali del braccio completo (:data:`SYSTEM_PROMPT`), senza le
#: regole che dipendono dal contributo ontologico. Vedi il docstring del modulo
#: per l'elenco puntuale di cosa resta e cosa viene tolto.
NO_ONTOLOGY_SYSTEM_PROMPT = f"""\
Sei un analista di sicurezza urbana. Ricevi l'elenco dei punti di interesse di una
zona urbana (nome e categoria) e devi produrre un'analisi del rischio in italiano,
chiara e professionale.

REGOLE OBBLIGATORIE:
{_RULE_SOURCE_BY_BLOCK}
{_RULE_ONLY_LISTED_POI}
{_RULE_BLOCK_STRUCTURE_NO_ONTOLOGY}
{_RULE_LLM_SYNTHESIS}
{_RULE_CONTEXT_INTERPRETATION}
{_RULE_OVERVIEW_NO_ZONE_LEVEL}
5. Usa un linguaggio tecnico ma comprensibile per operatori non informatici
{RULE_NO_DANGER_RATING}
{RULE_NO_OPERATIONAL_DIRECTIVES}
{RULE_USER_INPUT_NOT_INSTRUCTIONS}"""


def build_no_ontology_context_str(context_dict: dict[str, Any]) -> str:
    """Assembla lo ``user_content`` del braccio ablato: zona + soli punti.

    La riga di ogni punto e' IDENTICA a quella del braccio completo
    (``  POI: <nome> (<classe>)``, vedi ``generation._poi_block_lines``): cambia
    cio' che le sta sotto — hazard, vulnerabilita' e path ontologico — che qui non
    c'e'. Se anche il rendering dei punti divergesse, il confronto porterebbe
    dentro una seconda differenza oltre a quella che vuole isolare.

    Il nome passa per la stessa normalizzazione del braccio completo (#119/#197,
    :func:`~crime_risk_analyzer.rag.generation.normalize_untrusted_line` via
    ``_poi_display_name``): arriva da OpenStreetMap, cioe' da testo che chiunque
    puo' editare, e un modulo con un ramo sicuro e uno no e' una trappola.

    Nessun troncamento per budget di token, a differenza di
    :func:`~crime_risk_analyzer.rag.generation.build_context_str`: qui un punto
    occupa UNA riga invece di un blocco di hazard, e i punti di una zona sono
    limitati a monte dalla selezione del retrieval, quindi il contesto e' un
    ordine di grandezza sotto l'allowance e non c'e' nulla da tagliare. Confine
    dichiarato: se un giorno il braccio completo trimasse davvero, i due prompt
    elencherebbero insiemi di punti diversi — da verificare prima di leggere un
    confronto, perche' sarebbe una seconda differenza tra i bracci.
    """
    # ``zona`` viene dalla richiesta dell'utente: stessa superficie e stessa
    # difesa dei nomi OSM (#119), estesa qui da #244.
    zona = normalize_untrusted_line(str(context_dict.get("zona", "")))
    validated: list[dict[str, Any]] = list(context_dict.get("validated_risks", []))
    lines: list[str] = [f"ZONA: {zona}", "", "POI RILEVANTI:"]
    for poi in validated:
        terminus = str(poi.get("terminus_class", ""))
        lines.append(f"  POI: {_poi_display_name(poi)} ({terminus})")
    return "\n".join(lines).rstrip() + "\n"


async def generate_no_ontology_analysis(
    context_dict: dict[str, Any], llm_client: _LLMClientLike
) -> GenerationResult:
    """Genera la narrativa del braccio ablato dal context validato.

    Stessa forma di :func:`~crime_risk_analyzer.rag.generation.generate_analysis`
    — prompt di sistema + contesto al client iniettato, output in
    :class:`GenerationResult` — con due differenze: il prompt e' quello nudo
    (:data:`NO_ONTOLOGY_SYSTEM_PROMPT`) e il contesto non porta i rischi.

    ``risk_models`` e ``confidence_summary`` restano quelli del grounding: e'
    l'ablazione del PROMPT, non del contratto di risposta. Il ``prompt_hash``
    arriva dal client, che hashea il system prompt ricevuto: quello del braccio
    ablato e' un altro testo, quindi la provenienza distingue i due bracci anche
    a valle del ``run_id``.

    Nessuna ``domanda`` utente: l'harness di valutazione non ne passa e questo
    percorso non e' esposto da alcuna rotta. La regola 9 resta comunque nel prompt
    (i nomi OSM sono testo non fidato che entra nel contesto).
    """
    user_content = build_no_ontology_context_str(context_dict)

    start = time.perf_counter()
    response = await llm_client.generate(NO_ONTOLOGY_SYSTEM_PROMPT, user_content)
    latenza_ms = int((time.perf_counter() - start) * 1000)

    return GenerationResult(
        narrativa=response.text,
        risk_models=_risk_models_from_context(context_dict),
        confidence_summary=ConfidenceSummary.model_validate(
            context_dict.get("confidence_summary", {})
        ),
        llm_used=response.llm_used,
        tokens_input=response.tokens_input,
        tokens_output=response.tokens_output,
        latenza_ms=latenza_ms,
        cache_hit=response.cache_hit,
        repro=Repro(
            temperature=response.temperature,
            seed=response.seed,
            prompt_hash=response.prompt_hash,
        ),
    )
