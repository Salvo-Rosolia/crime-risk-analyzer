"""Etichette delle voci riconosciute per flessione (#392).

Trastevere: il modello scrive "i danneggiamenti seguiti da incendio" per la voce
"danneggiamento seguito da incendio"; il controllo deve riconoscere quella voce
(non "danneggiamenti", che e' un'altra voce senza tendenza calcolata).
"""

from __future__ import annotations

import re

import pytest

from crime_risk_analyzer.i18n.terminus_labels import label_it
from crime_risk_analyzer.istat.blocco import blocco_istat_poi
from crime_risk_analyzer.istat.catalogo import CATALOGO
from crime_risk_analyzer.istat.cifre import (
    FraseControllata,
    SpanBlocco,
    controlla_cifre,
    voci_nominate,
)
from crime_risk_analyzer.istat.mappatura import MAPPATURA
from crime_risk_analyzer.istat.righe import MOTIVO_ROTTURA_2016, RigaIstat
from tests.istat._fattorie import RAPINE_IN_BANCA, collegamento, istat_poi, riga

_DAMARS = riga(
    "DAMARS",
    label="danneggiamento seguito da incendio",
    delitti=383,
    confronto=286,
    tasso=13.9,
    italia=12.6,
    variazione=34,
    collegamenti=(collegamento("Incendiary_attack", "Attacco incendiario"),),
)
_DAMAGE = riga(
    "DAMAGE",
    label="danneggiamenti",
    delitti=19843,
    confronto=16417,
    tasso=721.2,
    italia=471.5,
    variazione=None,
    motivo=MOTIVO_ROTTURA_2016,
    collegamenti=(collegamento("Vandalism", "Vandalismo"),),
)
_STRAPPO = riga(
    "BAGTHEF",
    label="furti con strappo",
    delitti=4200,
    confronto=3900,
    tasso=152.7,
    italia=24.1,
    variazione=8,
    collegamenti=(collegamento("Purse_snatching", "Scippo", "esatta"),),
)
_GIOIELLERIA = riga(
    "SHOPTHEF",
    label="furti in esercizi commerciali",
    delitti=9000,
    confronto=11000,
    tasso=327.1,
    italia=150.2,
    variazione=-18,
    collegamenti=(
        collegamento("Jewelry_theft", "Furto in gioielleria", "piu_stretta"),
    ),
)
#: THEFT, "furti", variazione -10, collegato al rischio "Furto di beni".
_FURTI = riga()
_INTESTAZIONE = "Rischi da ontologia [ONTOLOGIA]\n"


def _frase(frase: str, *righe: RigaIstat) -> FraseControllata:
    blocco = blocco_istat_poi(istat_poi(*righe))
    testo = _INTESTAZIONE + frase
    esito = controlla_cifre(
        testo,
        blocchi=[SpanBlocco("ontologia", 0, len(_INTESTAZIONE), len(testo))],
        blocco_istat=blocco.testo,
        contesto_senza_istat="ZONA: Trastevere",
        righe=blocco.righe,
    )
    (controllata,) = [f for f in esito.frasi if f.blocco == "ontologia"]
    return controllata


_TRASTEVERE = (
    "Sempre per il Comune di Roma (2024), {voce} hanno un tasso più alto rispetto "
    "alla media nazionale e mostrano una crescita dal 2014."
)


@pytest.mark.parametrize(
    "voce",
    [
        "i danneggiamenti seguiti da incendio",
        "i **danneggiamenti seguiti da incendio**",
        "il danneggiamento seguito da incendio",
        "i Danneggiamenti Seguiti da Incendio",
    ],
)
def test_trastevere_la_frase_giusta_al_plurale_resta(voce: str) -> None:
    frase = _frase(_TRASTEVERE.format(voce=voce), _DAMAGE, _DAMARS)
    assert frase.voci == ("DAMARS",)
    assert frase.direzione_coerente is True
    assert frase.confronto_coerente is True
    assert frase.motivo is None


@pytest.mark.parametrize(
    "frase",
    [
        "Nel Comune di Roma i danneggiamenti seguiti da incendio sono in calo "
        "dal 2014.",
        "Nel Comune di Roma i **danneggiamenti seguiti da incendio** sono in calo "
        "dal 2014.",
        "Nel Comune di Roma il danneggiamento seguito da incendio e' in calo dal 2014.",
    ],
)
def test_la_tendenza_sbagliata_al_plurale_si_toglie(frase: str) -> None:
    controllata = _frase(frase, _DAMAGE, _DAMARS)
    assert controllata.voci == ("DAMARS",)
    assert controllata.motivo == "direzione_contraria"


def test_le_due_voci_nominate_separatamente_restano_entrambe() -> None:
    etichette = [("DAMARS", _DAMARS.voce_label), ("DAMAGE", "danneggiamenti")]
    frase = (
        "Nel Comune di Roma i danneggiamenti hanno un tasso più alto della media "
        "nazionale e i danneggiamenti seguiti da incendio anche."
    )
    assert voci_nominate(frase, etichette) == {"DAMAGE", "DAMARS"}
    # DAMAGE non ha tendenza: una tendenza scritta per entrambe non e' verificabile.
    controllata = _frase(
        "Nel Comune di Roma i danneggiamenti e i danneggiamenti seguiti da incendio "
        "sono in crescita dal 2014.",
        _DAMAGE,
        _DAMARS,
    )
    assert controllata.voci == ("DAMAGE", "DAMARS")
    assert controllata.motivo == "direzione_contraria"


@pytest.mark.parametrize(
    ("etichetta", "testo"),
    [
        ("danneggiamenti", "il danneggiamento"),
        ("danneggiamento seguito da incendio", "i danneggiamenti seguiti da incendio"),
        ("rapine", "la rapina"),
        ("furti", "il furto"),
        ("furti", "il FURTO"),
        ("delitti informatici", "il delitto informatico"),
        ("lesioni dolose", "la lesione dolosa"),
        ("rapine in pubblica via", "la rapina in pubblica via"),
        ("rapine in banca", "la rapina in banche"),
        ("incendi", "l'incendio"),
        ("incendi boschivi", "l’incendio boschivo"),
        ("rapine in uffici postali", "la rapina in ufficio postale"),
        ("furti in esercizi commerciali", "il furto in esercizio commerciale"),
        ("sequestri di persona", "il sequestro di persone"),
        ("truffe e frodi informatiche", "la truffa e frode informatica"),
        ("Furti di opere d’arte", "il furto di opere d'arte"),
        (
            "furti di opere d'arte e materiale archeologico",
            "furto di opere d’arte e materiali archeologici",
        ),
    ],
)
def test_singolare_plurale_maschile_femminile_non_cambiano_la_voce(
    etichetta: str, testo: str
) -> None:
    frase = f"Nel Comune di Roma {testo} e' in calo."
    assert voci_nominate(frase, [("V", etichetta)]) == {"V"}


@pytest.mark.parametrize(
    "testo",
    ["i furtivi movimenti", "il furgone", "le rapinatrici", "gli incendiari"],
)
def test_parole_diverse_con_la_stessa_radice_non_nominano_la_voce(testo: str) -> None:
    etichette = [("THEFT", "furti"), ("ROBBER", "rapine"), ("ARSON", "incendi")]
    assert voci_nominate(testo, etichette) == set()


def test_le_parole_di_3_lettere_non_si_flettono() -> None:
    # "via" non diventa la radice "v" (che varrebbe "va", "ve", "vi"...): la regola
    # e' prudente e lascia fuori anche "pubbliche vie" (limite dichiarato).
    etichette = [("STREETROB", "rapine in pubblica via")]
    assert voci_nominate("le rapine in pubblica vi", etichette) == set()
    assert voci_nominate("la rapina in pubblica via", etichette) == {"STREETROB"}


def test_a_parita_di_lunghezza_la_voce_prevale_sul_rischio() -> None:
    # "rapina in banca" (rischio) e "rapine in banca" (voce) hanno le stesse
    # radici: lo span va alla voce, che resta nominata anche senza tendenza.
    controllata = _frase(
        "Nel Comune di Roma la rapina in banca resta un rischio.", RAPINE_IN_BANCA
    )
    assert controllata.voci == ("BANKROB",)


def test_etichette_con_le_stesse_radici_valgono_per_tutte_le_loro_voci() -> None:
    # Un rischio collegato a piu' voci (C1), anche scritto con un'altra flessione:
    # il pezzo di testo e' consumato dalla prima, ma vale anche per le altre.
    etichette = [("A", "furti di beni"), ("B", "furto di beni"), ("C", "furto di beni")]
    assert voci_nominate("il furto di beni e' in calo", etichette) == {"A", "B", "C"}


def test_il_tasso_della_voce_al_singolare_e_un_marcatore() -> None:
    # Senza "dal 2014" ne' confronti l'unico marcatore e' "tasso del <voce>".
    controllata = _frase(
        "Nel Comune di Roma il tasso del furto con strappo e' in calo.", _STRAPPO
    )
    assert controllata.parla_di_istat is True
    assert controllata.motivo == "direzione_contraria"


def test_il_rischio_collegato_piu_lungo_prevale_sulla_voce_generica() -> None:
    # "furto" e' anche la voce "furti" (THEFT), ma il rischio "Furto in
    # gioielleria" (collegato a SHOPTHEF) lo contiene e consuma lo span.
    controllata = _frase(
        "Nel Comune di Roma il furto in gioielleria e' in calo dal 2014.",
        _FURTI,
        _GIOIELLERIA,
    )
    assert controllata.voci == ("SHOPTHEF",)
    assert controllata.motivo is None


# --- Ricerca sistematica sul catalogo reale (#392 punto 3) ---


def _etichette_reali() -> list[str]:
    """Etichette delle 56 voci del catalogo e dei rischi collegati, in minuscolo."""
    voci = {v.etichetta.lower() for v in CATALOGO.values()}
    rischi = {label_it(h).lower() for h, m in MAPPATURA.items() if m.voce_istat}
    return sorted(voci | rischi)


#: Desinenze scambiate da :func:`_altra_flessione` (la prima che combacia).
_SCAMBI = (
    ("che", "ca"),
    ("ghe", "ga"),
    ("ca", "che"),
    ("ga", "ghe"),
    ("io", "i"),
    ("o", "i"),
    ("a", "e"),
    ("e", "i"),
    ("i", "o"),
)


def _altra_flessione(etichetta: str) -> str:
    """Ogni parola di almeno 4 lettere col numero (o genere) opposto, alla buona."""

    def gira(m: re.Match[str]) -> str:
        parola = m.group()
        if len(parola) >= 4:
            for da, a in _SCAMBI:
                if parola.endswith(da):
                    return parola[: -len(da)] + a
        return parola

    return re.sub(r"\w+", gira, etichetta)


def _nomina(testo: str, etichetta: str) -> bool:
    return bool(voci_nominate(testo, [("X", etichetta)]))


def _coppie_contenute() -> list[tuple[str, str]]:
    """``(corta, lunga)``: la lunga nomina anche la corta se presa da sola."""
    etichette = _etichette_reali()
    return [
        (corta, lunga)
        for corta in etichette
        for lunga in etichette
        if corta != lunga and _nomina(lunga, corta) and not _nomina(corta, lunga)
    ]


def _collisioni() -> set[frozenset[str]]:
    """Etichette diverse che si nominano a vicenda (stessa radice parola per parola)."""
    etichette = _etichette_reali()
    return {
        frozenset((a, b))
        for a in etichette
        for b in etichette
        if a < b and _nomina(a, b) and _nomina(b, a)
    }


_COPPIE = _coppie_contenute()


def test_la_ricerca_trova_le_coppie_note() -> None:
    assert ("danneggiamenti", "danneggiamento seguito da incendio") in _COPPIE
    assert ("incendi", "danneggiamento seguito da incendio") in _COPPIE
    assert ("furti", "furti con strappo") in _COPPIE
    assert ("incendi", "incendi boschivi") in _COPPIE
    assert ("furti", "furto in gioielleria") in _COPPIE


@pytest.mark.parametrize(
    ("corta", "lunga"), _COPPIE, ids=[f"{c} < {lu}" for c, lu in _COPPIE]
)
def test_l_etichetta_piu_lunga_consuma_lo_span(corta: str, lunga: str) -> None:
    etichette = [("CORTA", corta), ("LUNGA", lunga)]
    for forma in (lunga, _altra_flessione(lunga)):
        frase = f"Nel Comune di Roma i dati su {forma} sono in calo."
        assert voci_nominate(frase, etichette) == {"LUNGA"}, forma
        assert voci_nominate(frase, etichette[::-1]) == {"LUNGA"}, forma


#: Collisioni nel catalogo reale: radici uguali parola per parola. Sono tutte fra
#: un rischio collegato e la voce a cui e' collegato (stessa voce, nessun danno).
_COLLISIONI_NOTE = {
    frozenset(("rapina in banca", "rapine in banca")),
}


def test_le_collisioni_del_catalogo_sono_solo_quelle_note() -> None:
    assert _collisioni() == _COLLISIONI_NOTE


def test_le_collisioni_note_portano_alla_stessa_voce() -> None:
    assert MAPPATURA["Bank_robbery"].voce_istat == "BANKROB"
    assert label_it("Bank_robbery").lower() == "rapina in banca"
    assert CATALOGO["BANKROB"].etichetta == "rapine in banca"
