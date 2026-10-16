# ruff: noqa: E501
"""Controllo delle cifre (#345, spec 4.7): tabella di casi tenere/togliere."""

from __future__ import annotations

import re
from decimal import Decimal

import pytest

from crime_risk_analyzer.istat.blocco import (
    BloccoIstat,
    blocco_istat_poi,
    blocco_istat_zona,
)
from crime_risk_analyzer.istat.cifre import (
    EsitoControllo,
    Motivo,
    Numero,
    SpanBlocco,
    applica_controllo,
    confronto_di,
    controlla_cifre,
    direzione_di,
    dividi_frasi,
    dividi_frasi_m1,
    estrai_numeri,
)
from crime_risk_analyzer.istat.righe import (
    MOTIVO_ROTTURA_2016,
    MOTIVO_SOTTO_SOGLIA,
    IstatPoi,
    RigaIstat,
)
from crime_risk_analyzer.rag.generation import (
    USER_INPUT_FENCE_CLOSE,
    USER_INPUT_FENCE_OPEN,
)
from tests.istat._fattorie import collegamento, cornice, istat_poi, riga

_FURTI = riga()
_DANNI = riga(
    "DAMAGE",
    label="danneggiamenti",
    delitti=19843,
    confronto=16417,
    tasso=721.2,
    italia=471.5,
    variazione=None,
    motivo=MOTIVO_ROTTURA_2016,
)
_RAPINE = riga(
    "SHOPROB",
    label="rapine in esercizi commerciali",
    delitti=812,
    confronto=701,
    tasso=29.5,
    italia=13.1,
    variazione=16,
)
_ISTAT = istat_poi(_FURTI, _DANNI, _RAPINE)
_BLOCCO = blocco_istat_poi(_ISTAT)
_CONTESTO = (
    "ZONA: Colosseo\n\nPOI RILEVANTI:\n  POI: Bar 2000 (Bank)\n"
    "NB: per limiti di lunghezza sono analizzati i 12 POI piu' rilevanti su 20; "
    "gli altri sono comunque in mappa e nella lista."
)
_INTESTAZIONI = {
    "ontologia": "Rischi da ontologia [ONTOLOGIA]",
    "contesto": "Rischi dal contesto [CONTESTO]",
    "speculativo": "Ipotesi speculative [SPECULATIVO]",
    "istat": "Dati statistici ISTAT [ISTAT]",
}
_TOKEN = {
    "ontologia": "[ONTOLOGIA]",
    "contesto": "[CONTESTO]",
    "speculativo": "[SPECULATIVO]",
    "istat": "[ISTAT]",
}


def _spans(testo: str) -> list[SpanBlocco]:
    """Intestazioni come le trova il parser (Task 10), qui senza importarlo."""
    trovati: list[tuple[str, int, int]] = []
    for campo, token in _TOKEN.items():
        i = testo.find(token)
        if i < 0:
            continue
        nl = testo.find("\n", i)
        trovati.append(
            (campo, testo.rfind("\n", 0, i) + 1, len(testo) if nl < 0 else nl + 1)
        )
    trovati.sort(key=lambda t: t[1])
    return [
        SpanBlocco(c, a, b, trovati[k + 1][1] if k + 1 < len(trovati) else len(testo))
        for k, (c, a, b) in enumerate(trovati)
    ]


def _controlla(testo: str) -> EsitoControllo:
    return controlla_cifre(
        testo,
        blocchi=_spans(testo),
        blocco_istat=_BLOCCO.testo,
        contesto_senza_istat=_CONTESTO,
        righe=_BLOCCO.righe,
    )


_CIFRA: Motivo = "cifra_istat_fuori_blocco"

_CASI: list[tuple[str, str, Motivo | None]] = [
    # #365 D3: nessun blocco e' piu' il posto delle cifre ISTAT. Una cifra ISTAT
    # toglie la frase ovunque, anche dentro un [ISTAT] scritto per errore.
    (
        "istat",
        "Nel Comune di Roma i furti denunciati nel 2024 sono 134.169 (fonte ISTAT, Comune di Roma, 2024).",
        _CIFRA,
    ),
    (
        "istat",
        "I furti sono 4.876,4 ogni 100.000 abitanti contro 1.788,7 in Italia (fonte ISTAT, Comune di Roma, 2024).",
        _CIFRA,
    ),
    (
        "istat",
        "Le rapine in esercizi commerciali sono in aumento del +16% tra il 2014 e il 2024 (fonte ISTAT, Comune di Roma, 2024).",
        _CIFRA,
    ),
    ("istat", "Il totale dei delitti denunciati e' 217.536 nel 2024.", _CIFRA),
    ("istat", "Nel 2024 si contano 19.843 casi.", _CIFRA),
    ("ontologia", "Il Colosseo concentra 134.169 furti.", _CIFRA),
    ("contesto", "La zona ha 4.876,4 visitatori.", _CIFRA),
    (
        "speculativo",
        "Forse i furti potrebbero essere collegati ai 134.169 casi denunciati.",
        _CIFRA,
    ),
    (
        "ontologia",
        "Secondo i dati ISTAT del Comune di Roma i furti sono 134.169.",
        _CIFRA,
    ),
    # formati equivalenti: sempre la stessa cifra ISTAT
    ("ontologia", "I furti sono 134169 nel 2024.", _CIFRA),
    ("ontologia", "I furti sono 134 169 nel 2024.", _CIFRA),
    ("ontologia", "I furti sono 134\xa0169 nel 2024.", _CIFRA),
    ("ontologia", "I furti sono 134 169 nel 2024.", _CIFRA),
    ("ontologia", "I furti sono 4876.4 ogni 100.000 abitanti.", _CIFRA),
    ("ontologia", "Le rapine in esercizi commerciali calano del -16%.", _CIFRA),
    ("ontologia", "Le rapine in esercizi commerciali variano del –16%.", _CIFRA),
    # arrotondamenti e numeri inventati: il motivo resta il primo
    (
        "ontologia",
        "I furti sono circa 134.000 (fonte ISTAT, Comune di Roma, 2024).",
        "numero_non_ammesso",
    ),
    ("ontologia", "I furti sono 4.876 ogni 100.000 abitanti.", "numero_non_ammesso"),
    ("ontologia", "Nel 2023 i furti erano 134.169.", "numero_non_ammesso"),
    ("ontologia", "Tre banche su 9 sono esposte.", "numero_non_ammesso"),
    # anni, periodo e numeri del contesto restano ammessi
    ("ontologia", "I dati coprono il periodo 2014-2024.", None),
    ("ontologia", "I dati coprono il periodo 2014\u20132024.", None),
    # C3: una frase in un [ISTAT] residuo parla sempre del dato, quindi vuole il luogo
    ("istat", "I dati coprono il periodo 2014-2024.", "luogo_mancante"),
    ("istat", "Nel Comune di Roma i dati coprono il periodo 2014-2024.", None),
    # B1: "livello"/"valore" nazionale non fanno parlare di ISTAT
    (
        "ontologia",
        "Il Colosseo e' un luogo di interesse a livello nazionale esposto a furti.",
        None,
    ),
    ("contesto", "La zona attira flussi di livello nazionale.", None),
    # B2: le parole di confronto contano solo vicino al termine di paragone
    ("ontologia", "Secondo l'ISTAT a Roma i furti e reati simili sono in calo.", None),
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma i furti al piano superiore sono in calo.",
        None,
    ),
    (
        "ontologia",
        "In linea con l'ontologia, secondo l'ISTAT nel Comune di Roma i furti hanno un tasso più basso di quello italiano.",
        "confronto_contrario",
    ),
    (
        "ontologia",
        "In linea con l'ontologia, secondo l'ISTAT nel Comune di Roma i furti hanno un tasso più alto di quello italiano.",
        None,
    ),
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma i furti sono al di sopra della media italiana.",
        None,
    ),
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma i furti hanno un tasso maggiore di quello italiano.",
        None,
    ),
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma i furti hanno un tasso più contenuto di quello italiano.",
        "confronto_contrario",
    ),
    # due classi nella stessa frase: non verificabile, si toglie
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma i furti sono sopra la media italiana e i danneggiamenti sotto la media italiana.",
        "confronto_contrario",
    ),
    # C1: la voce si risolve dal nome del rischio collegato
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma il furto di beni ha un tasso più basso di quello italiano.",
        "confronto_contrario",
    ),
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma il furto di beni ha un tasso più alto di quello italiano.",
        None,
    ),
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma il furto di beni e' in calo.",
        # C-1: il furto di beni e' collegato a furti (in calo), danneggiamenti (senza
        # tendenza) e rapine in esercizi commerciali (in crescita): vale per tutte
        "direzione_contraria",
    ),
    # nessuna voce nemmeno dai rischi: confronto o tendenza non verificabili
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma il fenomeno ha un tasso più alto di quello italiano.",
        "confronto_contrario",
    ),
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma il fenomeno e' in calo.",
        "direzione_contraria",
    ),
    ("ontologia", "Tra i 12 POI analizzati, Bar 2000 e' esposto a rapina.", None),
    ("ontologia", "1. Rischio di rapina per Bar 2000.", None),
    # una variazione e' una cifra ISTAT solo col '%': "10 anni" e' il periodo
    (
        "ontologia",
        "Nel Comune di Roma il totale dei delitti denunciati e' cambiato negli ultimi 10 anni.",
        None,
    ),
    # #365 D3 (a): una frase che parla del dato ISTAT nomina un luogo delle righe
    (
        "ontologia",
        "Secondo i dati ISTAT i furti hanno un tasso piu' alto di quello italiano.",
        "luogo_mancante",
    ),
    (
        "ontologia",
        "Secondo i dati ISTAT del Comune di Roma, i furti hanno un tasso più alto di quello italiano e sono in calo dal 2014 (voce più ampia del rischio).",
        None,
    ),
    ("ontologia", "Per l'ISTAT a Roma i furti sono sopra la media italiana.", None),
    ("ontologia", "I furti sono sotto la media nazionale.", "luogo_mancante"),
    ("ontologia", "Rispetto all'Italia i furti sono in calo.", "luogo_mancante"),
    ("ontologia", "Rispetto all’Italia i furti sono in calo.", "luogo_mancante"),
    ("ontologia", "I delitti denunciati per furti sono in calo.", "luogo_mancante"),
    ("ontologia", "Secondo l'ISTAT i furti sono in aumento.", "luogo_mancante"),
    (
        "speculativo",
        "Forse i delitti denunciati di furti sono in aumento.",
        "luogo_mancante",
    ),
    (
        "ontologia",
        "Il totale dei delitti denunciati e' stabile negli ultimi 10 anni.",
        "luogo_mancante",
    ),
    # R1 (review 2): il solo nome del luogo non fa parlare di ISTAT una frase,
    # nemmeno con parole di confronto o di direzione
    (
        "ontologia",
        "Nel Comune di Roma i furti sono piu' alti nelle zone turistiche.",
        None,
    ),
    ("contesto", "Nel Comune di Roma i furti sono in aumento.", None),
    (
        "ontologia",
        "Il furto di beni domina la zona e i furti sono in aumento per la folla.",
        None,
    ),
    ("ontologia", "A Roma la folla aumenta le occasioni di furti nelle scuole.", None),
    ("ontologia", "La visibilita' ridotta favorisce i danneggiamenti a Roma.", None),
    ("contesto", "Le sale giochi di Roma attirano furti.", None),
    ("contesto", "Bar 2000 e' esposto a furti di notte.", None),
    # #365 D3 (b): il confronto concorda con la classificazione della riga
    # (furti, danneggiamenti e rapine del fixture: tutti "piu' alto")
    (
        "ontologia",
        "Secondo i dati ISTAT del Comune di Roma, i furti hanno un tasso più basso di quello italiano.",
        "confronto_contrario",
    ),
    (
        "ontologia",
        "Secondo l'ISTAT, a Roma i furti sono inferiori alla media nazionale.",
        "confronto_contrario",
    ),
    (
        "ontologia",
        "Secondo l'ISTAT, a Roma i danneggiamenti sono in linea con il dato nazionale.",
        "confronto_contrario",
    ),
    (
        "contesto",
        "Secondo l'ISTAT, a Roma i danneggiamenti sono superiori alla media italiana.",
        None,
    ),
    ("overview", "Nel Comune di Roma i furti sono sopra la media italiana.", None),
    # D7: anche il totale ha il suo confronto (piu' alto nel fixture)
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma il totale dei delitti e' piu' alto della media italiana.",
        None,
    ),
    (
        "ontologia",
        "Secondo l'ISTAT, nel Comune di Roma il totale dei delitti e' piu' basso della media italiana.",
        "confronto_contrario",
    ),
    # direzione contraria al segno (o senza tendenza calcolata)
    (
        "ontologia",
        "Secondo i dati ISTAT del Comune di Roma, le rapine in esercizi commerciali mostrano un calo.",
        "direzione_contraria",
    ),
    (
        "ontologia",
        "Secondo l'ISTAT nel Comune di Roma le rapine in esercizi commerciali sono scese.",
        "direzione_contraria",
    ),
    (
        "ontologia",
        "Secondo l'ISTAT nel Comune di Roma i danneggiamenti sono in aumento.",
        "direzione_contraria",
    ),
    (
        "contesto",
        "Nel Comune di Roma i delitti denunciati per furti sono in aumento.",
        "direzione_contraria",
    ),
    (
        "istat",
        "I furti sono in crescita (fonte ISTAT, Comune di Roma, 2024).",
        "direzione_contraria",
    ),
]


@pytest.mark.parametrize(("blocco", "frase", "atteso"), _CASI)
def test_tabella_dei_casi(blocco: str, frase: str, atteso: Motivo | None) -> None:
    testo = (
        f"{frase}\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n"
        if blocco == "overview"
        else f"Sintesi.\n\n{_INTESTAZIONI[blocco]}\n{frase}\n"
    )
    frasi = [f for f in _controlla(testo).frasi if f.blocco == blocco]
    assert len(frasi) == 1
    assert frasi[0].motivo == atteso


def test_intestazione_istat_mancante_toglie_le_cifre_nella_sintesi() -> None:
    testo = (
        "Sintesi. Nel Comune di Roma i furti sono 134.169 (fonte ISTAT, Comune di Roma, 2024).\n\n"
        "Rischi da ontologia [ONTOLOGIA]\nRischio rapina.\n"
    )
    esito = _controlla(testo)
    assert [(f.blocco, f.motivo) for f in esito.frasi] == [
        ("overview", None),
        ("overview", "cifra_istat_fuori_blocco"),
        ("intestazione", None),
        ("ontologia", None),
    ]
    assert (
        esito.testo_filtrato
        == "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRischio rapina.\n"
    )
    assert esito.frasi_scartate == 1


def test_direzione_contraria_fuori_dal_blocco_istat() -> None:
    """Fix round 1 - importante 2, raffinato da F5 (review finale): fuori da
    ``[ISTAT]`` la direzione si controlla quando la frase parla dei dati ISTAT."""
    testo = (
        "Sintesi: secondo l'ISTAT i furti sono in forte aumento.\n\n"
        "Rischi da ontologia [ONTOLOGIA]\nSecondo i dati ISTAT nel Comune di Roma i furti sono in forte aumento.\n"
    )
    esito = _controlla(testo)
    # #365: la sintesi parla di ISTAT senza luogo, si toglie prima per quello.
    assert [(f.blocco, f.motivo) for f in esito.frasi] == [
        ("overview", "luogo_mancante"),
        ("intestazione", None),
        ("ontologia", "direzione_contraria"),
    ]


def test_filtro_toglie_righe_rimaste_col_solo_marcatore() -> None:
    testo = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n"
        "1. Il Colosseo concentra 134.169 furti.\n2. Rischio rapina per Bar 2000.\n"
    )
    assert _controlla(testo).testo_filtrato == (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n2. Rischio rapina per Bar 2000.\n"
    )


@pytest.mark.parametrize(
    "testo",
    [
        "  Bar 2000: rapina, scippi ecc. Secondo l'ISTAT!\r\n- furti.** In calo.)\n\n",
        "Nessun punto",
        "",
        " . \n.\t\n",
        "1. Prima voce.\n2. Seconda (d.lgs. 7/2016) e 3.016 furti.",
    ],
)
def test_dividi_frasi_m1_e_lo_splitter_di_m1(testo: str) -> None:
    """#369: le frasi di M1 (#229) con gli offset: si spezza a ogni punto e a ogni
    a-capo, senza spazi ai bordi e senza frasi vuote, come faceva M1."""
    attese = [s.strip() for s in re.split(r"[.\n]", testo) if s.strip()]
    assert [testo[a:b] for a, b in dividi_frasi_m1(testo)] == attese


def test_dividi_frasi_m1_dentro_un_intervallo() -> None:
    testo = "Sintesi. Altro.\nBar 2000: rapina. Scippi.\nCoda."
    inizio = testo.index("Bar")
    fine = testo.index("Coda")
    assert [testo[a:b] for a, b in dividi_frasi_m1(testo, inizio, fine)] == [
        "Bar 2000: rapina",
        "Scippi",
    ]


def _frasi_istat_m1(testo: str, esito: EsitoControllo) -> list[str]:
    return [testo[a:b] for a, b in esito.frasi_istat_m1]


def test_frasi_istat_m1_sono_frasi_di_m1_del_blocco_misurato() -> None:
    """#369: le frasi ISTAT per M1 sono divise come le divide M1, non come il
    filtro: "ecc." non chiude la frase per il filtro ma per M1 si'. Solo il blocco
    misurato conta (non la sintesi, non [CONTESTO], non le righe-etichetta)."""
    testo = (
        "Secondo l'ISTAT a Roma i furti sono in calo.\n\n"
        "Rischi da ontologia [ONTOLOGIA]\n"
        "Bar 2000 e' esposto a rapina, scippi ecc. Secondo l'ISTAT a Roma i furti "
        "sono in calo.\n\nRischi dal contesto [CONTESTO]\n"
        "Secondo l'ISTAT a Roma i furti sono in calo.\n"
    )
    esito = _controlla(testo)
    ontologia = [f for f in esito.frasi if f.blocco == "ontologia"]
    assert len(ontologia) == 1 and ontologia[0].parla_di_istat
    assert _frasi_istat_m1(testo, esito) == [
        "Secondo l'ISTAT a Roma i furti sono in calo"
    ]


def test_frasi_istat_m1_senza_blocco_misurato_sono_nessuna() -> None:
    testo = "Secondo l'ISTAT a Roma i furti sono in calo.\n"
    assert _controlla(testo).frasi_istat_m1 == ()


def test_frasi_istat_m1_anche_se_il_blocco_misurato_non_e_il_primo() -> None:
    testo = (
        "Sintesi.\n\nRischi dal contesto [CONTESTO]\n"
        "Secondo l'ISTAT a Roma i furti sono in calo.\n\n"
        "Rischi da ontologia [ONTOLOGIA]\n"
        "Bar 2000 e' esposto a rapina. Per l'ISTAT a Roma i furti sono in calo.\n"
    )
    assert _frasi_istat_m1(testo, _controlla(testo)) == [
        "Per l'ISTAT a Roma i furti sono in calo"
    ]


def test_frasi_istat_m1_riconoscono_l_elenco_dopo_righe_vuote() -> None:
    """Fix 6 anche sulle frasi di M1, che tengono il marcatore d'elenco: dopo
    un'introduzione con ":" la voce eredita il luogo oltre la riga vuota."""
    introduzione = "I dati ISTAT del Comune di Roma (2024) indicano:"
    testo = _ontologia(
        f"{introduzione}\n\n- furti: in calo;\n\n* danneggiamenti: stabili"
    )
    assert _frasi_istat_m1(testo, _controlla(testo)) == [
        introduzione,
        "- furti: in calo;",
        "* danneggiamenti: stabili",
    ]


def test_frasi_istat_m1_ereditano_il_luogo_anche_da_una_frase_tolta() -> None:
    """#369: per M1 il luogo passa anche dalle frasi che il filtro toglie, cosi' la
    misura non dipende dal filtro. Qui l'introduzione e' tolta (i furti sono in
    calo): per il filtro la riga d'elenco non eredita il luogo e non parla del dato,
    per M1 si'. Con l'introduzione giusta le frasi ISTAT per M1 sono le stesse."""
    voce = "- furti: in calo;"
    giusta = "I dati ISTAT del Comune di Roma (2024) indicano:"
    sbagliata = "I dati ISTAT del Comune di Roma (2024) indicano furti in aumento:"
    testo = _ontologia(f"{sbagliata}\n{voce}")
    esito = _controlla(testo)
    assert [(f.motivo, f.parla_di_istat) for f in esito.frasi[-2:]] == [
        ("direzione_contraria", True),
        (None, False),
    ]
    assert _frasi_istat_m1(testo, esito) == [sbagliata, voce]
    testo_giusto = _ontologia(f"{giusta}\n{voce}")
    assert _frasi_istat_m1(testo_giusto, _controlla(testo_giusto)) == [giusta, voce]


def test_frasi_istat_m1_marcatore_solo_a_inizio_riga() -> None:
    """Un trattino dopo il numero di una voce ("1. - furti") non e' un secondo
    marcatore: la frase resta la voce numerata, che eredita il luogo oltre la riga
    vuota (fix 6). Togliendo anche il trattino la voce non si riconoscerebbe."""
    introduzione = "I dati ISTAT del Comune di Roma (2024) indicano:"
    testo = _ontologia(f"{introduzione}\n\n1. - furti: in calo;")
    assert _frasi_istat_m1(testo, _controlla(testo)) == [
        introduzione,
        "1",
        "- furti: in calo;",
    ]


@pytest.mark.parametrize(
    ("voce", "attese"),
    [
        ("1. furti: in calo;", ["1", "furti: in calo;"]),
        ("10. furti: in calo;", ["10", "furti: in calo;"]),
        # M1 non spezza "1)": la voce e' una frase sola
        ("1) furti: in calo;", ["1) furti: in calo;"]),
        ("- 1. furti: in calo;", ["- 1", "furti: in calo;"]),
        ("   1. furti: in calo;", ["1", "furti: in calo;"]),
        # voce che non parla del dato: il suo numero resta fuori
        ("1. Bar 2000 e' esposto a rapina;", []),
        # un anno a inizio riga non e' il numero di una voce ("dal 2014": fuori
        # dalla forma "furti: in calo" una tendenza non basta, #385)
        (
            "2024 e' stato un anno di furti in calo dal 2014;",
            ["2024 e' stato un anno di furti in calo dal 2014;"],
        ),
        ("2024. I furti sono in calo dal 2014;", ["I furti sono in calo dal 2014;"]),
        # il punto di "3.016" non e' quello di un marcatore
        ("3.016 furti in calo dal 2014;", ["016 furti in calo dal 2014;"]),
    ],
)
def test_frasi_istat_m1_il_numero_segue_la_voce(voce: str, attese: list[str]) -> None:
    """#369, B-1: il numero che M1 stacca da una voce ISTAT numerata e' una frase
    ISTAT come la voce, cosi' M1 non lo conta come asserzione non ancorata. Anche
    con a capo CRLF."""
    introduzione = "I dati ISTAT del Comune di Roma (2024) indicano:"
    testo = _ontologia(f"{introduzione}\n{voce}")
    crlf = testo.replace("\n", "\r\n")
    for t in (testo, crlf):
        assert _frasi_istat_m1(t, _controlla(t)) == [introduzione, *attese]


def test_frasi_istat_m1_numero_a_fine_riga_non_segue_la_riga_dopo() -> None:
    """Un numero seguito dal punto e dall'a capo non e' l'inizio della voce della
    riga dopo."""
    introduzione = "I dati ISTAT del Comune di Roma (2024) indicano:"
    testo = _ontologia(f"{introduzione}\n1.\nfurti: in calo;")
    assert _frasi_istat_m1(testo, _controlla(testo)) == [
        introduzione,
        "furti: in calo;",
    ]


def test_filtro_con_a_capo_crlf_interrompe_l_eredita_alla_riga_vuota() -> None:
    """#369: con CRLF la riga vuota interrompe il luogo ereditato anche nel
    filtro, come con LF. Prima la frase dopo la riga vuota ereditava il luogo e
    restava; ora si toglie per luogo mancante."""
    lf = _ontologia(
        "Secondo l'ISTAT, nel Comune di Roma i furti sono in calo.\n\n"
        "Le rapine in pubblica via hanno un tasso più alto dal 2014."
    )
    crlf = lf.replace("\n", "\r\n")
    esito = _controlla_con(crlf, _ZONA_REALE)
    assert _motivi(esito) == _motivi(_controlla_con(lf, _ZONA_REALE))
    assert _motivi(esito) == [None, "luogo_mancante"]
    assert "Le rapine" not in esito.testo_filtrato
    assert "i furti sono in calo" in esito.testo_filtrato


def test_frasi_istat_m1_uguali_con_a_capo_crlf() -> None:
    """#369: con CRLF la riga vuota interrompe l'eredita' come con LF."""
    lf = _ontologia(
        "Secondo l'ISTAT, nel Comune di Roma i furti sono in calo.\n\n- furti: in calo;"
    )
    crlf = lf.replace("\n", "\r\n")
    assert (
        _frasi_istat_m1(crlf, _controlla(crlf))
        == _frasi_istat_m1(lf, _controlla(lf))
        == ["Secondo l'ISTAT, nel Comune di Roma i furti sono in calo"]
    )


def test_la_riga_etichetta_istat_non_si_toglie() -> None:
    """#365: "Dati statistici ISTAT [ISTAT]" nomina ISTAT ma non parla del dato;
    toglierla attaccherebbe la prosa del blocco a quello precedente (finche' il
    blocco ha frasi tenute, C5). Le frasi del blocco parlano del dato (C3)."""
    testo = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n\n"
        "Dati statistici ISTAT [ISTAT]\nNel Comune di Roma i furti sono in calo.\n"
    )
    esito = _controlla(testo)
    assert [(f.blocco, f.parla_di_istat, f.motivo) for f in esito.frasi][-2:] == [
        ("intestazione", False, None),
        ("istat", True, None),
    ]
    assert esito.testo_filtrato == testo


def test_blocco_istat_residuo_tutto_tolto_perde_anche_l_etichetta() -> None:
    """C5: senza frasi tenute la riga-etichetta resterebbe orfana."""
    testo = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n\n"
        "Dati statistici ISTAT [ISTAT]\nI furti sono 134.169.\n"
        "Secondo l'ISTAT i furti sono in calo.\n"
    )
    esito = _controlla(testo)
    assert esito.testo_filtrato == (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n"
    )
    # l'etichetta non e' una frase tolta: non conta fra le scartate
    assert esito.frasi_scartate == 2


def test_etichetta_con_prosa_sulla_stessa_riga_tutta_tolta() -> None:
    testo = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n\n"
        "Dati statistici ISTAT [ISTAT]: i furti sono 134.169.\n"
    )
    assert _controlla(testo).testo_filtrato == (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n"
    )


def test_niente_righe_vuote_iniziali_nel_testo_filtrato() -> None:
    testo = (
        "Secondo l'ISTAT i furti sono in calo.\n\n"
        "Rischi da ontologia [ONTOLOGIA]\nRapina.\n"
    )
    assert _controlla(testo).testo_filtrato == (
        "Rischi da ontologia [ONTOLOGIA]\nRapina.\n"
    )


def test_numeri_in_lettere_contati_non_tolti() -> None:
    testo = "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nI furti sono quasi il doppio della media.\n"
    esito = _controlla(testo)
    assert esito.numeri_in_lettere == 1
    assert esito.frasi_scartate == 0


def test_metriche_per_frase() -> None:
    testo = (
        "Sintesi.\n\nDati statistici ISTAT [ISTAT]\nI furti scendono da 148.910 a "
        "134.169, un calo del -10% (fonte ISTAT, Comune di Roma, 2024).\n"
    )
    frase = [f for f in _controlla(testo).frasi if f.blocco == "istat"][0]
    assert frase.motivo == "cifra_istat_fuori_blocco"
    assert (frase.cifre, frase.cifre_istat) == (3, 3)
    assert frase.voci == ("THEFT",)
    assert (frase.parla_di_istat, frase.luogo) == (True, True)
    assert (frase.direzione, frase.direzione_coerente) == ("giu", True)
    assert (frase.confronto, frase.confronto_coerente) == ("", None)


def test_metriche_per_frase_del_confronto() -> None:
    """#365: confronto e coerenza restano sulla frase per le metriche."""
    testo = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nSecondo l'ISTAT a Roma i "
        "furti sono sopra la media italiana. Secondo l'ISTAT a Roma i furti sono "
        "sotto la media italiana. Il furto di beni domina.\n"
    )
    frasi = [f for f in _controlla(testo).frasi if f.blocco == "ontologia"]
    assert [
        (f.parla_di_istat, f.confronto, f.confronto_coerente, f.motivo) for f in frasi
    ] == [
        (True, "piu_alto", True, None),
        (True, "piu_basso", False, "confronto_contrario"),
        (False, "", None, None),
    ]


@pytest.mark.parametrize(
    ("testo", "atteso"),
    [
        ("i furti sono sopra la media italiana", "piu_alto"),
        ("un tasso più alto di quello italiano", "piu_alto"),
        ("un tasso piu' alto di quello nazionale", "piu_alto"),
        ("un tasso più elevato della media", "piu_alto"),
        ("valori superiori al dato nazionale", "piu_alto"),
        ("al di sopra della media italiana", "piu_alto"),
        ("un tasso maggiore di quello italiano", "piu_alto"),
        ("sotto la media nazionale", "piu_basso"),
        ("al di sotto della media", "piu_basso"),
        ("un tasso più basso di quello italiano", "piu_basso"),
        ("un tasso più contenuto di quello italiano", "piu_basso"),
        ("un tasso minore del dato nazionale", "piu_basso"),
        ("valori inferiori alla media italiana", "piu_basso"),
        ("un tasso simile a quello italiano", "simile"),
        ("in linea con il dato nazionale", "simile"),
        (
            "più alto della media per i furti e più basso di quello italiano per altri",
            "misto",
        ),
        # senza termine di paragone vicino non e' un confronto
        ("un tasso piu' alto", "piu_alto"),
        ("valori inferiori", ""),
        ("reati simili sono in calo", ""),
        ("il piano superiore del palazzo", ""),
        ("in linea con l'ontologia, i furti", ""),
        ("più alti per alcune voci e più bassi per altre", ""),
        ("i furti sono in calo", ""),
    ],
)
def test_parole_di_confronto(testo: str, atteso: str) -> None:
    assert confronto_di(testo) == atteso


def test_confronto_per_luogo_e_voce_senza_classificazione() -> None:
    """#365 D3 (b): vale la classificazione della voce NEL luogo nominato; una voce
    senza classificazione (nazionale mancante) non regge un confronto."""
    provincia = riga(
        luogo="ITE43",
        nome="Provincia di Roma",
        tipo="provincia",
        tasso=1000.0,
        variazione=5,
    )
    senza_italia = riga("SNATCH", label="scippi", italia=None)
    blocco = blocco_istat_zona(
        [
            {"poi_id": "a", "istat": istat_poi(_COMUNE, senza_italia)},
            {
                "poi_id": "b",
                "istat": IstatPoi(
                    cornice=cornice(
                        luogo="ITE43", nome="Provincia di Roma", tipo="provincia"
                    ),
                    righe=(provincia,),
                ),
            },
        ],
        stima_token=len,
        limite_token=None,
    )
    casi = {
        "Secondo l'ISTAT, nella Provincia di Roma i furti sono sotto la media italiana.": None,
        "Secondo l'ISTAT, nel Comune di Roma i furti sono sotto la media italiana.": "confronto_contrario",
        # "Roma" vale per comune e provincia: basta che uno dei due concordi
        "Secondo l'ISTAT, a Roma i furti sono sotto la media italiana.": None,
        "Secondo l'ISTAT, nel Comune di Roma gli scippi sono sopra la media italiana.": "confronto_contrario",
        "Secondo l'ISTAT, nel Comune di Roma gli scippi sono in calo.": None,
    }
    for frase, atteso in casi.items():
        testo = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{frase}\n"
        esito = _controlla_con(testo, blocco)
        assert [f.motivo for f in esito.frasi if f.blocco == "ontologia"] == [atteso], (
            frase
        )


def test_estrazione_dei_numeri() -> None:
    assert estrai_numeri("da 1.162,7 a 0,6 e +15% poi −3 % nel 2014-2024") == [
        Numero(Decimal("1162.7"), "", False),
        Numero(Decimal("0.6"), "", False),
        Numero(Decimal("15"), "+", True),
        Numero(Decimal("3"), "-", True),
        Numero(Decimal("2014"), "", False),
        Numero(Decimal("2024"), "", False),
    ]
    assert estrai_numeri("voce ITE43 e 73_67") == []
    assert estrai_numeri("1. Rischio") == []


def test_divisione_in_frasi_non_spezza_i_numeri() -> None:
    testo = "Sono 1.162,7 ogni 100.000 abitanti. Poi altro!\nNuova riga"
    assert [testo[a:b] for a, b in dividi_frasi(testo)] == [
        "Sono 1.162,7 ogni 100.000 abitanti.",
        "Poi altro!",
        "Nuova riga",
    ]


def test_applica_controllo_senza_blocco_lascia_il_testo_invariato() -> None:
    """``blocco=None``: il prompt non aveva ISTAT, nessun controllo (#345 P4)."""
    testo = "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n"
    assert applica_controllo(testo, blocco=None, spans=[], contesto="") == (
        testo,
        None,
    )


def test_applica_controllo_con_blocco_vuoto_lascia_il_testo_invariato() -> None:
    """``BloccoIstat()`` di default (``testo=""``): stesso ramo di ISTAT spento."""
    testo = "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRapina.\n"
    assert applica_controllo(testo, blocco=BloccoIstat(), spans=[], contesto="") == (
        testo,
        None,
    )


def test_applica_controllo_con_blocco_attivo_filtra_e_ritorna_esito() -> None:
    """Con un blocco non vuoto delega a ``controlla_cifre`` e torna il filtrato."""
    testo = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nIl Colosseo concentra "
        "134.169 furti. Bar 2000 e' esposto a rapina.\n\n"
        "Dati statistici ISTAT [ISTAT]\nI furti sono 134.169 nel 2024.\n"
    )
    narrativa, esito = applica_controllo(
        testo, blocco=_BLOCCO, spans=_spans(testo), contesto=_CONTESTO
    )
    assert esito is not None
    assert narrativa == esito.testo_filtrato
    assert "134.169 furti" not in narrativa
    assert "Bar 2000 e' esposto a rapina." in narrativa
    assert esito == controlla_cifre(
        testo,
        blocchi=_spans(testo),
        blocco_istat=_BLOCCO.testo,
        contesto_senza_istat=_CONTESTO,
        righe=_BLOCCO.righe,
    )


def test_span_degli_anni_e_un_numero_ammesso_non_una_cifra_istat() -> None:
    """F2 (review finale): "10 anni" (Y - Y_confronto) non e' un numero inventato."""
    blocco = blocco_istat_poi(istat_poi(riga(variazione=-10)))
    testo = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nNegli ultimi 10 anni, secondo "
        "l'ISTAT, nel Comune di Roma i furti sono diminuiti.\n"
    )
    esito = controlla_cifre(
        testo,
        blocchi=_spans(testo),
        blocco_istat=blocco.testo,
        contesto_senza_istat=_CONTESTO,
        righe=blocco.righe,
    )
    frase = [f for f in esito.frasi if f.blocco == "ontologia"][0]
    assert frase.motivo is None
    # 10 coincide col valore assoluto della variazione (-10%): senza '%' e' il periodo
    assert frase.cifre_istat == 0


def test_per_cento_in_parole_vale_come_percentuale() -> None:
    """F6 (review finale): "10 per cento" e' una variazione ISTAT come "10%"."""
    testo = (
        "Nel Comune di Roma i furti sono calati del 10 per cento in dieci anni.\n\n"
        "Rischi da ontologia [ONTOLOGIA]\nRischio rapina.\n"
    )
    esito = _controlla(testo)
    assert [(f.blocco, f.motivo) for f in esito.frasi][0] == (
        "overview",
        "cifra_istat_fuori_blocco",
    )
    assert estrai_numeri("del 10 per cento e del 3 percento") == [
        Numero(Decimal("10"), "", True),
        Numero(Decimal("3"), "", True),
    ]


def test_prosa_sulla_riga_dell_intestazione_appartiene_al_blocco() -> None:
    """F7 (review finale): il testo dopo il token sulla riga-etichetta e' del blocco."""
    testo = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nRischio rapina.\n\n"
        "Dati statistici ISTAT [ISTAT]: nel Comune di Roma i delitti denunciati per "
        "furti sono in calo.\n"
    )
    esito = _controlla(testo)
    istat = [f for f in esito.frasi if f.blocco == "istat"]
    assert len(istat) == 1
    assert istat[0].motivo is None
    assert istat[0].testo.startswith("nel Comune di Roma")
    assert istat[0].direzione_coerente is True
    assert esito.frasi_scartate == 0
    assert esito.testo_filtrato == testo


def _controlla_con(
    testo: str, blocco: BloccoIstat, contesto: str = _CONTESTO
) -> EsitoControllo:
    return controlla_cifre(
        testo,
        blocchi=_spans(testo),
        blocco_istat=blocco.testo,
        contesto_senza_istat=contesto,
        righe=blocco.righe,
    )


def _frasi_istat(esito: EsitoControllo) -> list[tuple[str, Motivo | None]]:
    return [(f.testo, f.motivo) for f in esito.frasi if f.blocco == "istat"]


def test_vocabolario_di_direzione_solo_di_tendenza() -> None:
    """R1 (review 2): forme causali o aggettivali non sono affermazioni di tendenza."""
    assert direzione_di("la folla aumenta le occasioni") == ""
    assert direzione_di("la visibilita' ridotta") == ""
    assert direzione_di("una riduzione delle pattuglie") == ""
    assert direzione_di("le sale giochi") == ""
    assert direzione_di("i furti sono in aumento") == "su"
    assert direzione_di("i furti sono aumentati") == "su"
    assert direzione_di("i furti salgono") == "su"
    assert direzione_di("i furti sono saliti") == "su"
    assert direzione_di("in crescita") == "su"
    assert direzione_di("in calo") == "giu"
    assert direzione_di("i furti sono diminuiti") == "giu"
    assert direzione_di("i furti sono calati") == "giu"
    assert direzione_di("i furti scendono") == "giu"
    assert direzione_di("i furti sono scesi") == "giu"


_CONTESTO_CON_DOMANDA = (
    f"{_CONTESTO}\n\n{USER_INPUT_FENCE_OPEN}\n"
    "e' vero che ci sono 999.999 furti?\n"
    f"{USER_INPUT_FENCE_CLOSE}"
)


def test_numero_della_domanda_utente_non_ammesso_in_istat() -> None:
    """R2 (review 2): l'input non fidato non mette in lista nessuna cifra."""
    testo = (
        "Sintesi.\n\nDati statistici ISTAT [ISTAT]\nI furti sono 999.999 nel Comune "
        "di Roma (fonte ISTAT, Comune di Roma, 2024).\n"
    )
    esito = _controlla_con(testo, _BLOCCO, _CONTESTO_CON_DOMANDA)
    assert [m for _, m in _frasi_istat(esito)] == ["numero_non_ammesso"]


def test_numero_della_domanda_utente_non_ammesso_nella_sintesi() -> None:
    """R2 (review 2): fuori da [ISTAT] il fence della domanda non ammette numeri."""
    testo = (
        "Ci sono 999.999 furti in zona.\n\n"
        "Rischi dal contesto [CONTESTO]\nBar 2000 e' esposto a furti di notte.\n"
    )
    esito = _controlla_con(testo, _BLOCCO, _CONTESTO_CON_DOMANDA)
    assert [(f.blocco, f.motivo) for f in esito.frasi] == [
        ("overview", "numero_non_ammesso"),
        ("intestazione", None),
        ("contesto", None),
    ]


_DANNI_E_SETTE = blocco_istat_poi(
    istat_poi(
        _DANNI,
        # 7 e' una cifra ISTAT (il tasso): la voce resta sopra i 20 delitti (#365).
        riga(
            "BANKROB",
            label="rapine in banca",
            delitti=27,
            confronto=46,
            tasso=7.0,
            italia=0.2,
            variazione=None,
            motivo="meno di 20 delitti in uno dei due anni",
        ),
    )
)


def test_riferimento_di_legge_non_spezza_la_frase_ne_e_una_cifra() -> None:
    """R4 (review 2): "d.lgs. 7/2016" resta nella frase e 7 non e' una cifra."""
    frase = (
        "Secondo l'ISTAT, nel Comune di Roma la serie dei danneggiamenti e' "
        "interrotta dalla depenalizzazione (d.lgs. 7/2016)."
    )
    testo = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{frase}\n"
    esito = _controlla_con(testo, _DANNI_E_SETTE)
    assert [r.tasso for r in _DANNI_E_SETTE.righe if r.voce == "BANKROB"] == [7.0]
    assert [
        (f.testo, f.motivo, f.cifre_istat)
        for f in esito.frasi
        if f.blocco == "ontologia"
    ] == [(frase, None, 0)]
    assert esito.testo_filtrato == testo


def test_abbreviazioni_non_chiudono_la_frase() -> None:
    """R4 (review 2): d.lgs., art., n., es., ecc., cfr. non chiudono la frase."""
    testo = "Vedi art. 624 e cfr. n. 3, es. furti ecc. ma non solo. Fine."
    assert [testo[a:b] for a, b in dividi_frasi(testo)] == [
        "Vedi art. 624 e cfr. n. 3, es. furti ecc. ma non solo.",
        "Fine.",
    ]
    assert estrai_numeri("dal d.lgs. 7/2016 in poi") == []


_COMUNE = riga()
_PROVINCIA = riga(
    luogo="ITE43",
    nome="Provincia di Roma",
    breve="Roma",
    tipo="provincia",
    delitti=200000,
    confronto=190000,
    tasso=4700.1,
    italia=1788.7,
    variazione=5,
)
_DUE_LUOGHI = blocco_istat_zona(
    [
        {"poi_id": "a", "istat": istat_poi(_COMUNE)},
        {
            "poi_id": "b",
            "istat": IstatPoi(
                cornice=cornice(
                    luogo="ITE43",
                    nome="Provincia di Roma",
                    breve="Roma",
                    tipo="provincia",
                ),
                righe=(_PROVINCIA,),
            ),
        },
    ],
    stima_token=len,
    limite_token=None,
)


@pytest.mark.parametrize(
    ("frase", "atteso"),
    [
        (
            "Nel Comune di Roma i furti sono in aumento (fonte ISTAT, Comune di Roma, 2024).",
            "direzione_contraria",
        ),
        (
            "Secondo l'ISTAT, nella Provincia di Roma i furti sono in aumento.",
            None,
        ),
        ("Secondo l'ISTAT, nel Comune di Roma i furti sono in calo.", None),
        (
            "Secondo l'ISTAT, nella Provincia di Roma i furti sono in calo.",
            "direzione_contraria",
        ),
        # "Roma" vale per comune e provincia: basta una tendenza concorde
        ("Secondo l'ISTAT, a Roma i furti sono in aumento.", None),
        # #365: con ISTAT, le cifre si tolgono sempre (anche quelle giuste)
        (
            "Nella Provincia di Roma i furti sono 200.000, in aumento del +5% (fonte ISTAT, Provincia di Roma, 2024).",
            "cifra_istat_fuori_blocco",
        ),
        # una frase che non parla di ISTAT non si controlla
        ("I furti sono in aumento.", None),
    ],
)
def test_direzione_per_luogo_e_voce(frase: str, atteso: Motivo | None) -> None:
    """R6 (review 2): se la frase nomina un luogo delle righe valgono i suoi valori."""
    testo = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{frase}\n"
    esito = _controlla_con(testo, _DUE_LUOGHI)
    assert [(f.testo, f.motivo) for f in esito.frasi if f.blocco == "ontologia"] == [
        (frase, atteso)
    ]


_STRAPPO: RigaIstat = riga(
    "SNATCH",
    label="furti con strappo",
    delitti=340,
    confronto=1150,
    tasso=12.4,
    italia=19.9,
    variazione=-70,
)
_CON_STRAPPO = blocco_istat_poi(istat_poi(_COMUNE, _STRAPPO))


@pytest.mark.parametrize(
    "frase",
    [
        "Nei 10 anni 340 furti con strappo in meno.",
        "Negli ultimi 10 340 furti con strappo denunciati nel 2024 (fonte ISTAT, Comune di Roma, 2024).",
        "I furti sono 134 169 nel 2024.",
    ],
)
def test_spazio_normale_fra_due_numeri_ammessi(frase: str) -> None:
    """R8 (review 2): "10 340" sono due numeri ammessi, non 10.340 (che sarebbe un
    ``numero_non_ammesso``): la frase si toglie solo perche' porta una cifra ISTAT
    (#365)."""
    testo = f"Sintesi.\n\nDati statistici ISTAT [ISTAT]\n{frase}\n"
    assert _frasi_istat(_controlla_con(testo, _CON_STRAPPO)) == [
        (frase, "cifra_istat_fuori_blocco")
    ]


def test_la_variazione_del_totale_non_e_piu_una_cifra_ammessa() -> None:
    """#353: la cornice non calcola piu' la variazione (rottura 2016), quindi la
    vecchia percentuale del totale non e' nel blocco e una frase che la cita va
    tolta. Dati reali del Comune di Milano (totale 162.177 -> 140.974)."""
    from crime_risk_analyzer.istat.righe import istat_per_poi

    istat = istat_per_poi(45.4642, 9.19, ["Property_theft"])
    assert istat is not None
    blocco = blocco_istat_poi(istat)
    assert "-13%" not in blocco.testo
    testo = (
        "Sintesi.\n\nDati statistici ISTAT [ISTAT]\n"
        "Nel Comune di Milano il totale dei delitti denunciati e' in calo del -13% "
        "(fonte ISTAT, Comune di Milano, 2024).\n"
    )
    esito = controlla_cifre(
        testo,
        blocchi=_spans(testo),
        blocco_istat=blocco.testo,
        contesto_senza_istat=_CONTESTO,
        righe=blocco.righe,
    )
    assert "-13%" not in esito.testo_filtrato
    citanti = [f for f in esito.frasi if "-13%" in testo[f.inizio : f.fine]]
    assert len(citanti) == 1
    assert citanti[0].motivo is not None


def test_voce_dal_rischio_con_apostrofo_tipografico() -> None:
    """C1: il nome del rischio si riconosce con l'apostrofo dritto o tipografico."""
    auto = riga(
        "VEHTHEFT",
        label="furti di autoveicoli",
        tasso=100.0,
        italia=200.0,
        variazione=5,
        collegamenti=(collegamento("Car_theft", "Furto d'auto", "esatta"),),
    )
    blocco = blocco_istat_poi(istat_poi(auto))
    base = "Secondo l'ISTAT, nel Comune di Roma il furto {} ha un tasso più {} di quello italiano."
    casi = {
        base.format("d\u2019auto", "basso"): None,
        base.format("d'auto", "basso"): None,
        base.format("d\u2019auto", "alto"): "confronto_contrario",
    }
    for frase, atteso in casi.items():
        testo = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{frase}\n"
        esito = _controlla_con(testo, blocco)
        assert [f.motivo for f in esito.frasi if f.blocco == "ontologia"] == [atteso], (
            frase
        )


def test_la_frase_d_esempio_del_prompt_passa_il_controllo() -> None:
    """D7: la frase che il prompt porta come esempio non deve essere tolta."""
    from crime_risk_analyzer.rag.istat_rules import ESEMPIO_ISTAT

    frase = ESEMPIO_ISTAT.strip('"')
    testo = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{frase}\n"
    esito = _controlla(testo)
    assert [
        (f.motivo, f.confronto_coerente, f.direzione_coerente)
        for f in esito.frasi
        if f.blocco == "ontologia"
    ] == [(None, True, True)]


# --- #365, seconda prova reale: frasi ISTAT senza marcatori espliciti ---

_INFORMATICI = riga(
    "CYBERCRIME",
    label="delitti informatici",
    tasso=120.0,
    italia=80.0,
    variazione=12,
    collegamenti=(collegamento("Cyber_attack", "Attacco informatico", "piu_larga"),),
)
_STRADA = riga(
    "STREETROB",
    label="rapine in pubblica via",
    tasso=90.0,
    italia=40.0,
    variazione=32,
    collegamenti=(collegamento("Mugging", "Aggressione a scopo di furto", "esatta"),),
)
_ZONA_REALE = blocco_istat_zona(
    [{"poi_id": "a", "istat": istat_poi(_COMUNE, _INFORMATICI, _STRADA)}],
    stima_token=len,
    limite_token=None,
)


@pytest.mark.parametrize(
    ("frase", "atteso"),
    [
        # le tre frasi della prova reale: parlano del dato senza dire il luogo
        (
            "I **delitti informatici** mostrano un tasso più alto e una crescita "
            "dal 2014, con la voce più ampia del rischio.",
            "luogo_mancante",
        ),
        (
            "Le **rapine in pubblica via** hanno un tasso più alto e una crescita "
            "dal 2014, con la voce più ampia del rischio.",
            "luogo_mancante",
        ),
        (
            "I **furti** hanno un tasso più alto ma sono in calo dal 2014, la voce "
            "è più ampia del rischio.",
            "luogo_mancante",
        ),
        # voce nominata + uno dei marcatori: tasso, "dal 2014", voce
        ("I furti sono in calo dal 2014.", "luogo_mancante"),
        ("Per i furti la voce è più ampia del rischio.", "luogo_mancante"),
        # anche col nome del rischio collegato (come in C1)
        ("L'aggressione a scopo di furto ha un tasso più alto.", "luogo_mancante"),
        # col luogo: il confronto implicito ("tasso più alto") si verifica
        ("Nel Comune di Roma i furti hanno un tasso più alto.", None),
        ("Nel Comune di Roma i furti hanno un tasso più basso.", "confronto_contrario"),
        (
            "Nel Comune di Roma i **delitti informatici** hanno un tasso più alto e "
            "sono in crescita dal 2014.",
            None,
        ),
        # falsi positivi: niente voce ISTAT, o voce senza tasso/anno/voce
        ("Il tasso di affollamento della stazione è più alto la sera.", None),
        ("Ci sono furti nella stazione.", None),
        ("I furti nella stazione sono favoriti dalla folla.", None),
    ],
)
def test_frase_che_nomina_una_voce_e_un_marcatore_parla_di_istat(
    frase: str, atteso: Motivo | None
) -> None:
    testo = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{frase}\n"
    esito = _controlla_con(testo, _ZONA_REALE)
    assert [f.motivo for f in esito.frasi if f.blocco == "ontologia"] == [atteso]


def test_il_tasso_di_affollamento_non_parla_di_istat() -> None:
    testo = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n"
        "Il tasso di affollamento della stazione è più alto la sera.\n"
    )
    frase = [f for f in _controlla_con(testo, _ZONA_REALE).frasi][-1]
    assert (frase.parla_di_istat, frase.voci) == (False, ())


@pytest.mark.parametrize(
    ("testo", "atteso"),
    [
        ("i furti hanno un tasso più alto", "piu_alto"),
        ("un tasso decisamente più basso", "piu_basso"),
        ("un tasso simile", "simile"),
        ("hanno un tasso più alto ma sono in calo", "piu_alto"),
        # "tasso" lontano o in un'altra proposizione non ancora il confronto
        ("il tasso di affollamento, nelle ore di punta, e' piu' alto", ""),
    ],
)
def test_tasso_come_ancora_del_confronto_implicito(testo: str, atteso: str) -> None:
    assert confronto_di(testo) == atteso


@pytest.mark.parametrize(
    ("frase", "atteso"),
    [
        (
            "Secondo i dati ISTAT del **Comune di Roma (2024)**, i **delitti "
            "denunciati** hanno un tasso più alto di quello italiano (voce di "
            "contesto generale).",
            None,
        ),
        (
            "Secondo i dati ISTAT del Comune di Roma, i delitti denunciati hanno un "
            "tasso più basso di quello italiano.",
            "confronto_contrario",
        ),
        # se c'e' un'altra voce nominata vale quella, non il totale
        (
            "Secondo l'ISTAT, nel Comune di Roma i delitti denunciati per furti "
            "hanno un tasso più alto di quello italiano.",
            None,
        ),
    ],
)
def test_delitti_denunciati_si_risolve_nel_totale(
    frase: str, atteso: Motivo | None
) -> None:
    testo = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{frase}\n"
    esito = _controlla_con(testo, _ZONA_REALE)
    frasi = [f for f in esito.frasi if f.blocco == "ontologia"]
    assert [f.motivo for f in frasi] == [atteso]
    if "per furti" in frase:
        assert frasi[0].voci == ("THEFT",)


@pytest.mark.parametrize(
    "frase",
    [
        # "_" e' un carattere di parola: senza toglierlo "_furti_" non nomina i furti
        "I _furti_ hanno un tasso più alto ma sono in calo dal 2014.",
        # grassetto dentro un'etichetta di piu' parole
        "Le **rapine** in pubblica via hanno un tasso più alto dal 2014.",
    ],
)
def test_il_markdown_non_nasconde_la_voce(frase: str) -> None:
    testo = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{frase}\n"
    esito = _controlla_con(testo, _ZONA_REALE)
    assert [f.motivo for f in esito.frasi if f.blocco == "ontologia"] == [
        "luogo_mancante"
    ]


# --- #365, terza prova reale: il luogo vale per il resto del paragrafo ---


def _ontologia(corpo: str) -> str:
    return f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{corpo}\n"


def _motivi(esito: EsitoControllo, blocco: str = "ontologia") -> list[Motivo | None]:
    return [f.motivo for f in esito.frasi if f.blocco == blocco]


def test_elenco_dopo_il_luogo_lo_eredita() -> None:
    """Punto Termini: il luogo nell'introduzione vale per le voci dell'elenco."""
    corpo = (
        "I dati ISTAT del **Comune di Roma** (2024) forniscono indicazioni utili "
        "per alcuni di questi rischi:  \n"
        "- Per il **Rischio informatico**, la voce “delitti informatici” "
        "presenta un tasso più alto rispetto alla media italiana e una tendenza in "
        "crescita dal 2014; la voce è più ampia del rischio specifico.\n"
        "- Per il **Furto di rame**, la voce “furti” registra un tasso più "
        "alto rispetto alla media nazionale ma una tendenza in calo dal 2014; la "
        "voce è più ampia del rischio."
    )
    testo = _ontologia(corpo)
    esito = _controlla_con(testo, _ZONA_REALE)
    frasi = [f for f in esito.frasi if f.blocco == "ontologia"]
    assert [(f.motivo, f.luogo, f.luogo_ereditato) for f in frasi] == [
        (None, True, False),
        (None, False, True),
        (None, False, True),
    ]
    assert [(f.confronto_coerente, f.direzione_coerente) for f in frasi[1:]] == [
        (True, True),
        (True, True),
    ]
    assert esito.testo_filtrato == testo


def test_frase_successiva_della_zona_eredita_il_luogo() -> None:
    testo = _ontologia(
        "Questo aggregato è corroborato dai dati ISTAT del Comune di Roma (2024), "
        "che indicano per i furti un tasso più alto di quello italiano. Inoltre, le "
        "rapine in pubblica via mostrano un tasso più alto dell'italiano e una "
        "crescita dal 2014."
    )
    assert _motivi(_controlla_con(testo, _ZONA_REALE)) == [None, None]


def test_la_riga_vuota_interrompe_l_eredita() -> None:
    testo = _ontologia(
        "Secondo l'ISTAT, nel Comune di Roma i furti sono in calo.\n\n"
        "Le rapine in pubblica via hanno un tasso più alto dal 2014."
    )
    assert _motivi(_controlla_con(testo, _ZONA_REALE)) == [None, "luogo_mancante"]


@pytest.mark.parametrize(
    ("corpo", "atteso"),
    [
        # eredita il Comune (furti in calo): "in crescita" e' contraria
        (
            "Secondo l'ISTAT, nel Comune di Roma i furti sono in calo. I furti sono "
            "in crescita dal 2014.",
            [None, "direzione_contraria"],
        ),
        # eredita la Provincia (furti in aumento)
        (
            "Secondo l'ISTAT, nella Provincia di Roma i furti sono in aumento. I "
            "furti sono in crescita dal 2014.",
            [None, None],
        ),
        # un nuovo luogo sostituisce quello ereditato
        (
            "Secondo l'ISTAT, nel Comune di Roma i furti sono in calo. Secondo "
            "l'ISTAT nella Provincia di Roma i furti sono in aumento. I furti sono "
            "in crescita dal 2014.",
            [None, None, None],
        ),
    ],
)
def test_il_luogo_ereditato_decide_la_verifica(
    corpo: str, atteso: list[Motivo | None]
) -> None:
    assert _motivi(_controlla_con(_ontologia(corpo), _DUE_LUOGHI)) == atteso


def test_una_frase_tolta_non_trasmette_il_luogo() -> None:
    testo = _ontologia(
        "Secondo l'ISTAT, nel Comune di Roma i furti sono in aumento. Le rapine in "
        "pubblica via hanno un tasso più alto dal 2014."
    )
    assert _motivi(_controlla_con(testo, _ZONA_REALE)) == [
        "direzione_contraria",
        "luogo_mancante",
    ]


def test_una_frase_che_non_parla_di_istat_non_trasmette_il_luogo() -> None:
    testo = _ontologia(
        "Nel Comune di Roma la folla è intensa. Le rapine in pubblica via hanno un "
        "tasso più alto dal 2014."
    )
    assert _motivi(_controlla_con(testo, _ZONA_REALE)) == [None, "luogo_mancante"]


def test_nessuna_eredita_fra_blocchi() -> None:
    """Dalla sintesi a un blocco e fra due blocchi, anche senza riga vuota."""
    testo = (
        "Secondo l'ISTAT, nel Comune di Roma i furti sono in calo.\n"
        "Rischi da ontologia [ONTOLOGIA]\n"
        "Le rapine in pubblica via hanno un tasso più alto dal 2014.\n"
        "Secondo l'ISTAT, nel Comune di Roma i furti sono in calo.\n"
        "Rischi dal contesto [CONTESTO]\n"
        "I furti hanno un tasso più alto dal 2014.\n"
    )
    esito = _controlla_con(testo, _ZONA_REALE)
    assert _motivi(esito, "overview") == [None]
    assert _motivi(esito) == ["luogo_mancante", None]
    assert _motivi(esito, "contesto") == ["luogo_mancante"]


# --- #365, fix 4: "tasso" e "voce" come marcatori solo in senso ISTAT ---

_FURTI_CON_RISCHI = blocco_istat_poi(
    istat_poi(
        riga(
            collegamenti=(
                collegamento("Vehicle_Theft", "Furto di veicolo", "piu_stretta"),
                collegamento("Copper_theft", "Furto di rame", "piu_larga"),
                collegamento("Goods_theft", "Furto di merci", "piu_larga"),
            )
        ),
        _DANNI,
    )
)


@pytest.mark.parametrize(
    ("frase", "atteso"),
    [
        # falso positivo della prova reale: "tasso" dentro una vulnerabilita'
        (
            "Questa tendenza è rafforzata dalla presenza di *Furto di veicolo*, "
            "*Furto di rame* e *Furto di merci*, tutti collegati a una "
            "vulnerabilità di *Area ad alto tasso di criminalità* e a una "
            "*Carenza di personale* sia nella polizia che nei servizi di controllo.",
            None,
        ),
        ("I furti colpiscono un'Area ad alto tasso di criminalità.", None),
        ("I furti nella zona danno voce al disagio dei residenti.", None),
        # frasi reali dei giri precedenti: ancora riconosciute (senza luogo)
        (
            "I **furti** hanno un tasso più alto ma sono in calo dal 2014, la voce "
            "è più ampia del rischio.",
            "luogo_mancante",
        ),
        ("I furti hanno un tasso più alto.", "luogo_mancante"),
        (
            "La stazione registra un tasso di **danneggiamenti** più alto.",
            "luogo_mancante",
        ),
        ("Il tasso dei furti preoccupa.", "luogo_mancante"),
        # "voce" in senso ISTAT
        ("Per i furti la voce è più ampia del rischio.", "luogo_mancante"),
        ("I furti, voce ISTAT collegata, preoccupano.", "luogo_mancante"),
        ("Per i furti questa voce non coincide con il rischio.", "luogo_mancante"),
        # solo "voce ... coincide" marca questa frase
        ("I furti come voce non coincidono col furto di rame.", "luogo_mancante"),
        ("I furti sono una voce più ampia del furto di rame.", "luogo_mancante"),
    ],
)
def test_tasso_e_voce_marcano_solo_in_senso_istat(
    frase: str, atteso: Motivo | None
) -> None:
    testo = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{frase}\n"
    esito = _controlla_con(testo, _FURTI_CON_RISCHI)
    assert [f.motivo for f in esito.frasi if f.blocco == "ontologia"] == [atteso]


# --- #365, fix 5 (review finale) ---

_SCIPPI_SIMILI = riga("SNATCH", label="scippi", tasso=100.0, italia=100.0, variazione=5)
_FURTI_E_SCIPPI = blocco_istat_poi(istat_poi(_COMUNE, _SCIPPI_SIMILI))


@pytest.mark.parametrize(
    ("frase", "blocco", "atteso"),
    [
        # C-1: tutte le voci nominate devono concordare (furti in calo, rapine in
        # esercizi commerciali in crescita: "in crescita" vale solo per una)
        (
            "Nel Comune di Roma, secondo l'ISTAT, i furti e le rapine in esercizi "
            "commerciali sono in crescita dal 2014.",
            _BLOCCO,
            "direzione_contraria",
        ),
        (
            "Nel Comune di Roma, secondo l'ISTAT, i furti e le rapine in pubblica "
            "via hanno un tasso simile a quello italiano.",
            _ZONA_REALE,
            "confronto_contrario",
        ),
        # "simile" e' giusto per gli scippi ma non per i furti
        (
            "Secondo l'ISTAT, nel Comune di Roma i furti e gli scippi hanno un "
            "tasso simile a quello italiano.",
            _FURTI_E_SCIPPI,
            "confronto_contrario",
        ),
        (
            "Secondo l'ISTAT, nel Comune di Roma gli scippi hanno un tasso simile a "
            "quello italiano.",
            _FURTI_E_SCIPPI,
            None,
        ),
        # due voci entrambe coerenti: resta
        (
            "Secondo l'ISTAT, nel Comune di Roma i furti e le rapine in pubblica via "
            "hanno un tasso più alto di quello italiano.",
            _ZONA_REALE,
            None,
        ),
    ],
)
def test_tutte_le_voci_nominate_devono_concordare(
    frase: str, blocco: BloccoIstat, atteso: Motivo | None
) -> None:
    testo = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{frase}\n"
    assert _motivi(_controlla_con(testo, blocco)) == [atteso]


def test_elenco_con_luogo_ereditato_conta_le_voci_con_tendenza_o_confronto() -> None:
    """C-2: dopo "I dati ISTAT del Comune di Roma (2024) indicano:" una riga
    d'elenco con una voce e una tendenza o un confronto parla del dato."""
    testo = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n"
        "I dati ISTAT del Comune di Roma (2024) indicano:\n"
        "- furti: in crescita;\n"
        "- furti: più alti della media;\n"
        "- danneggiamenti: in crescita.\n"
    )
    frasi = [f for f in _controlla(testo).frasi if f.blocco == "ontologia"]
    assert [(f.motivo, f.parla_di_istat) for f in frasi] == [
        (None, True),
        ("direzione_contraria", True),
        (None, True),
        ("direzione_contraria", True),
    ]
    assert frasi[2].confronto_coerente is True


def test_senza_luogo_ereditato_la_riga_d_elenco_resta_fuori() -> None:
    """C-2 vale solo dentro il paragrafo con un luogo: senza, R1 resta."""
    testo = "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n- furti: in crescita;\n"
    frasi = [f for f in _controlla(testo).frasi if f.blocco == "ontologia"]
    assert [(f.motivo, f.parla_di_istat) for f in frasi] == [(None, False)]


@pytest.mark.parametrize(
    ("testo", "atteso"),
    [
        ("un tasso meno elevato della media", "piu_basso"),
        ("un tasso meno alto di quello italiano", "piu_basso"),
        ("un tasso meno basso di quello italiano", "piu_alto"),
        ("sono meno frequenti della media", "piu_basso"),
        ("sono meno diffusi rispetto al dato nazionale", "piu_basso"),
        ("sono più frequenti della media", "piu_alto"),
        ("sono più diffusi rispetto al dato nazionale", "piu_alto"),
        ("sono più elevati di quelli italiani", "piu_alto"),
        ("superano la media italiana", "piu_alto"),
        ("il tasso supera quello italiano", "piu_alto"),
        ("un tasso pari a quello italiano", "simile"),
        # C-4: il termine di paragone non e' l'aggettivo "italiani" da solo
        ("anche per una minore presenza di turisti italiani", ""),
        ("valori inferiori al livello nazionale", "piu_basso"),
        ("valori superiori al valore nazionale", "piu_alto"),
        ("valori superiori all'Italia", "piu_alto"),
    ],
)
def test_parole_di_confronto_della_review(testo: str, atteso: str) -> None:
    assert confronto_di(testo) == atteso


@pytest.mark.parametrize(
    ("testo", "atteso"),
    [
        ("i furti sono stabili", "stabile"),
        ("i furti si sono ridotti", "giu"),
        ("le rapine si sono ridotte", "giu"),
        ("i furti sono diminuiti", "giu"),
        ("le rapine sono diminuite", "giu"),
        ("i furti sono cresciuti", "su"),
        ("le rapine sono cresciute", "su"),
        # R1 resta: l'aggettivo "ridotta" non e' una tendenza
        ("la visibilita' ridotta", ""),
        ("stabile ma in calo", ""),
    ],
)
def test_parole_di_tendenza_della_review(testo: str, atteso: str) -> None:
    assert direzione_di(testo) == atteso


@pytest.mark.parametrize(
    ("variazione", "atteso"),
    [(0, None), (-10, "direzione_contraria"), (5, "direzione_contraria")],
)
def test_stabile_si_verifica_solo_con_variazione_zero(
    variazione: int, atteso: Motivo | None
) -> None:
    """C-3: il blocco scrive "stabile dal 2014" solo con variazione 0."""
    blocco = blocco_istat_poi(istat_poi(riga(variazione=variazione)))
    testo = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n"
        "Secondo l'ISTAT, nel Comune di Roma i furti sono stabili dal 2014.\n"
    )
    assert _motivi(_controlla_con(testo, blocco)) == [atteso]


def test_aggettivo_italiani_non_fa_confronto() -> None:
    """C-4: "minore presenza di turisti italiani" non confronta col dato."""
    testo = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n"
        "Secondo l'ISTAT, nel Comune di Roma i furti sono in calo dal 2014, anche "
        "per una minore presenza di turisti italiani.\n"
    )
    frasi = [f for f in _controlla(testo).frasi if f.blocco == "ontologia"]
    assert [(f.motivo, f.confronto) for f in frasi] == [(None, "")]


def test_codici_voce_contati_nell_esito() -> None:
    """Domanda 2: i codici delle righe scritti dal modello si contano, non si
    tolgono; solo maiuscolo e a parola intera."""
    testo = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n"
        "Secondo l'ISTAT, nel Comune di Roma la voce THEFT e' in calo (THEFT). "
        "Theft e THEFTS non contano; DAMAGE si'.\n"
    )
    esito = _controlla(testo)
    assert esito.codici_voce == 3
    assert esito.frasi_scartate == 0


@pytest.mark.parametrize(
    ("frase", "blocco", "atteso"),
    [
        # i danneggiamenti non hanno tendenza calcolata: la frase non e' verificabile
        # anche se per i furti "in calo" e' giusto
        (
            "Secondo l'ISTAT, nel Comune di Roma i furti e i danneggiamenti sono in "
            "calo.",
            _BLOCCO,
            "direzione_contraria",
        ),
        # gli scippi non hanno confronto (nazionale mancante)
        (
            "Secondo l'ISTAT, nel Comune di Roma i furti e gli scippi hanno un tasso "
            "più alto di quello italiano.",
            blocco_istat_poi(
                istat_poi(_COMUNE, riga("SNATCH", label="scippi", italia=None))
            ),
            "confronto_contrario",
        ),
    ],
)
def test_una_voce_non_verificabile_rende_la_frase_non_verificabile(
    frase: str, blocco: BloccoIstat, atteso: Motivo | None
) -> None:
    """C-1: con piu' voci basta che una non sia verificabile per togliere."""
    testo = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{frase}\n"
    assert _motivi(_controlla_con(testo, blocco)) == [atteso]


# --- #365, fix 6: introduzione con ":" e elenco dopo una riga vuota ---

_INTRO_TERMINI = (
    "I dati ISTAT del **Comune di Roma** (2024) forniscono indicazioni "
    "quantitative per alcuni di questi temi:  "
)
_VOCE_INFORMATICI = (
    "Per i **delitti informatici** (collegati al rischio informatico), il tasso è "
    "più alto di quello italiano e in crescita dal 2014; la voce è più ampia del "
    "rischio."
)
_VOCE_FURTI = (
    "Per i **furti** (collegati al furto di rame), il tasso è più alto di quello "
    "italiano ma in calo dal 2014; la voce è più ampia del rischio."
)
_FRASE_SENZA_LUOGO = "Le rapine in pubblica via hanno un tasso più alto dal 2014."


@pytest.mark.parametrize(
    ("corpo", "atteso"),
    [
        # il caso reale: introduzione con ":", riga vuota, elenco
        (
            f"{_INTRO_TERMINI}\n\n- {_VOCE_INFORMATICI}\n- {_VOCE_FURTI}",
            [None, None, None],
        ),
        # anche con piu' righe vuote prima della prima voce e altri marcatori
        (
            f"{_INTRO_TERMINI}\n\n\n* {_VOCE_INFORMATICI}\n* {_VOCE_FURTI}",
            [None, None, None],
        ),
        (
            f"{_INTRO_TERMINI}\n\n1. {_VOCE_INFORMATICI}\n2. {_VOCE_FURTI}",
            [None, None, None],
        ),
        # elenco "largo": righe vuote anche fra le voci, l'elenco continua
        (
            f"{_INTRO_TERMINI}\n\n- {_VOCE_INFORMATICI}\n\n- {_VOCE_FURTI}",
            [None, None, None],
        ),
        # introduzione senza ":": la riga vuota interrompe come prima
        (
            "I dati ISTAT del **Comune di Roma** (2024) danno indicazioni per alcuni "
            f"temi.\n\n- {_VOCE_INFORMATICI}\n- {_VOCE_FURTI}",
            [None, "luogo_mancante", "luogo_mancante"],
        ),
        # elenco interrotto da un paragrafo normale: l'eredita' si ferma
        (
            f"{_INTRO_TERMINI}\n\n- {_VOCE_INFORMATICI}\n\n{_FRASE_SENZA_LUOGO}\n"
            f"- {_VOCE_FURTI}",
            [None, None, "luogo_mancante", "luogo_mancante"],
        ),
        # ... anche senza riga vuota fra l'elenco e il paragrafo
        (
            f"{_INTRO_TERMINI}\n- {_VOCE_INFORMATICI}\n{_FRASE_SENZA_LUOGO}",
            [None, None, "luogo_mancante"],
        ),
        # un'introduzione tolta non passa il luogo nemmeno all'elenco
        (
            "I dati ISTAT del Comune di Roma (2024) indicano furti in aumento:\n\n"
            f"- {_VOCE_INFORMATICI}",
            ["direzione_contraria", "luogo_mancante"],
        ),
    ],
)
def test_introduzione_con_due_punti_passa_il_luogo_all_elenco(
    corpo: str, atteso: list[Motivo | None]
) -> None:
    testo = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{corpo}\n"
    assert _motivi(_controlla_con(testo, _ZONA_REALE)) == atteso


def test_l_elenco_non_eredita_fra_blocchi() -> None:
    testo = (
        f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{_INTRO_TERMINI}\n\n"
        f"Rischi dal contesto [CONTESTO]\n- {_VOCE_FURTI}\n"
    )
    esito = _controlla_con(testo, _ZONA_REALE)
    assert _motivi(esito, "contesto") == ["luogo_mancante"]


def test_l_elenco_deve_seguire_subito_l_introduzione() -> None:
    """Fix 6: se fra l'introduzione con ":" e l'elenco c'e' un'altra frase, le
    righe vuote prima dell'elenco interrompono l'eredita' come sempre."""
    testo = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n"
        f"{_INTRO_TERMINI}\nSecondo l'ISTAT i furti sono in calo.\n\n"
        f"- {_VOCE_FURTI}\n"
    )
    assert _motivi(_controlla_con(testo, _ZONA_REALE)) == [
        None,
        None,
        "luogo_mancante",
    ]


# --- #385: il controllo toglie solo le frasi che parlano davvero del dato ---

_INTRO_ROMA = (
    "I dati ISTAT del Comune di Roma (2024) indicano per i furti un tasso più alto "
    "di quello italiano, in calo dal 2014."
)


@pytest.mark.parametrize(
    "frase",
    [
        "I furti sono favoriti dalla crescita del turismo nell'area.",
        "Il furto di beni resta stabile come vulnerabilità tutto l'anno.",
        "Le rapine in esercizi commerciali sono in calo nelle ore notturne...",
        "I furti sono meno frequenti della media nelle ore notturne.",
    ],
)
def test_luogo_ereditato_e_tendenza_non_bastano(frase: str) -> None:
    """#385: col luogo ereditato una parola di tendenza o di confronto e il nome di
    una voce (o di un rischio) non fanno parlare del dato una frase sul rischio."""
    testo = _ontologia(f"{_INTRO_ROMA} {frase}")
    esito = _controlla(testo)
    assert [(f.motivo, f.parla_di_istat) for f in esito.frasi[-2:]] == [
        (None, True),
        (None, False),
    ]
    assert esito.testo_filtrato == testo


@pytest.mark.parametrize(
    "introduzione",
    [
        "Nel Comune di Roma, secondo l'ISTAT, i furti hanno un tasso più alto di "
        "quello italiano. I rischi dell'ontologia sono:",
        # l'introduzione ISTAT stessa apre l'elenco
        "Nel Comune di Roma, secondo l'ISTAT, i furti hanno un tasso più alto di "
        "quello italiano e i rischi dell'ontologia sono:",
    ],
)
def test_elenco_di_rischi_dopo_una_frase_istat_resta(introduzione: str) -> None:
    """#385, caso peggiore: le voci d'elenco sui rischi restano (prima restava
    solo "sono:")."""
    testo = _ontologia(
        f"{introduzione}\n"
        "- **Furto di beni**: la crescita dei flussi turistici aumenta i borseggi.\n"
        "- Furto di beni stabile nelle ore di punta per la folla."
    )
    esito = _controlla(testo)
    assert _motivi(esito) == [None] * len(_motivi(esito))
    assert esito.testo_filtrato == testo


@pytest.mark.parametrize(
    ("blocco", "frase"),
    [
        (
            "ontologia",
            "Il dato italiano della sicurezza stradale è migliorato negli ultimi anni.",
        ),
        ("ontologia", "Il quartiere ha un'età media superiore alla media nazionale."),
        ("contesto", "Il quartiere ha un'età media superiore alla media nazionale."),
        ("ontologia", "Il tasso nazionale di disoccupazione giovanile è alto."),
        (
            "ontologia",
            "Rispetto all'Italia del Nord, l'area ha più presenze turistiche.",
        ),
        ("contesto", "Quello italiano è un contesto turistico maturo."),
    ],
)
def test_frase_nazionale_senza_voce_non_parla_di_istat(blocco: str, frase: str) -> None:
    """#385: "media/dato/tasso nazionale", "quello italiano", "rispetto
    all'Italia" contano solo con una voce, un rischio collegato, ISTAT o i
    delitti denunciati."""
    testo = f"Sintesi.\n\n{_INTESTAZIONI[blocco]}\n{frase}\n"
    frasi = [f for f in _controlla(testo).frasi if f.blocco == blocco]
    assert [(f.motivo, f.parla_di_istat) for f in frasi] == [(None, False)]


@pytest.mark.parametrize(
    "frase",
    [
        "Il furto di beni è sopra la media nazionale.",
        "Rispetto all'Italia il furto di beni è in calo.",
    ],
)
def test_frase_nazionale_con_rischio_collegato_parla_di_istat(frase: str) -> None:
    """#385: con un rischio collegato la formula nazionale resta un marcatore."""
    testo = f"Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\n{frase}\n"
    assert _motivi(_controlla(testo)) == ["luogo_mancante"]


_SCIPPI_SOTTO_SOGLIA = riga(
    "SNATCH",
    label="scippi",
    delitti=25,
    confronto=12,
    tasso=20.0,
    italia=30.0,
    variazione=None,
    motivo=MOTIVO_SOTTO_SOGLIA,
)
_DANNI_2016 = riga(
    "DAMAGE",
    label="danneggiamenti",
    delitti=2016,
    confronto=1800,
    tasso=721.2,
    italia=471.5,
    variazione=None,
    motivo=MOTIVO_ROTTURA_2016,
    rottura_2016=True,
)
_SOGLIA_E_2016 = blocco_istat_poi(istat_poi(_COMUNE, _SCIPPI_SOTTO_SOGLIA, _DANNI_2016))


@pytest.mark.parametrize(
    ("frase", "atteso"),
    [
        ("Le voci con meno di 20 delitti in un anno non hanno tendenza.", None),
        ("Dopo la depenalizzazione del 2016 alcuni danneggiamenti...", None),
        # una cifra ISTAT che il blocco non scrive resta tolta
        ("Nel 2024 si contano 25 scippi.", "cifra_istat_fuori_blocco"),
    ],
)
def test_i_numeri_del_blocco_non_sono_cifre_istat(
    frase: str, atteso: Motivo | None
) -> None:
    """#385: la soglia e l'anno della depenalizzazione che il blocco scrive non
    valgono come cifre ISTAT, anche se coincidono con un tasso o un conteggio."""
    assert "meno di 20 delitti" in _SOGLIA_E_2016.testo
    assert "del 2016" in _SOGLIA_E_2016.testo
    testo = _ontologia(frase)
    # contesto senza numeri: "20" non vi coincide per caso (cfr. "su 20" di _CONTESTO)
    esito = _controlla_con(testo, _SOGLIA_E_2016, contesto="ZONA: Colosseo")
    assert _motivi(esito) == [atteso]


@pytest.mark.parametrize(
    ("corpo", "atteso"),
    [
        # il rischio collegato vale come voce in testa alla riga: furto di beni e'
        # collegato anche alle rapine in crescita, "in calo" non vale per tutte
        ("- Furto di beni: in calo;", ("direzione_contraria", True)),
        ("- **Furto di beni**: più alto della media;", (None, True)),
        # riga lunga: e' prosa sul rischio, non una riga di dati
        (
            "- furti: in crescita la sera, quando la folla riempie la piazza;",
            (None, False),
        ),
        (
            "- I furti nelle ore serali di punta della piazza: in crescita;",
            (None, False),
        ),
        # dopo i due punti non c'e' una tendenza ne' un confronto
        ("- furti: borseggi sui mezzi;", (None, False)),
        # in testa alla riga non c'e' una voce ne' un rischio
        ("- Turismo: in crescita;", (None, False)),
        ("- Turismo: furti in crescita;", (None, False)),
    ],
)
def test_riga_d_elenco_breve_dopo_introduzione_istat(
    corpo: str, atteso: tuple[Motivo | None, bool]
) -> None:
    testo = _ontologia(f"I dati ISTAT del Comune di Roma (2024) indicano:\n{corpo}")
    frasi = [f for f in _controlla(testo).frasi if f.blocco == "ontologia"]
    assert [(f.motivo, f.parla_di_istat) for f in frasi] == [(None, True), atteso]


def test_un_nuovo_luogo_esplicito_chiude_l_elenco_istat() -> None:
    """#385: dopo una frase ISTAT con un luogo esplicito che non finisce con ":"
    la forma "furti: in crescita" non basta piu', anche se il luogo resta."""
    testo = _ontologia(
        "I dati ISTAT del Comune di Roma (2024) indicano:\n"
        "Secondo l'ISTAT nel Comune di Roma i furti sono in calo.\n"
        "furti: in crescita;"
    )
    frasi = [f for f in _controlla(testo).frasi if f.blocco == "ontologia"]
    assert [(f.motivo, f.parla_di_istat) for f in frasi] == [
        (None, True),
        (None, True),
        (None, False),
    ]


# --- #386: plurali, negazioni, forme mancanti, piu' luoghi per esteso ---
# Caso di prova: furti nel Comune di Roma con tasso piu' alto di quello italiano e
# in calo dal 2014; rapine in esercizi commerciali piu' alte e in crescita;
# danneggiamenti senza tendenza (rottura del 2016).


@pytest.mark.parametrize(
    ("frase", "atteso"),
    [
        # plurali: "tassi", "quelli italiani", "valori nazionali", "livelli italiani"
        ("Nel Comune di Roma i furti hanno tassi più bassi.", "confronto_contrario"),
        ("I tassi dei furti sono inferiori a quelli italiani.", "luogo_mancante"),
        (
            "Nel Comune di Roma i tassi dei furti sono inferiori a quelli italiani.",
            "confronto_contrario",
        ),
        (
            "Nel Comune di Roma i furti hanno tassi inferiori ai valori nazionali.",
            "confronto_contrario",
        ),
        (
            "Nel Comune di Roma i furti sono sotto i livelli italiani.",
            "confronto_contrario",
        ),
        # negazioni
        (
            "Nel Comune di Roma il tasso dei furti non è più alto di quello italiano.",
            "confronto_contrario",
        ),
        (
            "Nel Comune di Roma i furti non hanno un tasso più alto di quello italiano.",
            "confronto_contrario",
        ),
        (
            "Secondo l'ISTAT, nel Comune di Roma i furti non sono in calo.",
            "direzione_contraria",
        ),
        (
            "Secondo l'ISTAT, nel Comune di Roma i furti non sono più in calo.",
            "direzione_contraria",
        ),
        (
            "Secondo l'ISTAT, nel Comune di Roma non c'è nessun calo dei furti.",
            "direzione_contraria",
        ),
        # negazione su una voce senza tendenza calcolata: non verificabile
        (
            "Secondo l'ISTAT, nel Comune di Roma i danneggiamenti non sono in calo.",
            "direzione_contraria",
        ),
        # forme di confronto mancanti
        (
            "Secondo l'ISTAT, nel Comune di Roma i furti sono meno che nel resto d'Italia.",
            "confronto_contrario",
        ),
        (
            "Nel Comune di Roma i furti sono meno numerosi che in Italia.",
            "confronto_contrario",
        ),
        (
            "Nel Comune di Roma i furti sono più rari che in Italia.",
            "confronto_contrario",
        ),
        (
            "Nel Comune di Roma il tasso dei furti è più ridotto di quello italiano.",
            "confronto_contrario",
        ),
        (
            "Nel Comune di Roma i furti sono meno frequenti che nel resto d'Italia.",
            "confronto_contrario",
        ),
        # forme di tendenza mancanti
        (
            "Nel Comune di Roma i furti sono in ripresa dal 2014.",
            "direzione_contraria",
        ),
        (
            "Nel Comune di Roma i furti sono raddoppiati dal 2014.",
            "direzione_contraria",
        ),
    ],
)
def test_frasi_sbagliate_della_verifica_386_si_tolgono(
    frase: str, atteso: Motivo
) -> None:
    """#386: frasi false che il controllo lasciava nel testo."""
    testo = _ontologia(frase)
    esito = _controlla(testo)
    assert _motivi(esito) == [atteso]
    assert frase not in esito.testo_filtrato


@pytest.mark.parametrize(
    "frase",
    [
        # la negazione inverte: giuste su una voce in crescita o piu' alta
        "Secondo l'ISTAT, nel Comune di Roma le rapine in esercizi commerciali non "
        "sono in calo.",
        "Secondo l'ISTAT, nel Comune di Roma i furti non sono in crescita.",
        "Nel Comune di Roma il tasso dei furti non è più basso di quello italiano.",
        "Nel Comune di Roma il tasso dei furti non è simile a quello italiano.",
        # la negazione in un'altra proposizione non conta
        "Secondo l'ISTAT, nel Comune di Roma i furti, che non mancano, sono in calo.",
        # "non" pleonastico dopo il confronto, "non solo": non negano
        "Nel Comune di Roma il tasso dei furti è più alto di quanto non sia quello "
        "italiano.",
        "Secondo l'ISTAT, nel Comune di Roma i furti non solo sono in calo dal 2014.",
        # plurali e forme nuove, giusti
        "Nel Comune di Roma i furti hanno tassi più alti dell'italiano.",
        "Nel Comune di Roma i furti hanno tassi più alti.",
        "Nel Comune di Roma i tassi dei furti sono superiori a quelli italiani.",
        "Nel Comune di Roma i furti sono più numerosi che in Italia.",
        "Nel Comune di Roma i furti sono più che nel resto d'Italia.",
        "Secondo l'ISTAT, nel Comune di Roma le rapine in esercizi commerciali sono "
        "in ripresa dal 2014.",
        "Nel Comune di Roma le rapine in esercizi commerciali sono raddoppiate dal "
        "2014.",
    ],
)
def test_frasi_giuste_della_verifica_386_restano(frase: str) -> None:
    testo = _ontologia(frase)
    esito = _controlla(testo)
    assert _motivi(esito) == [None]
    assert esito.frasi[-1].parla_di_istat
    assert esito.testo_filtrato == testo


@pytest.mark.parametrize(
    "frase",
    [
        "Il quartiere non ha un'età media superiore alla media nazionale.",
        "I tassi di affollamento della stazione non sono più alti la sera.",
        "La ripresa delle telecamere non copre i furti nella stazione.",
    ],
)
def test_frasi_senza_dato_istat_della_verifica_386_restano(frase: str) -> None:
    """#386 non allarga cio' che parla del dato: niente voce, niente ISTAT (#385)."""
    testo = _ontologia(frase)
    esito = _controlla(testo)
    assert [(f.motivo, f.parla_di_istat) for f in esito.frasi[-1:]] == [(None, False)]
    assert esito.testo_filtrato == testo


@pytest.mark.parametrize(
    ("testo", "atteso"),
    [
        ("i furti hanno tassi più bassi", "piu_basso"),
        ("sono inferiori a quelli italiani", "piu_basso"),
        ("tassi inferiori ai valori nazionali", "piu_basso"),
        ("sotto i livelli italiani", "piu_basso"),
        ("sotto i dati nazionali", "piu_basso"),
        ("meno che nel resto d'Italia", "piu_basso"),
        ("meno numerosi che in Italia", "piu_basso"),
        ("più rari che in Italia", "piu_basso"),
        ("più ridotto di quello italiano", "piu_basso"),
        ("meno frequenti che nel resto d'Italia", "piu_basso"),
        ("più numerosi che in Italia", "piu_alto"),
        ("meno rari che in Italia", "piu_alto"),
        ("più che nel resto d'Italia", "piu_alto"),
        ("tassi più alti dell'italiano", "piu_alto"),
    ],
)
def test_parole_di_confronto_386(testo: str, atteso: str) -> None:
    assert confronto_di(testo) == atteso


@pytest.mark.parametrize(
    ("testo", "atteso"),
    [
        ("i furti sono in ripresa", "su"),
        ("i furti sono raddoppiati", "su"),
        ("le rapine sono raddoppiate", "su"),
        # "ripresa" senza "in" non e' una tendenza
        ("la ripresa delle telecamere", ""),
    ],
)
def test_parole_di_tendenza_386(testo: str, atteso: str) -> None:
    assert direzione_di(testo) == atteso


def test_la_negazione_e_nell_esito() -> None:
    testo = _ontologia(
        "Secondo l'ISTAT, nel Comune di Roma i furti non sono in crescita. Nel "
        "Comune di Roma il tasso dei furti non è più basso di quello italiano."
    )
    direzione, confronto = _controlla(testo).frasi[-2:]
    assert (direzione.direzione, direzione.direzione_negata) == ("su", True)
    assert direzione.direzione_coerente is True
    assert (confronto.confronto, confronto.confronto_negato) == ("piu_basso", True)
    assert confronto.confronto_coerente is True


@pytest.mark.parametrize(
    ("corpo", "atteso"),
    [
        # (a) piu' luoghi per esteso: la frase deve valere per tutti
        (
            "Secondo l'ISTAT, nel Comune di Roma e nella Provincia di Roma i furti "
            "sono in crescita.",
            ["direzione_contraria"],
        ),
        (
            "Secondo l'ISTAT, nella Provincia di Roma e nel Comune di Roma i furti "
            "sono in calo.",
            ["direzione_contraria"],
        ),
        (
            "Secondo l'ISTAT, nel Comune di Roma e nella Provincia di Roma i furti "
            "hanno un tasso più alto di quello italiano.",
            [None],
        ),
        # i luoghi per esteso passano alla frase dopo, ancora tutti
        (
            "Secondo l'ISTAT, nel Comune di Roma e nella Provincia di Roma i furti "
            "hanno un tasso più alto di quello italiano. I furti sono in crescita "
            "dal 2014.",
            [None, "direzione_contraria"],
        ),
    ],
)
def test_piu_luoghi_per_esteso_devono_concordare_tutti(
    corpo: str, atteso: list[Motivo | None]
) -> None:
    assert _motivi(_controlla_con(_ontologia(corpo), _DUE_LUOGHI)) == atteso


@pytest.mark.parametrize(
    "corpo",
    [
        "Secondo l'ISTAT, a Roma i furti sono in crescita.",
        "Secondo l'ISTAT, a Roma i furti sono in calo.",
        # il nome breve passa il luogo alla frase dopo con la stessa regola
        "Secondo l'ISTAT, a Roma i furti hanno un tasso più alto di quello "
        "italiano. I furti sono in crescita dal 2014.",
    ],
)
def test_limite_il_nome_breve_basta_che_concordi_un_luogo(corpo: str) -> None:
    """Limite dichiarato (R6, #386 b): "Roma" vale per il comune e la provincia e
    la frase resta se concorda con almeno uno. "A Roma i furti sono in crescita"
    passa anche se nel comune sono in calo (in crescita nella provincia)."""
    esito = _controlla_con(_ontologia(corpo), _DUE_LUOGHI)
    assert _motivi(esito) == [None] * len(_motivi(esito))


def test_limite_una_negazione_vicina_inverte_anche_se_non_regge_la_parola() -> None:
    """Limite dichiarato (#386): "non" a meno di 4 parole dalla tendenza la nega
    anche quando regge un'altra parola; la frase giusta si toglie."""
    testo = _ontologia(
        "Secondo l'ISTAT, nel Comune di Roma i furti non denunciati sono in calo."
    )
    assert _motivi(_controlla(testo)) == ["direzione_contraria"]


@pytest.mark.parametrize(
    ("frase", "atteso"),
    [
        # solo "quelli italiani" fa parlare del dato
        (
            "Nel Comune di Roma i furti sono inferiori a quelli italiani.",
            "confronto_contrario",
        ),
        # solo "tassi dei <voce>" fa parlare del dato
        ("I tassi dei furti preoccupano.", "luogo_mancante"),
        # la negazione sta fra "tasso" e la parola di confronto
        (
            "Nel Comune di Roma il tasso non è più alto per i furti.",
            "confronto_contrario",
        ),
        # lo stesso confronto negato e non negato e' misto
        (
            "Nel Comune di Roma il tasso dei furti è più alto di quello italiano, ma "
            "non è più alto della media italiana.",
            "confronto_contrario",
        ),
        # una negazione a piu' di 3 parole dalla tendenza non la nega
        (
            "Secondo l'ISTAT, nel Comune di Roma i furti che non vengono denunciati "
            "sono in calo.",
            None,
        ),
    ],
)
def test_marcatori_e_negazioni_386(frase: str, atteso: Motivo | None) -> None:
    assert _motivi(_controlla(_ontologia(frase))) == [atteso]


def test_tendenza_negata_e_non_negata_non_si_verifica() -> None:
    """Come per tendenze diverse: la frase non si verifica su quell'asse."""
    testo = _ontologia(
        "Secondo l'ISTAT, nel Comune di Roma i furti sono in calo, non in calo."
    )
    frase = _controlla(testo).frasi[-1]
    assert (frase.direzione, frase.direzione_negata, frase.motivo) == ("", False, None)


_PROVINCIA_BASSA = riga(
    luogo="ITE43",
    nome="Provincia di Roma",
    breve="Roma",
    tipo="provincia",
    tasso=1000.0,
    italia=1788.7,
    variazione=5,
)
_COMUNE_E_PROVINCIA_BASSA = blocco_istat_zona(
    [
        {"poi_id": "a", "istat": istat_poi(_COMUNE)},
        {"poi_id": "b", "istat": istat_poi(_PROVINCIA_BASSA)},
    ],
    stima_token=len,
    limite_token=None,
)


@pytest.mark.parametrize(
    ("frase", "atteso"),
    [
        # (a) per esteso: piu' alto nel comune, piu' basso nella provincia
        (
            "Secondo l'ISTAT, nel Comune di Roma e nella Provincia di Roma i furti "
            "hanno un tasso più alto di quello italiano.",
            "confronto_contrario",
        ),
        # (b) limite dichiarato: col nome breve basta un luogo
        (
            "Secondo l'ISTAT, a Roma i furti hanno un tasso più alto di quello "
            "italiano.",
            None,
        ),
    ],
)
def test_confronto_con_piu_luoghi(frase: str, atteso: Motivo | None) -> None:
    esito = _controlla_con(_ontologia(frase), _COMUNE_E_PROVINCIA_BASSA)
    assert _motivi(esito) == [atteso]
