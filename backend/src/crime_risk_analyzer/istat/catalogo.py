"""Catalogo delle 56 voci del dataset ISTAT 73_67 (#353).

Fonte: codelist CL_REATI_PS v1.0 (dimensione TYPE_CRIME) del dataflow IT1/73_67,
codici effettivamente disponibili nel dataset, scaricati via SDMX il 2026-10-08.
Per ogni voce: ``codice``, ``etichetta`` (italiana, dalla codelist), ``madre``
(campo Parent della codelist, ``None`` per le radici), ``legata_al_luogo`` e
``rottura_2016``.

L'USO di una voce non si scrive qui: lo deriva :func:`hazard_per_voce` dalla
:data:`~crime_risk_analyzer.istat.mappatura.MAPPATURA`, cosi' catalogo e
mappatura non possono divergere. Una voce e' *usata* se almeno un hazard la
referenzia; le altre portano uno ``stato``:

- ``usabile``: un rischio TERMINUS compatibile esiste, ma la mappatura (D3: una
  voce per rischio, nessuna somma) ha scelto un'altra voce;
- ``esclusa``: nessun rischio TERMINUS compatibile; ``motivo`` dice perche';
- ``cornice``: il totale, che entra solo come cornice del luogo (D10).

``legata_al_luogo``: sottovoce di furti o rapine che indica il luogo del fatto
(abitazione, esercizio commerciale, auto in sosta, banca, ufficio postale,
pubblica via). Le sottovoci che indicano l'oggetto rubato (autovetture,
ciclomotori, motocicli, mezzi pesanti con merci, opere d'arte) o la modalita'
(con strappo, con destrezza) non lo sono. Le sottovoci di luogo coincidono con
le categorie di luogo dello SDI delle forze di polizia (Ministero dell'Interno,
*Rapporto intersettoriale sulla criminalita' predatoria 2024*): contano i fatti
all'istituto o al luogo, non ai clienti, e tengono separate dagli esercizi
commerciali farmacie, locali ed esercizi pubblici e distributori di carburante.
ISTAT non pubblica una definizione formale delle sottovoci: queste letture sono
per indizi (confronto dei totali e categorie SDI).

Usi non fatti, da dichiarare: «Furto di merci» in centro commerciale e
gioielleria troverebbe in ``SHOPTHEF`` una voce piu' precisa dei furti in
generale, ma il rischio ``Theft_of_goods`` e' uno solo per tutte le classi e
la mappatura non scende per classe di POI (spec #353 §3): resta su ``THEFT``.

``rottura_2016``: la voce comprende fatti depenalizzati dal d.lgs. 7/2016
(danneggiamento semplice, ingiuria, falsita' in scrittura privata,
appropriazione di cose smarrite e altri): la variazione decennale non e'
confrontabile e non si calcola, ne' per le voci dei rischi ne' per la cornice
del totale. :data:`VOCI_ROTTURA_2016` ne deriva l'insieme.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from crime_risk_analyzer.istat.mappatura import MAPPATURA

__all__ = [
    "CATALOGO",
    "VOCI_ROTTURA_2016",
    "Stato",
    "Voce",
    "hazard_per_voce",
    "usata",
]

#: Stato di una voce che nessun hazard usa (vedi docstring del modulo).
Stato = Literal["usabile", "esclusa", "cornice"]


@dataclass(frozen=True)
class Voce:
    """Una voce del dataset 73_67; ``stato``/``motivo`` solo se non usata."""

    codice: str
    etichetta: str
    madre: str | None = None
    legata_al_luogo: bool = False
    rottura_2016: bool = False
    stato: Stato | None = None
    motivo: str = ""


# --- Motivi ricorrenti ---

_FUORI_ONTOLOGIA = (
    "Fuori dall'ontologia TERMINUS, che descrive rischi per luoghi e "
    "infrastrutture; coerente con i vincoli del progetto (niente profilazione)."
)
_PERSONA = (
    "Reato contro la persona: nessun rischio TERMINUS corrispondente. "
    + _FUORI_ONTOLOGIA
)
_OMICIDIO = (
    "Omicidio: e' un esito sulla persona, non un rischio per un luogo. "
    + _FUORI_ONTOLOGIA
)
_SESSUALE = (
    "Reato sessuale o sui minori: nessun rischio TERMINUS corrispondente "
    "(Child_abuse riguarda i maltrattamenti, non pubblicati in 73_67). "
    + _FUORI_ONTOLOGIA
)
_ECONOMICO = (
    "Reato economico-finanziario senza luogo fisico: nessun rischio TERMINUS "
    "corrispondente. " + _FUORI_ONTOLOGIA
)
_ORGANIZZATO = (
    "Reato associativo o di traffico: nessun rischio TERMINUS corrispondente. "
    + _FUORI_ONTOLOGIA
)
_VEICOLI = (
    "Usabile in principio per Vehicle_Theft, che pero' usa gia' i furti di "
    "autovetture (corrispondenza piu' stretta): D3 non somma voci, quindi una "
    "seconda voce per lo stesso rischio non entra."
)
_NO_ABITAZIONI = (
    "nessuna classe OSM del progetto corrisponde a un'abitazione e nessun "
    "rischio TERMINUS riguarda le abitazioni."
)

_VOCI: tuple[Voce, ...] = (
    # --- Omicidi ---
    Voce(
        "MASSMURD",
        "strage",
        stato="esclusa",
        motivo=(
            "La strage e' un esito (piu' morti), non un tipo di rischio: gli "
            "attentati dell'ontologia usano gia' la voce «attentati». "
            + _FUORI_ONTOLOGIA
        ),
    ),
    Voce("INTENHOM", "omicidi volontari consumati", stato="esclusa", motivo=_OMICIDIO),
    Voce(
        "ROBBHOM",
        "omicidi volontari consumati a scopo di furto o rapina",
        madre="INTENHOM",
        stato="esclusa",
        motivo=_OMICIDIO,
    ),
    Voce(
        "MAFIAHOM",
        "omicidi volontari consumati di tipo mafioso",
        madre="INTENHOM",
        stato="esclusa",
        motivo=_OMICIDIO,
    ),
    Voce(
        "TERRORHOM",
        "omicidi volontari consumati a scopo terroristico",
        madre="INTENHOM",
        stato="esclusa",
        motivo=(
            "Conta le vittime, non i fatti: gli attacchi terroristici "
            "dell'ontologia usano gia' la voce «attentati». " + _FUORI_ONTOLOGIA
        ),
    ),
    Voce("ATTEMPHOM", "tentati omicidi", stato="esclusa", motivo=_OMICIDIO),
    Voce("INFANTHOM", "infanticidi", stato="esclusa", motivo=_OMICIDIO),
    Voce("MANSHOM", "omicidi preterintenzionali", stato="esclusa", motivo=_OMICIDIO),
    Voce(
        "UNINTHOM",
        "omicidi colposi",
        stato="esclusa",
        motivo=(
            "Reato colposo contro la persona (incidenti stradali, sul lavoro): "
            "nessun rischio TERMINUS corrispondente. " + _FUORI_ONTOLOGIA
        ),
    ),
    Voce(
        "ROADHOM",
        "omicidi colposi da incidente stradale",
        madre="UNINTHOM",
        stato="esclusa",
        motivo=(
            "Incidente stradale: nessun rischio TERMINUS di incidente. "
            + _FUORI_ONTOLOGIA
        ),
    ),
    # --- Altri reati contro la persona ---
    Voce("BLOWS", "percosse", stato="esclusa", motivo=_PERSONA),
    Voce("CULPINJU", "lesioni dolose"),
    Voce("MENACE", "minacce", stato="esclusa", motivo=_PERSONA),
    Voce("KIDNAPP", "sequestri di persona"),
    Voce(
        "OFFENCE",
        "ingiurie",
        rottura_2016=True,
        stato="esclusa",
        motivo=_PERSONA + " Depenalizzata dal d.lgs. 7/2016.",
    ),
    # --- Reati sessuali e sui minori ---
    Voce("RAPE", "violenze sessuali", stato="esclusa", motivo=_SESSUALE),
    Voce("RAPEUN18", "atti sessuali con minorenne", stato="esclusa", motivo=_SESSUALE),
    Voce("CORRUPUN18", "corruzione di minorenne", stato="esclusa", motivo=_SESSUALE),
    Voce(
        "PROSTI",
        "sfruttamento e favoreggiamento della prostituzione",
        stato="esclusa",
        motivo=_SESSUALE,
    ),
    Voce(
        "PORNO",
        "pornografia minorile e detenzione di materiale pedopornografico",
        stato="esclusa",
        motivo=_SESSUALE,
    ),
    # --- Furti ---
    Voce("THEFT", "furti"),
    Voce("BAGTHEF", "furti con strappo", madre="THEFT"),
    Voce(
        "PICKTHEF",
        "furti con destrezza",
        madre="THEFT",
        stato="esclusa",
        motivo=(
            "Nessun rischio TERMINUS di borseggio: i furti dell'ontologia sono ai "
            "danni di luoghi e infrastrutture, e lo scippo ha la sua voce (furti "
            "con strappo)."
        ),
    ),
    Voce(
        "BURGTHEF",
        "furti in abitazioni",
        madre="THEFT",
        legata_al_luogo=True,
        stato="esclusa",
        motivo=(
            "Conta i furti nelle abitazioni (categoria di luogo SDI): " + _NO_ABITAZIONI
        ),
    ),
    Voce(
        "SHOPTHEF",
        "furti in esercizi commerciali",
        madre="THEFT",
        legata_al_luogo=True,
    ),
    Voce(
        "VEHITHEF",
        "furti in auto in sosta",
        madre="THEFT",
        legata_al_luogo=True,
        stato="esclusa",
        motivo=(
            "Conta i furti dentro le auto in sosta (categoria di luogo SDI): "
            "nessuna classe OSM del progetto corrisponde a un parcheggio, e "
            "Vehicle_Theft e' il furto del veicolo, non dal veicolo."
        ),
    ),
    Voce("ARTTHEF", "furti di opere d'arte e materiale archeologico", madre="THEFT"),
    Voce(
        "TRUCKTHEF",
        "furti di automezzi pesanti trasportanti merci",
        madre="THEFT",
        stato="esclusa",
        motivo=(
            "Nessun rischio TERMINUS di furto di mezzi pesanti con il carico: i "
            "furti di merci dell'ontologia avvengono in magazzini, depositi e "
            "negozi."
        ),
    ),
    Voce(
        "MOPETHEF",
        "furti di ciclomotori",
        madre="THEFT",
        stato="usabile",
        motivo=_VEICOLI,
    ),
    Voce(
        "MOTORTHEF",
        "furti di motocicli",
        madre="THEFT",
        stato="usabile",
        motivo=_VEICOLI,
    ),
    Voce("CARTHEF", "furti di autovetture", madre="THEFT"),
    # --- Rapine ---
    Voce("ROBBER", "rapine"),
    Voce(
        "HOUSEROB",
        "rapine in abitazione",
        madre="ROBBER",
        legata_al_luogo=True,
        stato="esclusa",
        motivo=(
            "Conta le rapine nelle abitazioni (categoria di luogo SDI): "
            + _NO_ABITAZIONI
        ),
    ),
    Voce("BANKROB", "rapine in banca", madre="ROBBER", legata_al_luogo=True),
    Voce("POSTROB", "rapine in uffici postali", madre="ROBBER", legata_al_luogo=True),
    Voce(
        "SHOPROB",
        "rapine in esercizi commerciali",
        madre="ROBBER",
        legata_al_luogo=True,
    ),
    Voce("STREETROB", "rapine in pubblica via", madre="ROBBER", legata_al_luogo=True),
    # --- Reati economici, informatici, contro la proprieta' intellettuale ---
    Voce(
        "EXTORT",
        "estorsioni",
        stato="esclusa",
        motivo=(
            "Nessun rischio TERMINUS di racket o estorsione ai danni di un "
            "luogo. " + _FUORI_ONTOLOGIA
        ),
    ),
    # SWINCYB e COUNTER: niente corrispondenza parziale (decisione #353, spec §7).
    Voce(
        "SWINCYB",
        "truffe e frodi informatiche",
        stato="esclusa",
        motivo=(
            "Il rischio TERMINUS piu' vicino (biglietti contraffatti di "
            "spettatori e viaggiatori) e' un rischio di accesso e "
            "sovraffollamento, non una frode: sovrapposizione minima e non "
            "stimabile."
        ),
    ),
    Voce("CYBERCRIM", "delitti informatici"),
    Voce(
        "COUNTER",
        "contraffazione di marchi e prodotti industriali",
        stato="esclusa",
        motivo=(
            "Il rischio TERMINUS piu' vicino (contraffazione di generi "
            "alimentari) e' un rischio sanitario, non di marchi: sovrapposizione "
            "minima e non stimabile."
        ),
    ),
    Voce(
        "INTPROP",
        "violazione della proprietà intellettuale",
        stato="esclusa",
        motivo=_ECONOMICO,
    ),
    Voce("RECEIV", "ricettazione", stato="esclusa", motivo=_ECONOMICO),
    Voce(
        "MONEYLAU",
        "riciclaggio e impiego di denaro, beni o utilità di provenienza illecita",
        stato="esclusa",
        motivo=_ECONOMICO,
    ),
    Voce("USURY", "usura", stato="esclusa", motivo=_ECONOMICO),
    # --- Danneggiamenti e incendi ---
    Voce("DAMAGE", "danneggiamenti", rottura_2016=True),
    Voce("ARSON", "incendi"),
    Voce("FOREARS", "incendi boschivi", madre="ARSON"),
    Voce("DAMARS", "danneggiamento seguito da incendio"),
    # --- Stupefacenti, attentati, criminalita' organizzata ---
    Voce(
        "DRUG",
        "normativa sugli stupefacenti",
        stato="esclusa",
        motivo=(
            "Spaccio e detenzione non sono rischi TERMINUS (il furto di farmaci "
            "usa i furti). " + _FUORI_ONTOLOGIA
        ),
    ),
    Voce("ATTACK", "attentati"),
    Voce(
        "CRIMASS", "associazione per delinquere", stato="esclusa", motivo=_ORGANIZZATO
    ),
    Voce(
        "MAFIASS", "associazione di tipo mafioso", stato="esclusa", motivo=_ORGANIZZATO
    ),
    Voce("SMUGGL", "contrabbando", stato="esclusa", motivo=_ORGANIZZATO),
    # --- Residuo e totale ---
    Voce(
        "OTHCRIM",
        "altri delitti",
        # Per indizi: voce residua che comprende reati depenalizzati nel 2016
        # (falsita' in scrittura privata, appropriazione di cose smarrite).
        rottura_2016=True,
        stato="esclusa",
        motivo=(
            "Voce residua eterogenea senza contenuto definito: nessun rischio "
            "TERMINUS le corrisponde."
        ),
    ),
    Voce(
        "TOT",
        "totale",
        # Certa: il totale comprende i danneggiamenti (DAMAGE) e le ingiurie.
        rottura_2016=True,
        stato="cornice",
        motivo=(
            "Totale dei delitti: entra solo come cornice del luogo, mai "
            "collegato a un rischio (D10)."
        ),
    ),
)

#: codice -> voce, nell'ordine della codelist.
CATALOGO: dict[str, Voce] = {voce.codice: voce for voce in _VOCI}


def hazard_per_voce() -> dict[str, tuple[str, ...]]:
    """Voce ISTAT -> hazard che la usano, derivato da ``MAPPATURA``."""
    per_voce: dict[str, list[str]] = {}
    for hazard, mappatura in MAPPATURA.items():
        if mappatura.voce_istat:
            per_voce.setdefault(mappatura.voce_istat, []).append(hazard)
    return {voce: tuple(hazard) for voce, hazard in per_voce.items()}


def usata(codice: str) -> bool:
    """``True`` se almeno un hazard della mappatura usa la voce ``codice``."""
    return codice in hazard_per_voce()


#: Voci senza variazione decennale (serie interrotta dal d.lgs. 7/2016), dal
#: campo ``rottura_2016`` del catalogo. Vale per le righe dei rischi
#: (danneggiamenti) e per la cornice del totale, che comprende anch'essa fatti
#: depenalizzati (#353): una sola regola, nessuna eccezione per la cornice.
VOCI_ROTTURA_2016: frozenset[str] = frozenset(
    codice for codice, voce in CATALOGO.items() if voce.rottura_2016
)
