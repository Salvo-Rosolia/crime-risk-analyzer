# ruff: noqa: E501
"""Controllo delle cifre (#345, spec 4.7): tabella di casi tenere/togliere."""

from __future__ import annotations

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
    controlla_cifre,
    direzione_di,
    dividi_frasi,
    estrai_numeri,
)
from crime_risk_analyzer.istat.righe import MOTIVO_ROTTURA_2016, IstatPoi, RigaIstat
from crime_risk_analyzer.rag.generation import (
    USER_INPUT_FENCE_CLOSE,
    USER_INPUT_FENCE_OPEN,
)
from tests.istat._fattorie import cornice, istat_poi, riga

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


_CASI: list[tuple[str, str, Motivo | None]] = [
    # citazione corretta, conteggi, tassi, "per 100.000", anni
    (
        "istat",
        "Nel Comune di Roma i furti denunciati nel 2024 sono 134.169 (fonte ISTAT, Comune di Roma, 2024).",
        None,
    ),
    (
        "istat",
        "I furti sono 4.876,4 ogni 100.000 abitanti contro 1.788,7 in Italia (fonte ISTAT, Comune di Roma, 2024).",
        None,
    ),
    (
        "istat",
        "I furti scendono da 148.910 nel 2014 a 134.169 nel 2024, un calo del -10% (fonte ISTAT, Comune di Roma, 2024).",
        None,
    ),
    (
        "istat",
        "Le rapine in esercizi commerciali sono in aumento del +16% tra il 2014 e il 2024 (fonte ISTAT, Comune di Roma, 2024).",
        None,
    ),
    ("istat", "Il totale dei delitti denunciati e' 217.536 nel 2024.", None),
    ("istat", "I dati coprono il periodo 2014-2024.", None),
    ("istat", "I dati coprono il periodo 2014\u20132024.", None),
    (
        "istat",
        "Nei danneggiamenti la serie e' interrotta dal 2016, con 19.843 casi nel 2024 (fonte ISTAT, Comune di Roma, 2024).",
        None,
    ),
    ("istat", "Nel Comune di Roma i furti con destrezza e i furti sono 134.169.", None),
    # formati equivalenti
    ("istat", "I furti sono 134169 nel 2024.", None),
    ("istat", "I furti sono 134 169 nel 2024.", None),
    ("istat", "I furti sono 134\xa0169 nel 2024.", None),
    ("istat", "I furti sono 134\u202f169 nel 2024.", None),
    ("istat", "I furti sono 4876.4 ogni 100.000 abitanti.", None),
    # arrotondamenti e numeri inventati
    (
        "istat",
        "I furti sono circa 134.000 (fonte ISTAT, Comune di Roma, 2024).",
        "numero_non_ammesso",
    ),
    ("istat", "I furti sono 4.876 ogni 100.000 abitanti.", "numero_non_ammesso"),
    ("istat", "Nel 2023 i furti erano 134.169.", "numero_non_ammesso"),
    # cifra della voce sbagliata o senza voce
    ("istat", "I danneggiamenti sono 134.169 nel 2024.", "voce_errata"),
    ("istat", "Nel 2024 si contano 19.843 casi.", "voce_mancante"),
    # segni
    ("istat", "Le rapine in esercizi commerciali calano del -16%.", "segno_errato"),
    ("istat", "Le rapine in esercizi commerciali variano del −16%.", "segno_errato"),
    # fix round 1 - minore (c): trattino medio come segno
    (
        "istat",
        "Le rapine in esercizi commerciali variano del \u201316%.",
        "segno_errato",
    ),
    # direzione contraria al segno
    (
        "istat",
        "Le rapine in esercizi commerciali mostrano un calo tra il 2014 e il 2024 (fonte ISTAT, Comune di Roma, 2024).",
        "direzione_contraria",
    ),
    (
        "istat",
        "I furti sono in crescita (fonte ISTAT, Comune di Roma, 2024).",
        "direzione_contraria",
    ),
    # fix round 1 - importante 3: vocabolario di direzione esteso (sale/scende)
    (
        "istat",
        "Le rapine in esercizi commerciali scendono del 16%.",
        "direzione_contraria",
    ),
    ("istat", "Le rapine in esercizi commerciali sono scese.", "direzione_contraria"),
    # fix round 1 - minore (a): voce nominata senza tendenza calcolata (rottura 2016)
    ("istat", "I danneggiamenti sono in aumento.", "direzione_contraria"),
    # cifra ISTAT nel blocco sbagliato
    ("ontologia", "Il Colosseo concentra 134.169 furti.", "cifra_istat_fuori_blocco"),
    ("contesto", "La zona ha 4.876,4 visitatori.", "cifra_istat_fuori_blocco"),
    # P5: cifra ISTAT scritta dentro [SPECULATIVO], stessa regola del blocco sbagliato
    (
        "speculativo",
        "Forse i furti potrebbero essere collegati ai 134.169 casi denunciati.",
        "cifra_istat_fuori_blocco",
    ),
    # fix round 1 - minore (b): una variazione e' una cifra ISTAT solo col '%'
    (
        "istat",
        "Il totale dei delitti denunciati e' stabile negli ultimi 10 anni.",
        None,
    ),
    # numeri del contesto e marcatori d'elenco
    ("ontologia", "Tra i 12 POI analizzati, Bar 2000 e' esposto a rapina.", None),
    ("ontologia", "Tre banche su 9 sono esposte.", "numero_non_ammesso"),
    ("ontologia", "1. Rischio di rapina per Bar 2000.", None),
    # F1 (review finale): il ';' non chiude la frase, la variazione resta con la voce
    (
        "istat",
        "Nel Comune di Roma i furti denunciati nel 2024 sono 134.169 (fonte ISTAT, Comune di Roma, 2024); variazione 2014-2024: -10%.",
        None,
    ),
    # F5: fuori da [ISTAT] la direzione si controlla solo se la frase parla dei dati ISTAT
    (
        "ontologia",
        "Il furto di beni domina la zona e i furti sono in aumento per la folla.",
        None,
    ),
    ("ontologia", "Secondo l'ISTAT i furti sono in aumento.", "direzione_contraria"),
    # R1 (review 2): il solo nome del luogo non basta piu' a dire che la frase
    # parla dei dati ISTAT; servono "ISTAT", "delitti denunciati" o una cifra ISTAT
    ("contesto", "Nel Comune di Roma i furti sono in aumento.", None),
    (
        "contesto",
        "Nel Comune di Roma i delitti denunciati per furti sono in aumento.",
        "direzione_contraria",
    ),
    (
        "ontologia",
        "A Roma la folla aumenta le occasioni di furti nelle scuole.",
        None,
    ),
    (
        "ontologia",
        "La visibilita' ridotta favorisce i danneggiamenti a Roma.",
        None,
    ),
    ("contesto", "Le sale giochi di Roma attirano furti.", None),
    # R2 (review 2): in [ISTAT] i numeri del contesto fuori dal blocco DATI ISTAT
    # (POI totali, nomi dei POI) non sono ammessi; fuori da [ISTAT] si'
    ("istat", "Tra i 12 POI analizzati i furti sono 134.169.", "numero_non_ammesso"),
    ("istat", "Bar 2000 e' vicino: i furti sono 134.169.", "numero_non_ammesso"),
    ("contesto", "Bar 2000 e' esposto a furti di notte.", None),
    (
        "speculativo",
        "Forse i delitti denunciati di furti sono in aumento.",
        "direzione_contraria",
    ),
]


@pytest.mark.parametrize(("blocco", "frase", "atteso"), _CASI)
def test_tabella_dei_casi(blocco: str, frase: str, atteso: Motivo | None) -> None:
    testo = f"Sintesi.\n\n{_INTESTAZIONI[blocco]}\n{frase}\n"
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
    assert [(f.blocco, f.motivo) for f in esito.frasi] == [
        ("overview", "direzione_contraria"),
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


def test_testo_grezzo_senza_frasi_con_cifre_istat_per_m1() -> None:
    testo = (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nIl Colosseo concentra 134.169 "
        "furti. Bar 2000 e' esposto a rapina.\n\nDati statistici ISTAT [ISTAT]\n"
        "I furti sono 134.169 nel 2024.\n"
    )
    esito = _controlla(testo)
    assert esito.testo_senza_cifre_istat == (
        "Sintesi.\n\nRischi da ontologia [ONTOLOGIA]\nBar 2000 e' esposto a rapina.\n\n"
        "Dati statistici ISTAT [ISTAT]\n"
    )


def test_numeri_in_lettere_contati_non_tolti() -> None:
    testo = "Sintesi.\n\nDati statistici ISTAT [ISTAT]\nI furti sono quasi il doppio della media.\n"
    esito = _controlla(testo)
    assert esito.numeri_in_lettere == 1
    assert esito.frasi_scartate == 0


def test_metriche_per_frase() -> None:
    testo = (
        "Sintesi.\n\nDati statistici ISTAT [ISTAT]\nI furti scendono da 148.910 a "
        "134.169, un calo del -10% (fonte ISTAT, Comune di Roma, 2024).\n"
    )
    frase = [f for f in _controlla(testo).frasi if f.blocco == "istat"][0]
    assert (frase.cifre, frase.cifre_istat, frase.cifre_istat_corrette) == (3, 3, 3)
    assert frase.voci == ("THEFT",)
    assert (frase.direzione, frase.direzione_coerente) == ("giu", True)


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
    blocco = blocco_istat_poi(istat_poi(riga(variazione=-11)))
    testo = (
        "Sintesi.\n\nDati statistici ISTAT [ISTAT]\nNegli ultimi 10 anni i furti sono "
        "diminuiti dell'11% (fonte ISTAT, Comune di Roma, 2024).\n"
    )
    esito = controlla_cifre(
        testo,
        blocchi=_spans(testo),
        blocco_istat=blocco.testo,
        contesto_senza_istat=_CONTESTO,
        righe=blocco.righe,
    )
    frase = [f for f in esito.frasi if f.blocco == "istat"][0]
    assert frase.motivo is None
    assert (frase.cifre_istat, frase.cifre_istat_corrette) == (1, 1)


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
        "Dati statistici ISTAT [ISTAT]: nel Comune di Roma i furti denunciati nel 2024 "
        "sono 134.169 (fonte ISTAT, Comune di Roma, 2024).\n"
    )
    esito = _controlla(testo)
    istat = [f for f in esito.frasi if f.blocco == "istat"]
    assert len(istat) == 1
    assert istat[0].motivo is None
    assert istat[0].testo.startswith("nel Comune di Roma")
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
        riga(
            "BANKROB",
            label="rapine in banca",
            delitti=7,
            confronto=46,
            tasso=0.3,
            italia=0.2,
            variazione=None,
            motivo="meno di 20 delitti in uno dei due anni",
        ),
    )
)


def test_riferimento_di_legge_non_spezza_la_frase_ne_e_una_cifra() -> None:
    """R4 (review 2): "d.lgs. 7/2016" resta nella frase e 7 non e' una cifra."""
    frase = (
        "I danneggiamenti sono 19.843 nel 2024, ma la serie e' interrotta dalla "
        "depenalizzazione (d.lgs. 7/2016) (fonte ISTAT, Comune di Roma, 2024)."
    )
    testo = f"Sintesi.\n\nDati statistici ISTAT [ISTAT]\n{frase}\n"
    esito = _controlla_con(testo, _DANNI_E_SETTE)
    assert _frasi_istat(esito) == [(frase, None)]
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
            "Nel Comune di Roma i furti sono 200.000 (fonte ISTAT, Comune di Roma, 2024).",
            "voce_errata",
        ),
        ("Nel Comune di Roma i furti variano del +5%.", "voce_errata"),
        (
            "Nella Provincia di Roma i furti sono 200.000, in aumento del +5% (fonte ISTAT, Provincia di Roma, 2024).",
            None,
        ),
        (
            "Nel Comune di Roma i furti sono 134.169, in calo del -10% (fonte ISTAT, Comune di Roma, 2024).",
            None,
        ),
        # nessun luogo nominato per esteso: si resta per voce, come prima
        ("I furti sono in aumento.", None),
        ("I furti sono 200.000 nel 2024.", None),
    ],
)
def test_cifre_e_direzione_per_luogo_e_voce(frase: str, atteso: Motivo | None) -> None:
    """R6 (review 2): se la frase nomina un luogo delle righe valgono i suoi valori."""
    testo = f"Sintesi.\n\nDati statistici ISTAT [ISTAT]\n{frase}\n"
    assert _frasi_istat(_controlla_con(testo, _DUE_LUOGHI)) == [(frase, atteso)]


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
    """R8 (review 2): "10 340" sono due numeri ammessi, non 10.340."""
    testo = f"Sintesi.\n\nDati statistici ISTAT [ISTAT]\n{frase}\n"
    assert _frasi_istat(_controlla_con(testo, _CON_STRAPPO)) == [(frase, None)]
