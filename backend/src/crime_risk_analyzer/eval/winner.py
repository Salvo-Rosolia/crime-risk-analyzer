"""Criterio di vittoria lessicografico (#157, spec-valutazione §2).

Decide il vincitore del confronto tra due modelli sulle MEDIE delle K
ripetizioni, in ordine lessicografico dichiarato a priori:
  1. hallucination (piu' basso vince)
  2. grounding     (piu' alto vince)
  3. latency_ms    (piu' basso vince)
  4. cost_usd      (piu' basso vince)
Due valori sono 'pari' se coincidono alla precisione con cui la metrica viene
stampata (3/3/0/6 decimali) → si passa all'asse successivo. Parita' su tutti e 4
gli assi → nessun vincitore (pareggio esplicito), nessun tie-break artificiale.

Gli assi 3 e 4 sono SPAREGGI DISATTIVABILI (#236, ``operational_tiebreak``): su
una coppia di bracci i cui prompt hanno lunghezza diversa per costruzione — il
braccio senza ontologia non riceve hazard, vulnerabilita' e citazioni — latenza
e costo piu' bassi non sono un merito, e un verdetto deciso da loro misurerebbe
la lunghezza del prompt. Li' la catena si ferma alla qualita' e il pareggio resta
dichiarato. Tra due MODELLI, che ricevono lo stesso prompt, restano spareggi
legittimi: il default non cambia.

LIMITE (#164-D): 'grounding' e' un asse ridondante, NON un secondo criterio
indipendente. E' il complemento lineare di 'hallucination' sullo stesso
denominatore (le asserzioni): ``hallucination == 1 - grounding`` quando le
asserzioni sono > 0 (vedi metrics.py). Quindi il tie-break su 'grounding' non
decide di fatto mai: quando 'hallucination' pareggia (stessa griglia di
arrotondamento) pareggia anche 'grounding'; e nei corner degeneri (narrativa
vuota vs piena-senza-asserzioni) e' 'hallucination' a decidere (0.0 vs 1.0).
'grounding' resta nella catena per trasparenza, non aggiunge informazione
ortogonale. Un 2° asse davvero ortogonale (copertura/integrita' §2) e' un
miglioramento futuro, non implementato qui per non alterare la semantica del
verdetto prima dei dati reali.

Nota di scope (#157): l'asse 'hallucination' e' il PROXY testuale gia' in
Metrics; 'tasso di intervento del filtro' e 'allucinazioni residue' (spec §2)
sono deliverable separati, non implementati qui.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from crime_risk_analyzer.eval.compare import MetricValues


@dataclass(frozen=True)
class _AxisSpec:
    name: str
    ndigits: int  # precisione di stampa = tolleranza di parita'
    higher_better: bool
    get: Callable[[MetricValues], float]


#: Assi di QUALITA' (i due proxy testuali): valgono su qualunque coppia di bracci.
_QUALITY_AXES: tuple[_AxisSpec, ...] = (
    _AxisSpec("hallucination", 3, False, lambda m: m.hallucination),
    _AxisSpec("grounding", 3, True, lambda m: m.grounding),
)

#: Assi OPERATIVI (misure dirette), usati SOLO come spareggio dopo la qualita'.
#: Separati dai precedenti perche' non su ogni coppia sono un merito: quando i
#: due bracci ricevono prompt di lunghezza diversa per costruzione, chi ha il
#: prompt piu' corto e' piu' rapido ed economico a prescindere da cio' che dice
#: (#236) — vedi ``operational_tiebreak`` in :func:`decide_winner`.
_OPERATIONAL_AXES: tuple[_AxisSpec, ...] = (
    _AxisSpec("latency_ms", 0, False, lambda m: m.latency_ms),
    _AxisSpec("cost_usd", 6, False, lambda m: m.cost_usd),
)

#: Ordine lessicografico + direzione + precisione. Le precisioni combaciano con
#: i formati di compare.py (grounding/halluc .3f, latency .0f, cost .6f): la
#: parita' e' definita "a cio' che si stampa".
_AXES: tuple[_AxisSpec, ...] = _QUALITY_AXES + _OPERATIONAL_AXES

#: Ragione stampata quando la qualita' pareggia e lo spareggio operativo e'
#: escluso (#236). Il verdetto trattenuto va MOTIVATO: un ``winner=None`` muto
#: sarebbe indistinguibile dal pareggio a quattro assi di #157, che e' un altro
#: fatto (li' anche latenza e costo coincidono).
NO_OPERATIONAL_TIEBREAK_REASON = (
    "verdetto non decidibile: le metriche di qualita' pareggiano e velocita'/"
    "costo non sono spareggi validi su questa coppia, perche' il prompt del "
    "braccio senza ontologia e' strutturalmente piu' corto"
)

#: Precisione di stampa per asse, esposta al renderer (Task 4).
AXIS_PRECISION: dict[str, int] = {spec.name: spec.ndigits for spec in _AXES}


class AxisComparison(BaseModel):
    """Confronto su un singolo asse: valori grezzi + esito a precisione di stampa."""

    axis: str
    value_a: float
    value_b: float
    outcome: Literal["a", "b", "tie"]


class Winner(BaseModel):
    """Verdetto lessicografico con motivazione.

    ``winner`` e ``deciding_axis`` sono ``None`` in caso di pareggio totale.
    ``chain`` elenca gli assi valutati fino al decisivo incluso (o tutti quelli
    AMMESSI se pareggio): rende la decisione auditabile. Un asse escluso dallo
    spareggio non compare in ``chain`` — non ha prodotto un "pari", non e' stato
    guardato.
    """

    label_a: str
    label_b: str
    winner: str | None
    deciding_axis: str | None
    chain: list[AxisComparison]
    #: Perche' non c'e' un vincitore, quando la ragione non e' il semplice
    #: pareggio su tutti gli assi ammessi (#236: spareggio operativo escluso).
    #: Vuota nel caso di #157, cosi' il report non cambia dove non deve.
    no_winner_reason: str = ""


def _axis_outcome(spec: _AxisSpec, a: float, b: float) -> Literal["a", "b", "tie"]:
    ra = round(a, spec.ndigits)
    rb = round(b, spec.ndigits)
    if ra == rb:
        return "tie"
    if spec.higher_better:
        return "a" if ra > rb else "b"
    return "a" if ra < rb else "b"


def decide_winner(
    mean_a: MetricValues,
    mean_b: MetricValues,
    *,
    label_a: str,
    label_b: str,
    operational_tiebreak: bool = True,
) -> Winner:
    """Applica il lessicografico §2 sulle medie; ritorna il verdetto motivato.

    ``operational_tiebreak=False`` restringe la catena ai soli assi di QUALITA'
    (:data:`_QUALITY_AXES`): se pareggiano, il verdetto e' «nessun vincitore» con
    :data:`NO_OPERATIONAL_TIEBREAK_REASON`, non un vincitore silenzioso su
    latenza o costo. Serve alla coppia con/senza ontologia (#236), in cui il
    braccio ablato riceve un prompt strutturalmente piu' corto — niente hazard,
    vulnerabilita' e citazioni — ed e' quindi piu' rapido ed economico PER
    COSTRUZIONE: uno spareggio su quegli assi premierebbe la lunghezza del
    prompt. Il default resta ``True``, quindi il confronto tra due MODELLI
    (#157), dove il prompt e' lo stesso e una latenza piu' bassa e' un merito
    del modello, non cambia comportamento.
    """
    axes = _AXES if operational_tiebreak else _QUALITY_AXES
    chain: list[AxisComparison] = []
    for spec in axes:
        a = spec.get(mean_a)
        b = spec.get(mean_b)
        outcome = _axis_outcome(spec, a, b)
        chain.append(
            AxisComparison(axis=spec.name, value_a=a, value_b=b, outcome=outcome)
        )
        if outcome != "tie":
            winner = label_a if outcome == "a" else label_b
            return Winner(
                label_a=label_a,
                label_b=label_b,
                winner=winner,
                deciding_axis=spec.name,
                chain=chain,
            )
    return Winner(
        label_a=label_a,
        label_b=label_b,
        winner=None,
        deciding_axis=None,
        chain=chain,
        no_winner_reason=(
            "" if operational_tiebreak else NO_OPERATIONAL_TIEBREAK_REASON
        ),
    )
