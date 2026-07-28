"""Client Overpass API -> POI on-demand (#16).

Interroga Overpass nel bounding box di una citta' per una lista di chiavi OSM e
restituisce i POI nel contratto di RETRIEVAL: ogni POI espone ``id``, ``name``,
``lat``, ``lon``, ``osm_tags``, ``terminus_class`` e ``citta``. I campi
``confidence`` e ``sparql_path`` NON sono aggiunti qui: li produce il layer
grounding/SPARQL a valle.

Vincoli (orchestrator.md): massimo :data:`MAX_POIS` POI per richiesta; in caso di
timeout **o** di status ritentabile (429/5xx) si ritenta secondo la
:class:`RetryPolicy` ricevuta, poi :class:`OverpassError` (mappata a 503
dall'orchestrator). Le chiamate sono async (``httpx.AsyncClient``): nessun
I/O bloccante.

Due politiche, perche' i due contesti hanno costi opposti (#232):
:data:`INTERACTIVE_RETRY` per ``/analyze``, dove un utente sta aspettando e
fallire presto e' corretto; :data:`OFFLINE_RETRY` per la cattura degli snapshot
di valutazione, dove attendere e' gratis e fallire significa non avere
esperimento. Una sola implementazione, parametrizzata.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TypedDict, cast

import httpx

from crime_risk_analyzer.models.geo import Bbox, haversine_m
from crime_risk_analyzer.sparql_module.osm_mapping import (
    ORDINE_FAMIGLIE,
    OSM_SELECTORS,
    OSM_TO_TERMINUS,
    map_to_terminus,
)

__all__ = [
    "INTERACTIVE_RETRY",
    "MAX_POIS",
    "OFFLINE_RETRY",
    "PER_CLASS_CAP",
    "PER_SELECTOR_CAP",
    "Bbox",
    "OverpassError",
    "Poi",
    "RetryPolicy",
    "fetch_pois",
    "select_pois",
]

#: Endpoint Overpass di default (override possibile via parametro).
DEFAULT_OVERPASS_URL = "https://overpass-api.de/api/interpreter"

#: Numero massimo di POI restituiti per richiesta (orchestrator.md / retrieval.md).
#: #212: ridotto da 50 a 20 per risultati meno affollati e piu' leggibili.
MAX_POIS = 20

#: Cap di elementi restituiti da Overpass PER selettore: dimensiona il BACINO di
#: CANDIDATI, non il risultato. La scelta dei ``MAX_POIS`` che escono e' di
#: :func:`select_pois` (#254).
#: #212 l'aveva ridotto a 3 quando il taglio era «i primi che arrivano»; con la
#: selezione per prossimita' un bacino cosi' stretto renderebbe l'ordinamento poco
#: significativo (si ordinerebbero 3 elementi per selettore scelti da Overpass).
#: LIMITE DICHIARATO: ``out center N`` restituisce N elementi QUALSIASI, non i piu'
#: vicini, quindi alzare il tetto riduce l'arbitrarieta' del bacino ma non la
#: elimina. Resta uguale sui due percorsi (interattivo e cattura offline): un tetto
#: diverso farebbe selezionare produzione e snapshot da bacini diversi, rompendo
#: l'iso-input di #110.
PER_SELECTOR_CAP = 10

#: Quanti posti al massimo puo' prendere una singola classe TERMINUS dentro i
#: ``MAX_POIS`` (#254). I posti eventualmente rimasti si riempiono comunque coi piu'
#: vicini fra gli scartati, quindi il tetto non riduce mai il numero di POI
#: restituiti: cambia solo la loro composizione.
PER_CLASS_CAP = 3

logger = logging.getLogger(__name__)

#: Status HTTP ritentabili: 429 (rate limit) e 5xx di gateway/overload. Una
#: risposta con questi status non e' un errore definitivo ma una condizione
#: transitoria di Overpass -> merita un ritentativo come un timeout.
_RETRYABLE_STATUS = frozenset({429, 502, 503, 504})


@dataclass(frozen=True)
class RetryPolicy:
    """Quanto insistere con Overpass, e quanto aspettare fra i tentativi (#232).

    ``pause_s`` ha un elemento per ogni RITENTATIVO, nell'ordine: la sua
    lunghezza *e'* il numero di ritentativi, e i valori crescenti realizzano il
    backoff. Tenerli espliciti invece di calcolarli (base * fattore ** n) rende
    la politica leggibile in un test e nel report di una run.
    """

    #: Pause di cortesia prima di ciascun ritentativo, in secondi.
    pause_s: tuple[float, ...]
    #: Timeout del primo tentativo.
    timeout_s: float
    #: Timeout dei ritentativi (piu' lungo: un 504 sotto carico ha bisogno d'aria).
    retry_timeout_s: float
    #: Quanta attesa richiesta da ``Retry-After`` questa politica e' disposta ad
    #: accettare. ``None`` = header IGNORATO: e' il caso interattivo, dove
    #: allungare l'attesa perche' il server lo chiede peggiorerebbe proprio la
    #: latenza che si vuole tenere bassa. Un valore = tetto: oltre quello si
    #: rinuncia subito invece di ritentare presto, che sarebbe hammering verso un
    #: servizio pubblico gratuito che ha appena detto «piu' tardi».
    retry_after_cap_s: float | None


#: Percorso interattivo (``/analyze``): un utente sta aspettando, quindi fallire
#: presto e' corretto. E' il comportamento pre-#232 alla lettera — un ritentativo,
#: un secondo di pausa, ``Retry-After`` ignorato — perche' quel percorso non deve
#: guadagnare latenza. Vale anche per ``capture_city`` (#31), dove il tempo di
#: parete e' la metrica ``switch_ms`` e una pausa piu' lunga la falsificherebbe.
INTERACTIVE_RETRY = RetryPolicy(
    pause_s=(1.0,),
    timeout_s=30.0,
    retry_timeout_s=60.0,
    retry_after_cap_s=None,
)

#: Cattura offline degli snapshot di valutazione: qui attendere e' gratis e
#: fallire significa non avere esperimento (#232). Le pause sono di cortesia
#: verso un servizio pubblico gratuito — un 429 e' quota di slot esaurita e si
#: libera in decine di secondi — e sommano 155s; col timeout di ogni tentativo il
#: caso peggiore per una zona sfiora i 7 minuti.
OFFLINE_RETRY = RetryPolicy(
    pause_s=(5.0, 15.0, 45.0, 90.0),
    timeout_s=30.0,
    retry_timeout_s=60.0,
    retry_after_cap_s=120.0,
)

#: User-agent esplicito richiesto dall'endpoint pubblico Overpass: senza di esso
#: (default httpx ``python-httpx/...``) overpass-api.de risponde 406.
_USER_AGENT = (
    "crime-risk-analyzer (https://github.com/Salvo-Rosolia/crime-risk-analyzer)"
)


class Poi(TypedDict):
    """POI nel contratto di retrieval (pre-grounding)."""

    id: str
    name: str
    lat: float
    lon: float
    osm_tags: str
    terminus_class: str
    citta: str


class OverpassError(RuntimeError):
    """Overpass non raggiungibile o risposta non valida (mappabile a 503)."""


def _build_query(bbox: Bbox, osm_selectors: Sequence[str]) -> str:
    """Costruisce la query Overpass QL per i selettori ``key=value`` dentro ``bbox``.

    Ogni selettore ``k=v`` emette un blocco unione node+way seguito da un
    ``out center PER_SELECTOR_CAP`` locale: cosi' nessun selettore denso satura il
    risultato. Bbox nell'ordine ``(south, west, north, east)``.
    """
    lat_min, lon_min, lat_max, lon_max = bbox
    bbox_str = f"{lat_min},{lon_min},{lat_max},{lon_max}"
    blocks: list[str] = []
    for selector in osm_selectors:
        key, _, value = selector.partition("=")
        blocks.append(
            f'(\n  node["{key}"="{value}"]({bbox_str});\n'
            f'  way["{key}"="{value}"]({bbox_str});\n);\n'
            f"out center {PER_SELECTOR_CAP};"
        )
    return "[out:json][timeout:25];\n" + "\n".join(blocks)


def _extract_osm_tag(tags: Mapping[str, object]) -> str:
    """Estrae il selettore rappresentativo ``chiave=valore`` da ``tags`` OSM.

    Itera le famiglie in :data:`ORDINE_FAMIGLIE` (priorita') e ritorna il PRIMO
    ``key=value`` che esiste nel binding :data:`OSM_TO_TERMINUS`. Cosi' un POI
    multi-tag e' classificato dal tag effettivamente mappato e non da un tag spurio
    a priorita' piu' alta. Ritorna stringa vuota se nessun tag noto e' presente.
    """
    for family in ORDINE_FAMIGLIE:
        value = tags.get(family)
        if isinstance(value, str):
            selector = f"{family}={value}"
            if selector in OSM_TO_TERMINUS:
                return selector
    return ""


def _coords(element: Mapping[str, object]) -> tuple[float, float] | None:
    """Estrae ``(lat, lon)`` da un elemento, o ``None`` se non utilizzabili.

    I ``node`` hanno ``lat``/``lon`` diretti; i ``way`` espongono il centroide
    in ``center``.
    """
    lat = element.get("lat")
    lon = element.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        center = element.get("center")
        if not isinstance(center, Mapping):
            return None
        center_map = cast(Mapping[str, object], center)
        lat = center_map.get("lat")
        lon = center_map.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    return float(lat), float(lon)


def _to_poi(element: Mapping[str, object], citta: str) -> Poi | None:
    """Converte un elemento Overpass in :class:`Poi`, o ``None`` se inutilizzabile.

    Scarta gli elementi senza tag o senza coordinate.
    """
    tags = element.get("tags")
    if not isinstance(tags, Mapping):
        return None
    tags_map = cast(Mapping[str, object], tags)

    coords = _coords(element)
    if coords is None:
        return None
    lat, lon = coords

    osm_tag = _extract_osm_tag(tags_map)
    return Poi(
        id=str(element.get("id", "")),
        name=str(tags_map.get("name", "")),
        lat=lat,
        lon=lon,
        osm_tags=osm_tag,
        terminus_class=map_to_terminus(osm_tag),
        citta=citta,
    )


def _parse_elements(payload: object, citta: str) -> list[Poi]:
    """Mappa TUTTI gli ``elements`` di una risposta Overpass in POI.

    Nessun taglio qui (#254): questa funzione produce il bacino di candidati, e
    quali ``MAX_POIS`` escono lo decide :func:`select_pois`. Prima il taglio era
    un ``break`` a ``MAX_POIS`` sull'ordine di emissione, cioe' sull'ordine di
    dichiarazione dei selettori.
    """
    if not isinstance(payload, Mapping):
        raise OverpassError("Risposta Overpass non valida: payload non oggetto")
    payload_map = cast(Mapping[str, object], payload)
    elements = payload_map.get("elements")
    if not isinstance(elements, list):
        raise OverpassError("Risposta Overpass priva di 'elements'")
    elements_list = cast(list[object], elements)

    pois: list[Poi] = []
    visti: set[tuple[str, str]] = set()
    for element in elements_list:
        if not isinstance(element, Mapping):
            continue
        element_map = cast(Mapping[str, object], element)
        # Identita' OSM = (type, id): la query ha un blocco per selettore e ogni
        # ``out`` stampa il proprio set, quindi un oggetto con piu' tag mappati
        # arriva una volta per blocco (verificato dal vivo: l'Arco di Costantino,
        # ``tourism=attraction`` + ``historic=monument``, arriva due volte). Il
        # ``type`` entra nella chiave perche' node e way vivono in namespace
        # separati e lo stesso numero identifica due oggetti diversi (#265).
        chiave = (str(element_map.get("type", "")), str(element_map.get("id", "")))
        if chiave in visti:
            continue
        poi = _to_poi(element_map, citta)
        if poi is not None:
            visti.add(chiave)
            pois.append(poi)
    return pois


def select_pois(
    pois: list[Poi],
    center: tuple[float, float],
    *,
    max_pois: int = MAX_POIS,
    per_class_cap: int = PER_CLASS_CAP,
) -> list[Poi]:
    """I ``max_pois`` POI da restituire, scelti per prossimita' a ``center`` (#254).

    Prima di #254 il taglio prendeva i primi ``MAX_POIS`` nell'ordine in cui
    Overpass li emetteva, cioe' nell'ordine di dichiarazione dei selettori: in una
    zona densa i primi selettori esaurivano i posti e le famiglie di tag in coda
    non comparivano mai. Sui 4 snapshot catturati prima di questa modifica si vede
    l'effetto: solo POI ``amenity=*``, nessun museo, monumento o stazione.

    Ordinamento dichiarato: distanza crescente e, a parita' di distanza, ``id``
    crescente come STRINGA. Serve perche' il contesto entra nel prompt e
    ``repro.prompt_hash`` deve restare stabile a parita' di input. Non e' un
    ordinamento totale in senso stretto: due oggetti OSM alle stesse coordinate e
    con lo stesso id numerico pareggerebbero su entrambe le componenti e il
    pareggio ricadrebbe sulla stabilita' di ``sorted``, cioe' sull'ordine di
    emissione di Overpass. Oggi il caso non e' raggiungibile — ``_parse_elements``
    deduplica per ``(type, id)`` — ma lo diventerebbe se l'``id`` del POI restasse
    senza il tipo di elemento (#265).

    Due giri sulla stessa lista ordinata. Nel primo entra un POI solo se la sua
    classe TERMINUS non ha gia' ``per_class_cap`` posti: senza questo tetto, in
    centro citta' i POI piu' vicini sono spesso tutti della stessa classe (otto
    bancomat entro 150 m) e la zona verrebbe descritta su un campione omogeneo.
    Il secondo giro riempie i posti eventualmente rimasti con gli scartati piu'
    vicini: senza di esso una zona di sole banche restituirebbe ``per_class_cap``
    punti invece di ``max_pois``, cioe' meno di prima.
    """
    lat, lon = center
    ordinati = sorted(
        pois,
        key=lambda poi: (haversine_m(lat, lon, poi["lat"], poi["lon"]), poi["id"]),
    )
    scelti: list[Poi] = []
    scartati: list[Poi] = []
    per_classe: dict[str, int] = {}
    for poi in ordinati:
        if len(scelti) >= max_pois:
            break
        classe = poi["terminus_class"]
        if per_classe.get(classe, 0) >= per_class_cap:
            scartati.append(poi)
            continue
        per_classe[classe] = per_classe.get(classe, 0) + 1
        scelti.append(poi)
    if len(scelti) < max_pois:
        scelti.extend(scartati[: max_pois - len(scelti)])
        # Gli scartati sono piu' lontani dei scelti nel primo giro, ma non
        # necessariamente in coda: si riordina per tenere l'invariante «la lista
        # esce in ordine di distanza» (la numerazione in mappa la rispecchia).
        scelti.sort(
            key=lambda poi: (haversine_m(lat, lon, poi["lat"], poi["lon"]), poi["id"])
        )
    return scelti


async def _try_post(
    client: httpx.AsyncClient, url: str, query: str, timeout: float
) -> httpx.Response | None:
    """Esegue un tentativo di POST a Overpass col timeout indicato.

    Ritorna la :class:`httpx.Response` (qualunque status), oppure ``None`` se il
    tentativo scade in timeout (segnale ritentabile). Un errore di trasporto
    non-timeout (``httpx.HTTPError``, es. connessione rifiutata) e' definitivo:
    viene rilanciato subito come :class:`OverpassError`.
    """
    try:
        return await client.post(url, content=query, timeout=timeout)
    except httpx.TimeoutException:
        return None
    except httpx.HTTPError as exc:
        raise OverpassError(f"Errore di rete verso Overpass: {exc}") from exc


def _retry_after_s(response: httpx.Response | None) -> float | None:
    """I secondi indicati da ``Retry-After``, se leggibili come intero (#232).

    Solo la forma a secondi: la forma HTTP-date esiste nello standard ma Overpass
    non la usa, e interpretarla richiederebbe un parsing di date per nulla.
    ``None`` = header assente o illeggibile -> vale la pausa prevista.
    """
    if response is None:
        return None
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return max(float(int(raw.strip())), 0.0)
    except ValueError:
        return None


def _attesa_prima_del_ritentativo(
    response: httpx.Response | None, prevista: float, cap: float | None
) -> float:
    """Quanto attendere prima del prossimo tentativo, o rinuncia.

    Mai meno della pausa prevista dalla politica: verso un servizio pubblico
    gratuito la cortesia e' un minimo, non un massimo — quindi un ``Retry-After``
    piu' breve non la accorcia. Il tetto NON tocca la pausa prevista (che la
    politica ha dichiarato di proposito) ma solo la richiesta del server.

    Solleva :class:`OverpassError` se il server chiede piu' del tetto: ritentare
    prima sarebbe hammering verso chi ha appena detto «piu' tardi», e brucerebbe
    i ritentativi restanti in tentativi con probabilita' nulla. Meglio fermarsi
    dicendo quando ritentare.
    """
    if cap is None:
        return prevista
    richiesta = _retry_after_s(response)
    if richiesta is None:
        return prevista
    if richiesta > cap:
        raise OverpassError(
            f"Overpass ha chiesto di ritentare fra {richiesta:.0f}s, oltre il "
            f"tetto di {cap:.0f}s di questa politica: riprova piu' tardi"
        )
    return max(prevista, richiesta)


async def fetch_pois(
    bbox: Bbox,
    citta: str,
    osm_selectors: Iterable[str] = OSM_SELECTORS,
    *,
    overpass_url: str = DEFAULT_OVERPASS_URL,
    retry: RetryPolicy | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[Poi]:
    """Recupera i POI dentro ``bbox`` per i selettori OSM ``osm_selectors``.

    Default: l'intero binding canonico :data:`OSM_SELECTORS`. Arricchisce ogni POI
    con ``terminus_class`` (#13). Ritenta se un tentativo scade in timeout **o**
    risponde con uno status ritentabile (:data:`_RETRYABLE_STATUS`, 429/5xx),
    secondo ``retry``; esaurita la politica, :class:`OverpassError`.

    ``retry`` risolto a :data:`INTERACTIVE_RETRY` quando ``None``: la risoluzione
    avviene alla CHIAMATA e non come default di firma, cosi' un test puo'
    sostituire la politica di default senza riscrivere ogni chiamante. La cattura
    offline passa :data:`OFFLINE_RETRY` (#232). ``sleep`` e' iniettabile: i test
    verificano le pause senza attenderle.
    """
    policy = retry or INTERACTIVE_RETRY
    selectors = list(osm_selectors)
    query = _build_query(bbox, selectors)

    async with httpx.AsyncClient(headers={"User-Agent": _USER_AGENT}) as client:
        response = await _try_post(client, overpass_url, query, policy.timeout_s)
        # Un ritentativo per ogni pausa dichiarata: scatta sia sul timeout
        # (response None) sia su uno status transitorio (429/5xx). Uno status
        # non-2xx NON ritentabile (400/403/404) esce subito dal ciclo e fallisce
        # piu' sotto, senza attendere.
        for tentativo, prevista in enumerate(policy.pause_s, start=1):
            if response is not None and response.status_code not in _RETRYABLE_STATUS:
                break
            attesa = _attesa_prima_del_ritentativo(
                response, prevista, policy.retry_after_cap_s
            )
            # Log a ogni ritentativo (#232): con la politica offline l'attesa
            # complessiva arriva a minuti, e senza traccia «processo appeso» e
            # «backoff di cortesia in corso» sono indistinguibili — la condizione
            # che il 26/07 ha spinto a scrivere il backoff a mano in una shell.
            esito = (
                "timeout" if response is None else f"ha risposto {response.status_code}"
            )
            logger.warning(
                "Overpass %s: ritentativo %d/%d fra %.0fs",
                esito,
                tentativo,
                len(policy.pause_s),
                attesa,
            )
            await sleep(attesa)
            response = await _try_post(
                client, overpass_url, query, policy.retry_timeout_s
            )

    if response is None:
        raise OverpassError("Overpass timeout dopo i ritentativi con timeout esteso")
    if not response.is_success:
        raise OverpassError(f"Overpass ha risposto {response.status_code}")

    try:
        payload: object = response.json()
    except ValueError as exc:
        raise OverpassError("Risposta Overpass non e' JSON valido") from exc

    # Il bacino di candidati arriva completo; la scelta dei MAX_POIS che escono e'
    # per prossimita' al centro dell'area interrogata, con tetto per classe (#254).
    return select_pois(_parse_elements(payload, citta), bbox.center())
