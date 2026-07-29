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
from crime_risk_analyzer.rag.generation import (
    RULE_NO_DANGER_RATING,
    RULE_NO_OPERATIONAL_DIRECTIVES,
    RULE_USER_INPUT_NOT_INSTRUCTIONS,
    Repro,
    SourceProse,
    _LLMClientLike,  # pyright: ignore[reportPrivateUsage]
    normalize_untrusted_line,
    parse_source_prose,
)
from crime_risk_analyzer.rag.grounding import GroundedRisk
from crime_risk_analyzer.rag.poi_context import NeighbourPoi

__all__ = [
    "POI_SYSTEM_PROMPT",
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
    # della domanda utente). Il resto del contesto viene dall'ontologia o da
    # etichette del vocabolario controllato: non e' testo non fidato.
    lines = [
        f"Citta': {citta}",
        f"Zona: {zona}",
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
) -> PoiGenerationResult:
    """Genera la narrativa del POI: prompt POI + contesto -> client LLM.

    Nessun budget di trim (#210): il contesto di un POI e' un ordine di
    grandezza piu' piccolo di quello di zona (un punto e cinque vicini contro
    fino a venti POI con tutti i loro rischi), quindi non c'e' nulla da
    troncare. ``max_tokens`` resta quello del client iniettato.
    """
    user_content = build_poi_context_str(
        citta=citta,
        zona=zona,
        poi_name=poi_name,
        poi_label_it=poi_label_it,
        risks=risks,
        vulnerabilities=vulnerabilities,
        sparql_path=sparql_path,
        neighbours=neighbours,
        zone_summary=zone_summary,
    )
    start = time.perf_counter()
    response = await llm_client.generate(POI_SYSTEM_PROMPT, user_content)
    latenza_ms = int((time.perf_counter() - start) * 1000)
    return PoiGenerationResult(
        narrativa=response.text,
        narrativa_fonti=parse_source_prose(response.text),
        llm_used=response.llm_used,
        tokens_input=response.tokens_input,
        tokens_output=response.tokens_output,
        latenza_ms=latenza_ms,
        repro=Repro(
            temperature=response.temperature,
            seed=response.seed,
            prompt_hash=response.prompt_hash,
        ),
    )
