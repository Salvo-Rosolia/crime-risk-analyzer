from typing import get_args

import pytest

from crime_risk_analyzer.eval import compare, harness, metrics
from crime_risk_analyzer.eval.metrics import (
    _MEASURED_TOKEN_BY_MODE,  # pyright: ignore[reportPrivateUsage]
    METRICS_VERSION,
    FrasiEscluseIncoerentiError,
    RiskAnchoring,
    _measured_spans,  # pyright: ignore[reportPrivateUsage]
    compute_metrics,
    cost_usd_of,
    frasi_escluse_m1,
    grounding,
    hallucination,
    hazards_cited_in,
    latency_ms,
    risk_anchoring,
)
from crime_risk_analyzer.eval.schema import ExperimentConfig, Mode, RunCase, RunRecord
from crime_risk_analyzer.istat.blocco import blocco_istat_poi
from crime_risk_analyzer.istat.cifre import controlla_cifre
from crime_risk_analyzer.models.vocab import ConfidenceSummary
from crime_risk_analyzer.orchestrator import AnalyzeResponse, PoiOut, ZonaGeo
from crime_risk_analyzer.rag.generation import (
    Repro,
    RiskItem,
    RiskModel,
    source_block_spans,
)
from crime_risk_analyzer.rag.no_ontology_generation import LLM_SYNTHESIS_BLOCK_HEADER
from tests.istat._fattorie import RAPINE_IN_BANCA, istat_poi, riga


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
                poi_id="1",
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
        # Idem per la geo della zona (#260): irrilevante per le metriche testate qui.
        zona_geo=ZonaGeo(
            lat=41.0,
            lon=12.0,
            bbox_min_lat=40.9,
            bbox_min_lon=11.9,
            bbox_max_lat=41.1,
            bbox_max_lon=12.1,
        ),
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


def test_a_poi_named_after_the_tag_does_not_corrupt_the_graded_block() -> None:
    # Il prompt chiede di nominare i punti reali e i nomi arrivano da OSM, dove
    # chiunque puo' chiamare un locale "Bar [ONTOLOGIA] Fake". Citato nella
    # sintesi iniziale, il taglio per fonte si ancorava dentro quella frase: nel
    # blocco gradato finivano l'intestazione vera e la prosa di overview, cioe'
    # la metrica di questo esperimento misurava un altro testo (0.5/0.5 invece
    # di 1.0/0.0). Il blocco gradato deve essere quello che il modello ha aperto.
    r = _resp(
        _narrativa(
            "Banca A presenta rischio rapina.",
            overview="In zona spicca il Bar [ONTOLOGIA] Fake, molto frequentato.",
        )
    )
    assert grounding(r) == 1.0
    assert hallucination(r) == 0.0


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


def test_hazards_cited_in_returns_the_lowercased_measured_block() -> None:
    narrativa = (
        "Overview.\n\n[ONTOLOGIA]\nLa zona presenta Rapina al viaggiatore "
        "vicino alla stazione."
    )
    block = hazards_cited_in(narrativa, "analyze")
    assert "rapina al viaggiatore" in block
    assert "attacco informatico" not in block


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


# --- #236: il blocco gradato dipende dal braccio, non il calcolo --------------


def _narrativa_sintesi_llm(corpo: str) -> str:
    """Narrativa del braccio ablato: stesso corpo, etichetta di blocco onesta.

    Quel braccio non ha consultato alcuna ontologia, quindi non intitola il
    blocco all'ontologia (vedi ``rag/no_ontology_generation.py``).
    """
    return f"Sintesi della zona.\n\n{LLM_SYNTHESIS_BLOCK_HEADER}\n{corpo}"


def test_the_ablated_arm_is_graded_on_its_own_block_label() -> None:
    """Stesso testo, etichette diverse, stesso punteggio.

    Cambia SOLO quale riga-etichetta il proxy cerca, in base al ``mode`` della
    run: se il punteggio cambiasse, il confronto tra i due bracci misurerebbe
    l'etichetta invece dell'ancoraggio.
    """
    corpo = "Banca A presenta rischio rapina.\nIl Museo X rischia incendi."
    ablato = _resp(_narrativa_sintesi_llm(corpo))
    completo = _resp(_narrativa(corpo))
    assert grounding(ablato, mode="no_ontology_prompt") == pytest.approx(0.5)
    assert hallucination(ablato, mode="no_ontology_prompt") == pytest.approx(0.5)
    assert grounding(ablato, mode="no_ontology_prompt") == grounding(completo)
    assert hallucination(ablato, mode="no_ontology_prompt") == hallucination(completo)


def test_the_complete_arm_is_still_graded_on_the_ontology_label() -> None:
    """Non-regressione: per ``analyze`` il blocco gradato resta [ONTOLOGIA].

    Il ``mode`` di default e' il braccio storico, cosi' ogni chiamata scritta
    prima di #236 misura esattamente quello che misurava.
    """
    r = _resp(_narrativa("Banca A presenta rischio rapina."))
    assert grounding(r, mode="analyze") == 1.0
    assert grounding(r) == 1.0
    assert hallucination(r) == 0.0


def test_the_label_of_the_other_arm_does_not_open_the_graded_block() -> None:
    """L'etichetta e' per braccio: quella dell'altro non apre il blocco.

    Una run ablata che scrivesse comunque ``[ONTOLOGIA]`` (modello non
    compliant) ricade nella NON-ATTRIBUZIONE come qualunque risposta priva del
    blocco atteso: 0.0/1.0. Stesso trattamento dell'header omesso (#229), quindi
    non c'e' un'etichetta «di comodo» che paghi.
    """
    r = _resp(_narrativa("Banca A presenta rischio rapina."))
    assert grounding(r, mode="no_ontology_prompt") == 0.0
    assert hallucination(r, mode="no_ontology_prompt") == 1.0


def test_compute_metrics_grades_the_block_of_the_given_arm() -> None:
    """Il ``mode`` arriva fino all'assemblaggio delle quattro metriche."""
    r = _resp(_narrativa_sintesi_llm("Banca A presenta rischio rapina."))
    assert compute_metrics(r, mode="no_ontology_prompt").grounding == 1.0
    # Senza il mode giusto la stessa run risulterebbe non attribuita.
    assert compute_metrics(r).grounding == 0.0


def test_compute_metrics_quality_vacuous_true_on_empty_narrativa() -> None:
    """#240: il marcatore di vacuita' distingue il ramo vacuo (nulla da giudicare)."""
    r = _resp("", tokens=(0, 0))
    assert compute_metrics(r).quality_vacuous is True


def test_compute_metrics_quality_vacuous_false_on_graded_narrativa() -> None:
    """Una narrativa gradabile (con o senza attribuzione) non e' vacua."""
    grounded = _resp(_narrativa("Banca A presenta rischio rapina."))
    assert compute_metrics(grounded).quality_vacuous is False
    non_attribuita = _resp(
        "La zona presenta alcuni rischi generici e gravi pericoli inventati."
    )
    assert compute_metrics(non_attribuita).quality_vacuous is False


def test_every_mode_declares_the_block_the_proxy_grades() -> None:
    """Un braccio nuovo non puo' entrare senza dire su cosa viene misurato.

    Il ``mode`` decide quale blocco il proxy grada: se la mappa restasse
    indietro, la nuova modalita' verrebbe misurata sull'etichetta di un'altra e
    prenderebbe 0.0/1.0 per non attribuzione, in silenzio.
    """
    assert set(get_args(Mode)) == set(_MEASURED_TOKEN_BY_MODE)


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


# --- M1 con i dati ISTAT nel prompt (#345, #368, #369) ---------------------------

_BLOCCO_ISTAT = blocco_istat_poi(istat_poi(riga(), RAPINE_IN_BANCA))
_ANCORATA = "Banca A: rapina in banca."
_NON_ANCORATA = "La zona e' molto affollata."
_ISTAT = "Secondo l'ISTAT nel Comune di Roma i furti sono in calo."


def _resp_istat(grezzo: str, *, poi: str = "Banca A") -> AnalyzeResponse:
    """Risposta con i dati ISTAT nel prompt: ``grezzo`` e' il testo del modello,
    la narrativa quella filtrata dal controllo (come in ``generate_analysis``)."""
    esito = controlla_cifre(
        grezzo,
        blocchi=source_block_spans(grezzo),
        blocco_istat=_BLOCCO_ISTAT.testo,
        contesto_senza_istat="ZONA: Colosseo",
        righe=_BLOCCO_ISTAT.righe,
    )
    resp = _resp(esito.testo_filtrato)
    return resp.model_copy(
        update={
            "narrativa_grezza": grezzo,
            "controllo_istat": esito,
            "poi": [resp.poi[0].model_copy(update={"name": poi})],
            "risk_models": [resp.risk_models[0].model_copy(update={"poi": poi})],
        }
    )


def _m1(resp: AnalyzeResponse) -> tuple[float, float, bool | None]:
    m = compute_metrics(resp)
    return (m.grounding, m.hallucination, m.quality_vacuous)


def test_senza_istat_nessuna_frase_esclusa() -> None:
    assert frasi_escluse_m1(_resp(_narrativa(f"{_ANCORATA} {_ISTAT}"))) is None


def test_m1_istat_esclude_le_frasi_istat_senza_poi_ne_rischio() -> None:
    """#369: la frase ISTAT che non nomina un POI ne' un rischio esce dal
    denominatore; la frase non ancorata senza parole da ISTAT resta."""
    resp = _resp_istat(_narrativa(f"{_ANCORATA} {_NON_ANCORATA} {_ISTAT}"))
    assert _m1(resp) == (0.5, 0.5, False)
    assert frasi_escluse_m1(resp) == [_ISTAT.rstrip(".")]


@pytest.mark.parametrize(
    "ancorata",
    [
        "Secondo l'ISTAT nel Comune di Roma i furti vicino a Banca A sono in calo.",
        "Secondo l'ISTAT nel Comune di Roma la rapina in banca ha un tasso piu' alto.",
    ],
)
def test_m1_istat_misura_la_frase_istat_che_nomina_un_poi_o_un_rischio(
    ancorata: str,
) -> None:
    """#369: con un POI o un rischio la frase ISTAT si misura come le altre."""
    resp = _resp_istat(_narrativa(f"{_ANCORATA} {_NON_ANCORATA} {ancorata}"))
    assert compute_metrics(resp).grounding == pytest.approx(2 / 3)
    assert frasi_escluse_m1(resp) == []


def test_m1_istat_blocco_fatto_solo_di_frasi_istat_e_non_attribuzione() -> None:
    """Nessuna frase misurata resta: il blocco non attribuisce rischi ai punti,
    come un blocco vuoto (grounding 0, allucinazione 1), non un caso vuoto."""
    resp = _resp_istat(_narrativa(f"{_ISTAT} Il tasso dei furti e' piu' alto."))
    # ancoraggi presenti (Banca A, rapina in banca) e tutte le frasi escluse
    assert frasi_escluse_m1(resp) == [
        _ISTAT.rstrip("."),
        "Il tasso dei furti e' piu' alto",
    ]
    assert _m1(resp) == (0.0, 1.0, False)


def test_m1_istat_senza_poi_ne_rischi_e_vacuo_e_non_esclude_nulla() -> None:
    """Review #369: senza ancoraggi M1 e' vacuo e non grada nulla, quindi non
    esclude nulla. Prima ogni frase ISTAT risultava esclusa e il record lo
    dichiarava per una zona non gradata."""
    resp = _resp_istat(_narrativa(f"{_ANCORATA} {_ISTAT}")).model_copy(
        update={"poi": [], "risk_models": []}
    )
    assert _m1(resp) == (1.0, 0.0, True)
    assert frasi_escluse_m1(resp) == []


def test_m1_istat_narrativa_vuota_e_vacua_e_non_esclude_nulla() -> None:
    resp = _resp_istat("")
    assert _m1(resp) == (1.0, 0.0, True)
    assert frasi_escluse_m1(resp) == []


def test_m1_istat_senza_intestazione_e_solo_frasi_istat_e_non_attribuzione() -> None:
    """#369: prima il testo senza le frasi ISTAT restava vuoto e valeva come caso
    vuoto, con punteggio perfetto. La narrativa c'e': e' non attribuzione."""
    resp = _resp_istat(f"{_ISTAT}\n")
    assert _m1(resp) == (0.0, 1.0, False)


@pytest.mark.parametrize(
    ("corpo", "esclusa"),
    [
        # "ecc." non chiude la frase per il filtro, per M1 si'
        (f"Banca A: rapina in banca, scippi ecc. {_ISTAT}", _ISTAT.rstrip(".")),
        # punto seguito da asterischi o da una parentesi: idem
        (f"**Banca A**: rapina in banca.** {_ISTAT}", f"** {_ISTAT.rstrip('.')}"),
        (f"Banca A (rapina in banca.) {_ISTAT}", f") {_ISTAT.rstrip('.')}"),
        # il punto esclamativo chiude la frase per il filtro, per M1 no
        (
            f"{_ANCORATA} La zona e' affollata! {_ISTAT}",
            f"La zona e' affollata! {_ISTAT.rstrip('.')}",
        ),
    ],
)
def test_m1_istat_esclude_frasi_di_m1(corpo: str, esclusa: str) -> None:
    """#369: le frasi escluse sono quelle di M1, divise come M1 le divide."""
    resp = _resp_istat(_narrativa(corpo))
    assert frasi_escluse_m1(resp) == [esclusa]
    assert _m1(resp) == (1.0, 0.0, False)


@pytest.mark.parametrize(
    "introduzione",
    [
        "I dati ISTAT del Comune di Roma (2024) indicano:",
        # tolta dal filtro: i furti sono in calo
        "I dati ISTAT del Comune di Roma (2024) indicano furti in aumento:",
    ],
)
def test_m1_istat_il_luogo_ereditato_non_dipende_dal_filtro(introduzione: str) -> None:
    """#369: la riga d'elenco eredita il luogo anche da un'introduzione tolta."""
    resp = _resp_istat(_narrativa(f"{_ANCORATA}\n{introduzione}\n- furti: in calo;"))
    assert frasi_escluse_m1(resp) == [introduzione, "- furti: in calo;"]
    assert _m1(resp) == (1.0, 0.0, False)


@pytest.mark.parametrize("tendenza", ["in calo", "in aumento"])
def test_m1_istat_misura_la_frase_ancorata_dopo_qualunque_frase_istat(
    tendenza: str,
) -> None:
    """#369, il caso della revisione: prima la frase ancorata dopo una frase ISTAT
    giusta (che passa il luogo) era tagliata, dopo una sbagliata restava."""
    istat = f"Secondo l'ISTAT nel Comune di Roma i furti sono {tendenza}."
    resp = _resp_istat(_narrativa(f"{istat} Vicino a Banca A i furti sono in calo."))
    assert frasi_escluse_m1(resp) == [istat.rstrip(".")]
    assert _m1(resp) == (1.0, 0.0, False)


def test_m1_istat_limite_un_rischio_inventato_a_parole_da_istat_e_escluso() -> None:
    """Limite dichiarato (#369): un rischio che non e' nella base di conoscenza,
    scritto con le parole del dato ISTAT, esce dal denominatore invece di contare
    come non ancorato. Il record lo conserva fra le frasi escluse."""
    inventato = (
        "Secondo i dati ISTAT nel Comune di Roma i sequestri di persona crescono"
    )
    resp = _resp_istat(_narrativa(f"{_ANCORATA} {inventato}."))
    assert frasi_escluse_m1(resp) == [inventato]
    assert _m1(resp) == (1.0, 0.0, False)


def test_m1_istat_misura_il_grezzo_senza_ritoccarlo() -> None:
    """#369: le frasi misurate sono quelle del grezzo, non di un testo riscritto
    (prima il taglio comprimeva gli spazi doppi e il nome del POI non si trovava
    piu')."""
    nome = "Bar  Centrale"
    resp = _resp_istat(_narrativa(f"{nome}: borseggi. {_ISTAT}"), poi=nome)
    assert _m1(resp) == (1.0, 0.0, False)


def test_m1_istat_uguale_con_a_capo_crlf() -> None:
    lf = _narrativa(f"{_ANCORATA}\n{_ISTAT}\n\n- furti: in calo;")
    crlf = lf.replace("\n", "\r\n")
    assert _m1(_resp_istat(crlf)) == _m1(_resp_istat(lf)) == (0.5, 0.5, False)
    assert frasi_escluse_m1(_resp_istat(crlf)) == frasi_escluse_m1(_resp_istat(lf))


def test_m1_istat_grada_il_grezzo_non_il_filtrato() -> None:
    """Il filtro toglie la frase con un numero inventato, M1 la misura (#345)."""
    resp = _resp_istat(_narrativa(f"{_ANCORATA} Si stimano 999 episodi l'anno."))
    assert "999" not in (resp.narrativa or "")
    assert _m1(resp) == (0.5, 0.5, False)
    assert grounding(resp) == 0.5 and hallucination(resp) == 0.5


def test_m1_istat_grezzo_svuotato_dal_filtro_e_non_attribuzione() -> None:
    """Il filtro toglie l'unica frase (i furti sono in calo): la narrativa
    mostrata e' vuota, ma il modello ha scritto. M1 guarda il grezzo, quindi e'
    non attribuzione e non il caso vuoto con punteggio perfetto."""
    resp = _resp_istat("Secondo l'ISTAT nel Comune di Roma i furti sono in aumento.\n")
    assert (resp.narrativa or "").strip() == ""
    assert _m1(resp) == (0.0, 1.0, False)


def test_m1_istat_l_elenco_numerato_finisce_come_quello_a_trattini() -> None:
    """#369, B1 e B-1: M1 stacca "1" da "1. furti: in calo;". Quel numero non
    deve interrompere l'elenco ne' prolungarlo (la frase dopo l'elenco, che non
    parla del dato, resta misurata) e segue la voce: escluso con lei, non contato
    come asserzione non ancorata. Numerato e a trattini danno lo stesso M1."""
    introduzione = "I dati ISTAT del Comune di Roma (2024) indicano:"
    dopo = "La zona e' affollata e i furti sono in calo"

    def resp(primo: str, secondo: str) -> AnalyzeResponse:
        return _resp_istat(
            _narrativa(
                f"{_ANCORATA}\n{introduzione}\n{primo} furti: in calo;\n"
                f"{secondo} furti: sopra la media italiana\n{dopo}."
            )
        )

    numerato, trattini = resp("1.", "2."), resp("-", "-")
    assert frasi_escluse_m1(numerato) == [
        introduzione,
        "1",
        "furti: in calo;",
        "2",
        "furti: sopra la media italiana",
    ]
    assert frasi_escluse_m1(trattini) == [
        introduzione,
        "- furti: in calo;",
        "- furti: sopra la media italiana",
    ]
    # misurate in entrambi: Banca A (ancorata) e la frase dopo l'elenco
    assert _m1(numerato) == _m1(trattini) == (0.5, 0.5, False)


def test_m1_istat_la_prosa_sulla_riga_etichetta_passa_il_luogo() -> None:
    """#369, C2: M1 non misura la prosa scritta sulla riga-etichetta, ma il luogo
    che nomina vale per l'elenco che segue, come per il filtro."""
    grezzo = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA] I dati ISTAT del Comune di "
        f"Roma (2024) indicano:\n- furti: in calo;\n{_ANCORATA}\n"
    )
    resp = _resp_istat(grezzo)
    assert frasi_escluse_m1(resp) == ["- furti: in calo;"]
    assert _m1(resp) == (1.0, 0.0, False)


def test_m1_istat_la_prosa_sulla_riga_etichetta_non_e_mai_esclusa() -> None:
    """#369, C2: contratto di ``frasi_istat_m1``. La prosa sulla riga-etichetta
    passa il luogo ma non e' una frase di M1: non compare fra gli intervalli del
    controllo ne' fra le frasi escluse, anche quando parla del dato."""
    prosa = "Secondo l'ISTAT nel Comune di Roma i furti sono in calo"
    grezzo = (
        f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA] {prosa}. I dati ISTAT del "
        f"Comune di Roma (2024) indicano:\n- furti: in calo;\n{_ANCORATA}\n"
    )
    resp = _resp_istat(grezzo)
    assert resp.controllo_istat is not None
    inizio_blocco = grezzo.index("\n", grezzo.index("[ONTOLOGIA]")) + 1
    intervalli = resp.controllo_istat.frasi_istat_m1
    assert intervalli and all(a >= inizio_blocco for a, _ in intervalli)
    escluse = frasi_escluse_m1(resp)
    assert escluse is not None
    assert escluse == ["- furti: in calo;"]
    assert not any(prosa in e or "indicano" in e for e in escluse)


def test_m1_istat_senza_grezzo_solleva() -> None:
    """#369, C3: gli offset delle frasi ISTAT sono quelli del grezzo; senza il
    grezzo M1 non ripiega in silenzio sulla narrativa filtrata."""
    resp = _resp_istat(_narrativa(f"{_ANCORATA} {_ISTAT}")).model_copy(
        update={"narrativa_grezza": None}
    )
    with pytest.raises(ValueError, match="narrativa_grezza"):
        compute_metrics(resp)
    with pytest.raises(ValueError, match="narrativa_grezza"):
        frasi_escluse_m1(resp)


# --- Parita' fra le frasi di M1 e quelle del controllo ISTAT (#369) -------------
#
# M1 (``_measured_spans``) e il controllo (``EsitoControllo.frasi_istat_m1``)
# devono dividere lo stesso blocco nelle stesse frasi: se divergessero, gli
# intervalli del controllo non coinciderebbero con nessuna frase di M1 e nessuna
# frase sarebbe esclusa, senza errore.

#: Narrative in cui OGNI frase di M1 del blocco misurato nomina ISTAT: le frasi
#: ISTAT del controllo devono essere esattamente le frasi di M1.
_TUTTE_ISTAT = [
    _narrativa("Per l'ISTAT a Roma i furti sono in calo."),
    _narrativa("Secondo l'ISTAT scippi ecc. Per l'ISTAT a Roma i furti calano."),
    _narrativa("**Per l'ISTAT a Roma furti in calo.** Per l'ISTAT anche rapine."),
    _narrativa("Per l'ISTAT a Roma (furti in calo.) Per l'ISTAT rapine stabili."),
    _narrativa("Per l'ISTAT a Roma furti in calo! Per l'ISTAT rapine. Ecco l'ISTAT"),
    _narrativa(
        "I dati ISTAT di Roma:\n- ISTAT, furti: in calo;\n\n1. ISTAT, rapine: ok"
    ),
    _narrativa("Per l'ISTAT a Roma furti in calo.\nPer l'ISTAT rapine.").replace(
        "\n", "\r\n"
    ),
    "Sintesi.\n\n**Rischi da ontologia [ONTOLOGIA]**\nPer l'ISTAT a Roma furti.\n"
    "\nRischi dal contesto [CONTESTO]\nPer l'ISTAT a Roma furti.\n",
    "Sintesi.\n\nRischi dal contesto [CONTESTO]\nPer l'ISTAT a Roma furti.\n\n"
    "Rischi da ontologia [ONTOLOGIA]\nPer l'ISTAT a Roma. Per l'ISTAT rapine.\n",
    "Sintesi.\n\nRischi da ontologia [ONTOLOGIA] I dati ISTAT di Roma:\n"
    "- per l'ISTAT, furti: in calo;\n",
]

#: Narrative dei test di questo modulo, con frasi ISTAT e non: le frasi ISTAT del
#: controllo sono un sottoinsieme delle frasi di M1.
_MISTE = [
    _narrativa(f"{_ANCORATA} {_NON_ANCORATA} {_ISTAT}"),
    _narrativa(f"Banca A: rapina in banca, scippi ecc. {_ISTAT}"),
    _narrativa(f"**Banca A**: rapina in banca.** {_ISTAT}"),
    _narrativa(f"Banca A (rapina in banca.) {_ISTAT}"),
    _narrativa(f"{_ANCORATA} La zona e' affollata! {_ISTAT}"),
    _narrativa(
        f"{_ANCORATA}\nI dati ISTAT del Comune di Roma (2024) indicano:\n"
        "1. furti: in calo;\n2. furti: sopra la media italiana\n"
        "La zona e' affollata e i furti sono in calo."
    ),
    _narrativa(f"{_ANCORATA}\n{_ISTAT}\n\n- furti: in calo;").replace("\n", "\r\n"),
    _narrativa(f"{_ANCORATA} Si stimano 999 episodi l'anno."),
    f"{_ISTAT}\n",
]


def _frasi_m1_e_istat(
    grezzo: str,
) -> tuple[list[tuple[int, int]], tuple[tuple[int, int], ...]]:
    resp = _resp_istat(grezzo)
    assert resp.controllo_istat is not None
    return _measured_spans(grezzo, "analyze"), resp.controllo_istat.frasi_istat_m1


@pytest.mark.parametrize("grezzo", _TUTTE_ISTAT)
def test_parita_frasi_di_m1_e_del_controllo(grezzo: str) -> None:
    misurate, istat = _frasi_m1_e_istat(grezzo)
    assert misurate, "il corpus deve avere un blocco misurato non vuoto"
    assert list(istat) == misurate


@pytest.mark.parametrize("grezzo", _MISTE)
def test_frasi_istat_del_controllo_sono_frasi_di_m1(grezzo: str) -> None:
    misurate, istat = _frasi_m1_e_istat(grezzo)
    assert set(istat) <= set(misurate)


# --- Ancoraggio ai rischi sul testo misurato da M1 con ISTAT (#377) ---------------


def _record_istat(resp: AnalyzeResponse) -> RunRecord:
    """Il record che l'harness scrive per ``resp`` (grezzo e frasi escluse)."""
    return harness._record_from_response(  # pyright: ignore[reportPrivateUsage]
        run_id="r",
        snapshot_id="s",
        config=ExperimentConfig(
            name="istat", mode="analyze", model="groq", cases=[], istat=True
        ),
        case=RunCase(citta="Roma", zona="Colosseo"),
        model_id="m",
        resp=resp,
        code_commit="a",
        ontology_hash="b",
        snapshot_catturato_il=None,
        snapshot_configurazione_canonica=None,
    )


def _ancoraggio_dal_record(resp: AnalyzeResponse) -> RiskAnchoring | None:
    """La sezione del confronto sul record scritto dall'harness."""
    return compare._record_anchoring(  # pyright: ignore[reportPrivateUsage]
        _record_istat(resp)
    )


@pytest.mark.parametrize(
    "grezzo",
    [
        *_MISTE,
        _narrativa(f"{_ISTAT} Il tasso dei furti e' piu' alto."),
        _narrativa(f"{_ANCORATA} {_ISTAT} {_ISTAT}"),
    ],
)
def test_ancoraggio_dal_record_istat_ripartisce_le_frasi_di_m1(grezzo: str) -> None:
    """#377: grezzo meno le frasi escluse salvate = le asserzioni di M1."""
    resp = _resp_istat(grezzo)
    graded = metrics._grade(resp, "analyze")  # pyright: ignore[reportPrivateUsage]
    r = _ancoraggio_dal_record(resp)
    assert graded is not None and r is not None
    if r.frasi_misurate:
        assert (
            r.frasi_ancorate_rischio + r.frasi_ancorate_solo_poi,
            r.frasi_misurate,
        ) == graded
    else:
        # Senza blocco, o con il blocco fatto solo di frasi ISTAT escluse: M1 lo
        # conta non attribuzione, l'ancoraggio ai rischi vale 0.
        assert graded == (0, 1)
        assert r.ancoraggio_rischi == 0.0


def test_ancoraggio_dal_record_senza_frasi_escluse_misura_il_grezzo() -> None:
    """#377: lista di esclusione vuota ma narrativa filtrata diversa dal grezzo
    (il controllo toglie una cifra non ISTAT): si misurano le frasi di M1, cioe'
    il grezzo, non la narrativa mostrata."""
    resp = _resp_istat(_narrativa(f"{_ANCORATA} Si stimano 999 episodi l'anno."))
    record = _record_istat(resp)
    assert record.frasi_escluse_m1 == []
    assert record.narrativa != record.narrativa_grezza
    graded = metrics._grade(resp, "analyze")  # pyright: ignore[reportPrivateUsage]
    r = _ancoraggio_dal_record(resp)
    assert r is not None
    assert (r.frasi_ancorate_rischio + r.frasi_ancorate_solo_poi, r.frasi_misurate) == (
        graded
    )
    assert r.frasi_misurate == 2


def test_blocco_di_sole_frasi_istat_escluse_e_conforme() -> None:
    """Il formato c'e': non e' una narrativa non conforme, solo senza frasi."""
    r = _ancoraggio_dal_record(
        _resp_istat(_narrativa(f"{_ISTAT} Il tasso dei furti e' piu' alto."))
    )
    assert r == RiskAnchoring(0, 0, 0, conforme=True)


def test_ancoraggio_con_frasi_escluse_toglie_una_frase_per_voce() -> None:
    testo = _narrativa(f"{_ANCORATA} {_NON_ANCORATA} {_NON_ANCORATA}")
    r = risk_anchoring(
        testo,
        mode="analyze",
        poi_names=["Banca A"],
        risk_models=[],
        frasi_escluse=[_NON_ANCORATA.rstrip(".")],
    )
    assert r == RiskAnchoring(2, 0, 1, conforme=True)


def test_ancoraggio_frase_esclusa_assente_dal_blocco_solleva() -> None:
    with pytest.raises(FrasiEscluseIncoerentiError, match="frase esclusa"):
        risk_anchoring(
            _narrativa(_ANCORATA),
            mode="analyze",
            poi_names=["Banca A"],
            risk_models=[],
            frasi_escluse=["Frase che non c'e'"],
        )
