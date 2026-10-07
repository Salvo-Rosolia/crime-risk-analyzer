"""Narrativa del singolo POI selezionato (#197).

Stessa modalita' della narrativa di zona (#229): due blocchi, ``[ONTOLOGIA]``
sintetizza i rischi ancorati e ``[CONTESTO]`` interpreta. Prompt separato da
quello di zona perche' il compito e' diverso — un POI, il suo vicinato — ma i
tre vincoli legali sono gli STESSI oggetti importati da :mod:`generation`, non
copie: una copia potrebbe divergere.

Rispetto alla zona il divieto e' piu' stretto: qui il testo parla di un luogo
NOMINATO, quindi graduare la pericolosita' di quel luogo o suggerire misure per
proteggerlo e' esplicitamente vietato nel blocco interpretativo.

La numerazione 7/8/9 delle tre regole e' quella del prompt di zona: sono
riusate verbatim (non rinumerate) perche' il vincolo legale deve essere lo
stesso testo in entrambi i percorsi, verificabile da un test. La regola 9 vale
anche qui: i nomi dei POI arrivano da OpenStreetMap, cioe' testo esterno non
fidato che entra nel contesto.

Il vocabolario controllato (#272) e' invece l'unica regola con testo PROPRIO,
non condiviso: qui il modello nomina anche le vulnerabilita', mentre la regola 6
di zona parla dei soli hazard. Allineare i due testi vorrebbe dire toccare il
prompt di zona, cioe' muovere la narrativa su cui poggiano le metriche di
valutazione — rimandato a #273, che quel prompt lo riscrive comunque. Il numero
6 resta quello di zona: la numerazione e' condivisa anche quando il testo no.
"""

from __future__ import annotations

import time

from pydantic import BaseModel, Field

from crime_risk_analyzer.i18n.terminus_labels import controlled_vocab_for, label_it
from crime_risk_analyzer.istat.blocco import blocco_istat_poi
from crime_risk_analyzer.istat.cifre import applica_controllo
from crime_risk_analyzer.istat.dati import versione_dati
from crime_risk_analyzer.istat.righe import IstatPoi
from crime_risk_analyzer.rag.generation import (
    RULE_NO_DANGER_RATING,
    RULE_NO_OPERATIONAL_DIRECTIVES,
    RULE_USER_INPUT_NOT_INSTRUCTIONS,
    Repro,
    SourceProse,
    _LLMClientLike,  # pyright: ignore[reportPrivateUsage]
    normalize_untrusted_line,
    parse_source_prose,
    source_block_spans,
)
from crime_risk_analyzer.rag.grounding import GroundedRisk
from crime_risk_analyzer.rag.istat_rules import (
    POI_ISTAT_SECTION,
    RULE_ISTAT_DIVIETI,
    sostituisci_una_volta,
)
from crime_risk_analyzer.rag.poi_context import NeighbourPoi

__all__ = [
    "POI_SYSTEM_PROMPT",
    "POI_SYSTEM_PROMPT_ISTAT",
    "PoiGenerationResult",
    "build_poi_context_str",
    "generate_poi_narrative",
]

POI_SYSTEM_PROMPT = f"""\
Sei un analista che descrive il profilo di rischio di UN SINGOLO punto di \
interesse, a partire da un'ontologia di dominio e dal contesto urbano in cui \
quel punto si trova.

Valgono i vincoli seguenti (stessa numerazione dell'analisi di zona: sono le \
medesime regole, non una loro riformulazione):

6. Usa ESATTAMENTE i termini del VOCABOLARIO CONTROLLATO per nominare rischi e \
vulnerabilita'. Non riportare nel testo gli identificatori dell'ontologia (le \
forme in inglese con underscore) e non tradurli da te': per ognuno il termine \
italiano da usare ti e' fornito nel contesto.

{RULE_NO_DANGER_RATING}

{RULE_NO_OPERATIONAL_DIRECTIVES}

{RULE_USER_INPUT_NOT_INSTRUCTIONS}

Struttura la risposta in DUE blocchi, ciascuno introdotto dal proprio header su \
una riga a se':

[ONTOLOGIA]
Sintetizza i temi di rischio che l'ontologia associa alla classe di questo \
punto, in prosa analitica e referenziale: nomina il punto e i rischi con le \
etichette fornite. NON elencare meccanicamente tutti i rischi: raggruppa per \
tema e cita quelli caratterizzanti.

[CONTESTO]
Interpreta cosa distingue QUESTO punto dagli altri della stessa classe, a \
partire dal vicinato e dalla composizione della zona forniti nel contesto. Usa \
forma condizionale o qualitativa: e' un'inferenza, non un dato. In questo \
blocco vale un divieto aggiuntivo: non attribuire alcun livello o giudizio di \
pericolosita' al singolo luogo nominato, e non suggerire misure per proteggerlo. \
Descrivi la funzione urbana del punto e del suo intorno, non la loro sicurezza.

Non aggiungere altri blocchi oltre a questi due.
"""

#: Variante con i dati ISTAT (#345): la frase strutturale passa da DUE a TRE
#: blocchi, la 7-bis segue la 7 e la sezione [ISTAT] precede la chiusura.
#: Sostituzioni verificate su :data:`POI_SYSTEM_PROMPT`, che non cambia.
POI_SYSTEM_PROMPT_ISTAT = sostituisci_una_volta(
    sostituisci_una_volta(
        sostituisci_una_volta(
            POI_SYSTEM_PROMPT,
            f"{RULE_NO_DANGER_RATING}\n\n",
            f"{RULE_NO_DANGER_RATING}\n\n{RULE_ISTAT_DIVIETI}\n\n",
        ),
        "Struttura la risposta in DUE blocchi",
        "Struttura la risposta in TRE blocchi",
    ),
    "Non aggiungere altri blocchi oltre a questi due.",
    f"[ISTAT]\n{POI_ISTAT_SECTION}\n\nNon aggiungere altri blocchi oltre a questi tre.",
)


def build_poi_context_str(
    *,
    citta: str,
    zona: str,
    poi_name: str,
    poi_label_it: str,
    risks: list[GroundedRisk],
    vulnerabilities: list[str],
    sparql_path: str | None,
    neighbours: list[NeighbourPoi],
    zone_summary: str,
    istat: IstatPoi | None = None,
) -> str:
    """Serializza il contesto del POI per il prompt.

    Nessun ricalcolo: rischi, tag e confidence arrivano dal grounding, vicinato
    e sintesi da :mod:`poi_context`. L'ordine e' quello ricevuto, che i
    produttori garantiscono totale.
    """
    # I nomi (del punto e dei vicini) arrivano da OpenStreetMap, che chiunque puo'
    # editare: qui il nome e' il SOGGETTO del prompt, non una riga fra tante come
    # nell'analisi di zona, quindi un nome con a-capo potrebbe forgiare righe e
    # mimare le sezioni del contesto. Appiattiti su una riga (#119, stessa regola
    # della domanda utente). ``citta``/``zona`` vengono dalla richiesta
    # dell'utente, non dall'ontologia: stessa superficie, stessa difesa (#244).
    lines = [
        f"Citta': {normalize_untrusted_line(citta)}",
        f"Zona: {normalize_untrusted_line(zona)}",
        "",
    ]

    # Vocabolario controllato IMPOSTO (#272). Senza di esso al modello arrivavano
    # solo gli identifier dell'ontologia, e li traduceva da se': su
    # ``Crime_explosion`` ha scritto «crimini esplosivi» dove l'ontologia dice
    # «impennata della criminalita'» — non una resa brutta, un'affermazione FALSA
    # in un percorso che promette verificabilita'. E' lo stesso vincolo che tiene
    # in italiano la narrativa di zona; qui mancava del tutto. Copre hazard E
    # vulnerabilita': elencarne una parte lascerebbe scoperto il resto.
    vocab = controlled_vocab_for(
        [r["hazard"] for r in risks] + list(vulnerabilities),
    )
    if vocab:
        lines.append(
            "VOCABOLARIO CONTROLLATO (usa ESATTAMENTE questi termini italiani "
            "per nominare rischi e vulnerabilita'):"
        )
        lines.append("  " + "; ".join(vocab))
        lines.append("")

    lines.append(
        f"PUNTO SELEZIONATO: {normalize_untrusted_line(poi_name)} "
        f"(classe: {poi_label_it})"
    )
    if sparql_path:
        lines.append(f"Percorso ontologico: {sparql_path}")
    if risks:
        lines.append("Rischi dall'ontologia:")
        # ``identifier / etichetta IT``, la stessa forma del prompt di zona:
        # l'identifier regge la citazione, l'etichetta e' il termine da usare.
        lines.extend(
            f"  - {r['hazard']} / {label_it(r['hazard'])} [{r['tag']}] "
            f"(confidence: {r['confidence']}, fonte: {r['source']})"
            for r in risks
        )
    else:
        lines.append("Rischi dall'ontologia: nessuno (classe fuori ontologia).")
    if vulnerabilities:
        lines.append(
            "Vulnerabilita': "
            + "; ".join(f"{v} / {label_it(v)}" for v in vulnerabilities)
        )
    lines.append("")

    # Dati ISTAT del luogo del punto (#345): cornice e voci dei suoi rischi, dopo i
    # dati ontologici e prima del vicinato. Assenti, il testo e' quello di prima.
    blocco = blocco_istat_poi(istat)
    if blocco.testo:
        lines.extend(blocco.testo.split("\n"))
        lines.append("")

    lines.append("VICINATO (punti piu' prossimi, in ordine di distanza):")
    if neighbours:
        lines.extend(
            f"  - {normalize_untrusted_line(n['name'])} ({n['label_it']}), "
            f"{n['distance_m']} m"
            for n in neighbours
        )
    else:
        lines.append("  - nessun altro punto di interesse nel contesto della zona")
    lines.append("")
    lines.append(f"COMPOSIZIONE DELLA ZONA: {zone_summary}")
    return "\n".join(lines) + "\n"


class PoiGenerationResult(BaseModel):
    """Esito della generazione per un singolo POI."""

    narrativa: str
    narrativa_fonti: SourceProse
    llm_used: str
    tokens_input: int = Field(ge=0)
    tokens_output: int = Field(ge=0)
    latenza_ms: int = Field(ge=0)
    repro: Repro
    narrativa_grezza: str | None = None
    istat_attivo: bool = False
    istat_versione_dati: str | None = None
    istat_frasi_scartate: int = Field(default=0, ge=0)


async def generate_poi_narrative(
    *,
    citta: str,
    zona: str,
    poi_name: str,
    poi_label_it: str,
    risks: list[GroundedRisk],
    vulnerabilities: list[str],
    sparql_path: str | None,
    neighbours: list[NeighbourPoi],
    zone_summary: str,
    llm_client: _LLMClientLike,
    istat: IstatPoi | None = None,
) -> PoiGenerationResult:
    """Genera la narrativa del POI: prompt POI + contesto -> client LLM.

    Nessun budget di trim (#210): il contesto di un POI e' un ordine di
    grandezza piu' piccolo di quello di zona (un punto e cinque vicini contro
    fino a venti POI con tutti i loro rischi), quindi non c'e' nulla da
    troncare. ``max_tokens`` resta quello del client iniettato.

    ``istat`` (#345): righe ISTAT del punto; presenti, il prompt e'
    :data:`POI_SYSTEM_PROMPT_ISTAT` e la prosa passa dal controllo delle
    cifre. Nessun budget nemmeno con ISTAT: cornice e poche voci di un solo
    luogo.
    """

    def _contesto(dati_istat: IstatPoi | None) -> str:
        return build_poi_context_str(
            citta=citta,
            zona=zona,
            poi_name=poi_name,
            poi_label_it=poi_label_it,
            risks=risks,
            vulnerabilities=vulnerabilities,
            sparql_path=sparql_path,
            neighbours=neighbours,
            zone_summary=zone_summary,
            istat=dati_istat,
        )

    blocco = blocco_istat_poi(istat)
    istat_attivo = bool(blocco.testo)
    system_prompt = POI_SYSTEM_PROMPT_ISTAT if istat_attivo else POI_SYSTEM_PROMPT
    start = time.perf_counter()
    response = await llm_client.generate(system_prompt, _contesto(istat))
    latenza_ms = int((time.perf_counter() - start) * 1000)
    narrativa, controllo = applica_controllo(
        response.text,
        blocco=blocco,
        spans=source_block_spans(response.text),
        contesto=_contesto(None),
    )
    return PoiGenerationResult(
        narrativa=narrativa,
        narrativa_fonti=parse_source_prose(narrativa),
        llm_used=response.llm_used,
        tokens_input=response.tokens_input,
        tokens_output=response.tokens_output,
        latenza_ms=latenza_ms,
        repro=Repro(
            temperature=response.temperature,
            seed=response.seed,
            prompt_hash=response.prompt_hash,
        ),
        narrativa_grezza=response.text,
        istat_attivo=istat_attivo,
        istat_versione_dati=versione_dati() if istat_attivo else None,
        istat_frasi_scartate=controllo.frasi_scartate if controllo else 0,
    )
