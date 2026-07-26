import pytest

from crime_risk_analyzer.eval.metrics import (
    METRICS_VERSION,
    compute_metrics,
    cost_usd_of,
    grounding,
    hallucination,
    latency_ms,
)
from crime_risk_analyzer.models.vocab import ConfidenceSummary
from crime_risk_analyzer.orchestrator import AnalyzeResponse, PoiOut
from crime_risk_analyzer.rag.generation import Repro, RiskItem, RiskModel


def _resp(
    narrativa: str,
    *,
    with_citation: bool = True,
    tokens: tuple[int, int] = (10, 20),
) -> AnalyzeResponse:
    return AnalyzeResponse(
        citta="Roma",
        zona_normalizzata="Centro",
        poi=[
            PoiOut(
                id="1",
                name="Banca A",
                terminus_class="Bank",
                lat=41.0,
                lon=12.0,
                confidence="verificato",
                sparql_path=(
                    "Bank → havingHazard → Bank_robbery" if with_citation else None
                ),
            )
        ],
        risk_models=[
            RiskModel(
                poi="Banca A",
                risks=[
                    RiskItem(
                        hazard="Bank_robbery",
                        confidence="verificato",
                        tag="ONTOLOGIA",
                    )
                ],
            )
        ],
        narrativa=narrativa,
        confidence_summary=ConfidenceSummary(verificato=1),
        llm_used="claude-sonnet-4-6",
        latenza_ms=120,
        repro=Repro(temperature=0.0, seed=0, prompt_hash="ph"),
        cache_hit=False,
        fallback=False,
        # Valore finto: qui si misurano le metriche sulla narrativa, l'impronta
        # del contesto (#242) e' irrilevante e un letterale lo dichiara.
        contesto_hash="h-ctx",
        tokens_input=tokens[0],
        tokens_output=tokens[1],
    )


# #229 (M1): la narrativa reale e' strutturata a BLOCCHI (#196), con il tag di fonte
# nell'HEADER e non inline per frase. I test usano quindi la forma a blocchi reale
# (prima usavano tag inline, che non rispecchia l'output prodotto dal prompt).
# ``parse_source_prose`` isola il corpo del blocco [ONTOLOGIA] — l'unico layer con
# backing strutturato dal grounding e quindi l'unico gradato dal proxy M1. Overview e
# [CONTESTO] sono interpretazione: NON gradabili dal proxy deterministico (la loro
# qualita'/fabbricazione va al gold umano #109/#152, ed e' frenata a monte dal prompt).
def _narrativa(
    ontologia: str,
    *,
    overview: str = "Sintesi della zona.",
    contesto: str | None = None,
) -> str:
    text = f"{overview}\n\nRischi da ontologia [ONTOLOGIA]\n{ontologia}"
    if contesto is not None:
        text += f"\n\nRischi dal contesto [CONTESTO]\n{contesto}"
    return text


def test_metrics_version_is_m1_generation() -> None:
    # #229: bump di versione della semantica proxy (v1 inline-tag -> v2 block-aware
    # M1). Serve a compare.py/winner.py per non mescolare generazioni di metrica.
    assert METRICS_VERSION == 2


def test_grounding_full_when_ontology_sentence_backed() -> None:
    r = _resp(_narrativa("Banca A presenta rischio rapina."))
    assert grounding(r) == 1.0
    assert hallucination(r) == 0.0


def test_ontology_sentence_without_anchor_is_hallucination() -> None:
    # Invariante #109 PRESERVATO DENTRO il layer con backing: una frase nel blocco
    # [ONTOLOGIA] che asserisce un rischio senza ancoraggio reale (Museo X/incendio
    # non sono POI/hazard del contesto) e' fabbricazione -> hallucination.
    r = _resp(_narrativa("Il Museo X presenta rischio incendio."))
    assert hallucination(r) == 1.0
    assert grounding(r) == 0.0


def test_context_pure_interpretation_is_excluded_not_hallucination() -> None:
    # #229 (correzione all'over-penalizzazione): l'interpretazione pura in [CONTESTO]
    # (nessun ancoraggio) NON e' gradata dal proxy. Qui l'unico blocco gradato e'
    # [ONTOLOGIA] (ancorato) -> grounding 1.0, la prosa contestuale non abbassa il
    # punteggio. (Sotto il proxy v1 inline-tag questa narrativa a blocchi scoreva 0.)
    r = _resp(
        _narrativa(
            "Banca A presenta rischio rapina.",
            contesto="La zona ha carattere prevalentemente commerciale.",
        )
    )
    assert grounding(r) == 1.0
    assert hallucination(r) == 0.0


def test_context_fabrication_is_delegated_to_gold_not_flagged_by_proxy() -> None:
    # #229 (cambio semantico ESPLICITO rispetto a #109): una fabbricazione nel blocco
    # [CONTESTO] (Museo Z inventato) NON e' rilevata dal proxy deterministico —
    # [CONTESTO] e' interpretazione, la cui fabbricazione e' delegata al gold umano
    # (#152) e frenata a monte dal prompt (regola 2 + [CONTESTO] "senza inventare").
    # Il proxy grada solo [ONTOLOGIA]: qui l'ontologia e' ancorata -> grounding 1.0.
    r = _resp(
        _narrativa(
            "Banca A presenta rischio rapina.",
            contesto="Il Museo Z rischia gravi incendi ogni notte.",
        )
    )
    assert grounding(r) == 1.0
    assert hallucination(r) == 0.0


def test_overview_and_headers_excluded_from_grading() -> None:
    # overview e righe-header non sono asserzioni ontologiche: escluse dal proxy.
    # Anche se l'overview nomina un'entita' non reale, non conta come hallucination.
    r = _resp(
        _narrativa(
            "Banca A presenta rischio rapina.",
            overview="Il Museo Y domina la zona.",
        )
    )
    assert grounding(r) == 1.0
    assert hallucination(r) == 0.0


def test_sparse_ontology_grounding_is_fraction() -> None:
    # blocco [ONTOLOGIA] con 2 frasi: 1 ancorata + 1 non ancorata -> 0.5.
    r = _resp(
        _narrativa("Banca A presenta rischio rapina.\nIl Museo X rischia incendi.")
    )
    assert grounding(r) == pytest.approx(0.5)
    assert hallucination(r) == pytest.approx(0.5)


def test_filler_in_ontology_block_counts_as_ungrounded() -> None:
    # #229 (cambio rispetto a #163): sotto M1 il blocco [ONTOLOGIA] deve essere
    # referenziale (citare i dati). Una frase-filler NEL blocco che non ancora nulla
    # abbassa la groundedness (non e' piu' esclusa dal denominatore): incoraggia una
    # sintesi ancorata, coerente con "piu' valore per parola" (#229).
    r = _resp(
        _narrativa(
            "Banca A presenta rischio rapina.\n"
            "La sicurezza urbana e' un tema importante."
        )
    )
    assert grounding(r) == pytest.approx(0.5)
    assert hallucination(r) == pytest.approx(0.5)


def test_hallucination_is_complement_of_grounding_on_ontology() -> None:
    r = _resp(
        _narrativa(
            "Banca A presenta rischio rapina.\nIl Museo X rischia incendi.\n"
            "Banca A e' esposta a furto."
        )
    )
    assert hallucination(r) == pytest.approx(1.0 - grounding(r))


def test_empty_narrativa_is_vacuously_grounded() -> None:
    r = _resp("", tokens=(0, 0))
    assert grounding(r) == 1.0
    assert hallucination(r) == 0.0


def test_nonempty_narrative_without_ontology_block_is_penalized() -> None:
    # #229 (fix anti-gaming): una narrativa PIENA con dati da citare ma SENZA blocco
    # [ONTOLOGIA] riconoscibile (modello non compliant: tutto in overview / header
    # omesso) NON e' "vacuamente ancorata" -> e' NON-ATTRIBUZIONE: grounding 0.0 /
    # hallucination 1.0. Cosi' un modello (o una risposta evasiva/fabbricante) non
    # ottiene un punteggio perfetto omettendo l'header — l'asse hallucination e' il
    # criterio PRIMARIO di winner.py (#157): l'evasione perde invece di vincere.
    r = _resp("La zona presenta alcuni rischi generici e gravi pericoli inventati.")
    assert grounding(r) == 0.0
    assert hallucination(r) == 1.0


def test_no_anchors_is_vacuous_nothing_to_cite() -> None:
    # Ramo vacuo per "niente da citare": nessun ancoraggio disponibile (poi/risk_models
    # vuoti, es. zona senza POI recuperati) -> il proxy non ha dati contro cui gradare
    # -> grounding 1.0 / hallucination 0.0. Distinto dalla non-attribuzione sopra (li'
    # i dati da citare c'erano). Gli anchors non sono controllabili dal modello (vengono
    # dalla pipeline), quindi questo ramo non e' gameable.
    r = _resp(_narrativa("Qualcosa accade nella zona.")).model_copy(
        update={"poi": [], "risk_models": []}
    )
    assert grounding(r) == 1.0
    assert hallucination(r) == 0.0


def test_empty_poi_name_does_not_anchor_everything() -> None:
    # Regressione review #163 (I1): un POI senza nome (name="") NON deve rendere
    # "ancorata" ogni frase. Una frase [ONTOLOGIA] fabbricata resta hallucination.
    r = _resp(_narrativa("Il Museo X presenta rischio incendio."))
    nameless = PoiOut(
        id="2",
        name="",
        terminus_class="Bank",
        lat=41.0,
        lon=12.0,
        confidence="verificato",
        sparql_path=None,
    )
    r = r.model_copy(update={"poi": [*r.poi, nameless]})
    assert hallucination(r) == 1.0
    assert grounding(r) == 0.0


def test_latency_passthrough() -> None:
    assert latency_ms(_resp("x")) == 120


def test_compute_metrics_cost() -> None:
    m = compute_metrics(
        _resp(_narrativa("Banca A presenta rischio rapina."), tokens=(1_000_000, 0))
    )
    assert m.cost_usd == pytest.approx(3.0)
    assert 0.0 <= m.grounding <= 1.0


def test_cost_usd_of_zero_when_no_llm() -> None:
    r = _resp(
        _narrativa("Banca A presenta rischio rapina."), tokens=(1_000_000, 0)
    ).model_copy(update={"llm_used": ""})
    assert cost_usd_of(r) == 0.0
