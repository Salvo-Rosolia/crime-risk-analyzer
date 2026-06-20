"""Scenari demo precaricati e relativo modello Pydantic.

L'endpoint ``GET /scenarios`` (vedi ``backend/orchestrator.md``) espone i 10
scenari pre-caricati della demo. È la **fonte unica** anche per il frontend, che
popola le card scenario da qui invece di tenere una copia hardcoded
(``spec-frontend.md`` §"10 Scenari pre-caricati").

I 10 scenari coprono 4 città (Roma, Milano, Napoli, Torino) per dimostrare la
natura *city-agnostic* del sistema (contributo C1). Sono dati statici e
**indipendenti dall'ontologia**: non serve il grafo per servirli.

Tre zone — Colosseo, Stazione Termini, Duomo — hanno una cache di analisi
precalcolata in ``frontend/public/demo/cache/<id>.json``. Per quelle, l'``id``
dello scenario coincide con la chiave del file di cache, così il fallback di
cache del frontend (``/demo/cache/<id>.json``) si risolve correttamente.
"""

from pydantic import BaseModel, Field


class ScenarioPreset(BaseModel):
    """Uno scenario demo precaricato esposto da ``GET /scenarios``.

    I campi rispecchiano quelli consumati dal frontend (``src/ui.js``,
    ``src/app.js``): ``id`` come chiave/identificativo (anche per il fallback di
    cache), ``city``/``zone``/``type`` per la card, ``zona`` come stringa pronta
    per il geocoding.
    """

    id: str = Field(
        description="Identificativo stabile; per le zone con cache è la chiave cache."
    )
    city: str = Field(
        description="Città dello scenario (accento cromatico city-agnostic nel FE)."
    )
    zone: str = Field(description="Etichetta breve della zona, mostrata nella card.")
    type: str = Field(
        description="Descrizione del tipo di zona (sottotitolo della card)."
    )
    zona: str = Field(
        description='Stringa "Zona, Città" pronta per il geocoding/analisi.'
    )


# Lista canonica dei 10 scenari (allineata a ``spec-frontend.md`` §DEMO_SCENARIOS).
# Roma (5), Milano (2), Napoli (2), Torino (1). Le tre zone con cache di analisi
# usano come ``id`` la chiave del rispettivo file (colosseo/termini/duomo).
_SCENARIOS: tuple[ScenarioPreset, ...] = (
    ScenarioPreset(
        id="colosseo",
        city="Roma",
        zone="Colosseo",
        type="area archeologica, alto afflusso",
        zona="Colosseo, Roma",
    ),
    ScenarioPreset(
        id="termini",
        city="Roma",
        zone="Stazione Termini",
        type="hub trasporti",
        zona="Stazione Termini, Roma",
    ),
    ScenarioPreset(
        id="eur",
        city="Roma",
        zone="EUR",
        type="quartiere direzionale",
        zona="EUR, Roma",
    ),
    ScenarioPreset(
        id="pigneto",
        city="Roma",
        zone="Pigneto",
        type="quartiere misto, periferia interna",
        zona="Pigneto, Roma",
    ),
    ScenarioPreset(
        id="san-giovanni",
        city="Roma",
        zone="Piazza San Giovanni",
        type="grande piazza",
        zona="Piazza San Giovanni, Roma",
    ),
    ScenarioPreset(
        id="duomo",
        city="Milano",
        zone="Duomo",
        type="centro storico",
        zona="Duomo, Milano",
    ),
    ScenarioPreset(
        id="milano-centrale",
        city="Milano",
        zone="Stazione Centrale",
        type="hub trasporti",
        zona="Stazione Centrale, Milano",
    ),
    ScenarioPreset(
        id="spaccanapoli",
        city="Napoli",
        zone="Spaccanapoli",
        type="centro storico",
        zona="Spaccanapoli, Napoli",
    ),
    ScenarioPreset(
        id="garibaldi",
        city="Napoli",
        zone="Piazza Garibaldi",
        type="stazione",
        zona="Piazza Garibaldi, Napoli",
    ),
    ScenarioPreset(
        id="porta-nuova",
        city="Torino",
        zone="Porta Nuova",
        type="stazione + centro",
        zona="Porta Nuova, Torino",
    ),
)


def get_scenarios() -> list[ScenarioPreset]:
    """Restituisce i 10 scenari demo precaricati.

    Dati statici (nessun accesso all'ontologia o alla rete). Ritorna una nuova
    lista a ogni chiamata per evitare condivisione accidentale di stato mutabile.
    """
    return list(_SCENARIOS)
