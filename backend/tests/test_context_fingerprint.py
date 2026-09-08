"""Impronta del contesto di zona (#242): determinismo e sensibilita'."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from crime_risk_analyzer.analyze_narrative import ZoneNarrativeRequest
from crime_risk_analyzer.context_fingerprint import fingerprint
from crime_risk_analyzer.overpass_client import Poi
from crime_risk_analyzer.poi_narrative import PoiNarrativeRequest


def _poi(
    poi_id: str = "node/1",
    name: str = "Banca A",
    terminus_class: str = "Bank",
    lat: float = 41.8900,
    lon: float = 12.4920,
) -> Poi:
    return {
        "id": poi_id,
        "name": name,
        "lat": lat,
        "lon": lon,
        "osm_tags": "amenity=bank",
        "terminus_class": terminus_class,
        "citta": "Roma",
    }


def test_stessa_lista_stesso_digest() -> None:
    """Determinismo: due esecuzioni sulla stessa lista devono coincidere,
    altrimenti il confronto in /analyze/poi rifiuterebbe contesti identici."""
    pois = [_poi(), _poi("node/2", "Liceo Cavour", "School")]
    assert fingerprint(pois) == fingerprint(list(pois))


def test_digest_e_un_hexdigest_sha256() -> None:
    assert len(fingerprint([_poi()])) == 64
    assert all(c in "0123456789abcdef" for c in fingerprint([_poi()]))


def test_poi_aggiunto_cambia_il_digest() -> None:
    assert fingerprint([_poi()]) != fingerprint([_poi(), _poi("node/2", "Bar")])


def test_poi_rimosso_cambia_il_digest() -> None:
    due = [_poi(), _poi("node/2", "Bar")]
    assert fingerprint(due) != fingerprint([_poi()])


def test_nome_diverso_cambia_il_digest() -> None:
    """Il nome del POI entra nel prompt (vicinato e punto selezionato)."""
    assert fingerprint([_poi()]) != fingerprint([_poi(name="Banca B")])


def test_classe_diversa_cambia_il_digest() -> None:
    """La classe TERMINUS guida composizione della zona ed etichette IT."""
    assert fingerprint([_poi()]) != fingerprint([_poi(terminus_class="School")])


def test_coordinata_diversa_cambia_il_digest() -> None:
    """Le coordinate determinano le distanze dei vicini nel prompt."""
    assert fingerprint([_poi()]) != fingerprint([_poi(lat=41.8901)])


def test_ordine_diverso_cambia_il_digest() -> None:
    """Sensibile all'ordine per scelta (spec #242): l'impronta identifica la
    lista MOSTRATA, che in UI e' numerata, non il solo insieme."""
    a, b = _poi(), _poi("node/2", "Bar")
    assert fingerprint([a, b]) != fingerprint([b, a])


def test_lista_vuota_ha_un_digest_stabile() -> None:
    """Zona senza POI: l'impronta esiste ed e' confrontabile (nessun caso speciale)."""
    assert fingerprint([]) == fingerprint([])
    assert fingerprint([]) != fingerprint([_poi()])


def test_campi_fuori_impronta_non_cambiano_il_digest() -> None:
    """``osm_tags`` e ``citta`` non entrano nel prompt del POI: fuori impronta,
    cosi' un ritag su OSM non invalida una narrativa ancora valida."""
    base = _poi()
    variante: Poi = {**base, "osm_tags": "amenity=bank;atm=yes", "citta": "ROMA"}
    assert fingerprint([base]) == fingerprint([variante])


# --- Il tipo dell'impronta nei body di richiesta (``contesto_hash``) ---
# Il bound del campo e' una proprieta' del digest prodotto QUI, non delle due
# rotte che lo ricevono: ``ZoneNarrativeRequest`` e ``PoiNarrativeRequest``
# dichiaravano ognuna il proprio ``Field(min_length=64, max_length=64)`` con la
# stessa motivazione ricopiata a mano, e un cambio di algoritmo avrebbe potuto
# correggerne uno lasciando l'altro a respingere impronte valide.

#: Le richieste che portano un ``contesto_hash``, con il resto del body minimo
#: valido: la coppia (modello, campi) serve a provare lo STESSO bound su entrambe.
_RICHIESTE_CON_IMPRONTA = [
    pytest.param(
        ZoneNarrativeRequest, {"citta": "Roma", "zona": "Colosseo"}, id="zona"
    ),
    pytest.param(
        PoiNarrativeRequest,
        {"citta": "Roma", "zona": "Colosseo", "poi_id": "node/1"},
        id="poi",
    ),
]


@pytest.mark.parametrize(("modello", "resto"), _RICHIESTE_CON_IMPRONTA)
def test_la_richiesta_accetta_esattamente_la_lunghezza_del_digest(
    modello: type[BaseModel], resto: dict[str, str]
) -> None:
    """Entrambe le rotte vincolano l'impronta alla lunghezza REALE del digest.

    Un carattere in meno o in piu' non ha la forma di un'impronta: cade in
    validazione (422 prima di ogni I/O) e non al confronto (409, che a cache
    fredda costa una ricostruzione del contesto). Il valido e' calcolato con
    :func:`fingerprint`, non scritto a mano: se il digest cambiasse lunghezza,
    il bound dei due modelli deve seguirlo.
    """
    valida = fingerprint([_poi()])

    modello.model_validate({**resto, "contesto_hash": valida})

    for storta in (valida[:-1], valida + "0"):
        with pytest.raises(ValidationError):
            modello.model_validate({**resto, "contesto_hash": storta})


def test_le_due_richieste_descrivono_l_impronta_allo_stesso_modo() -> None:
    """Un campo, una prosa: bound e descrizione vengono dall'alias condiviso di
    questo modulo, non ricopiati in due modelli. La descrizione finisce
    nell'OpenAPI, quindi due copie divergono anche verso il client."""
    zona = ZoneNarrativeRequest.model_fields["contesto_hash"]
    poi = PoiNarrativeRequest.model_fields["contesto_hash"]

    assert zona.description is not None
    assert zona.description == poi.description
    assert zona.metadata == poi.metadata
