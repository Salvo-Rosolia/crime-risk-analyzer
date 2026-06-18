// src/map.js — Leaflet map management (imperative, singleton)
import { pinHTML } from './confidence.js';

const DEFAULT_CENTER = [41.9028, 12.4964]; // Roma
const DEFAULT_ZOOM   = 12;

/** @type {L.Map|null} */
let _map = null;
/** @type {L.LayerGroup|null} */
let _layer = null;
/** @type {((id: string) => void)|null} */
let _onPoiClick = null;

/**
 * Initialise the Leaflet map. Safe to call multiple times — only inits once.
 * @param {string} containerId
 * @param {(id: string) => void} onPoiClick
 */
export function initMap(containerId, onPoiClick) {
  if (_map) return;
  _onPoiClick = onPoiClick;

  // L is a CDN global — available at runtime, not in tests
  _map = L.map(containerId, { zoomControl: false, attributionControl: true })
    .setView(DEFAULT_CENTER, DEFAULT_ZOOM);

  L.tileLayer(
    'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
    {
      subdomains:  'abcd',
      maxZoom:     19,
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> © <a href="https://carto.com/">CARTO</a>',
    }
  ).addTo(_map);

  L.control.zoom({ position: 'bottomright' }).addTo(_map);
  _layer = L.layerGroup().addTo(_map);

  // Ensure map fills its container after initial paint
  setTimeout(() => _map.invalidateSize(), 200);
}

/**
 * Clear all POI markers and re-render from current state data.
 * Cleans up old layer before adding new markers (no stale layers).
 * @param {Array<{id:string, name:string, lat:number, lon:number, confidence:string}>} pois
 * @param {string|null} filter - active confidence filter or null
 * @param {string|null} selectedId - currently selected POI id or null
 */
export function renderMarkers(pois, filter, selectedId) {
  if (!_layer) return;
  _layer.clearLayers();

  pois.forEach(poi => {
    const dim   = Boolean(filter && poi.confidence !== filter) ||
                  Boolean(selectedId !== null && selectedId !== poi.id);
    const focus = selectedId === poi.id;

    const size = focus ? 34 : 26;
    const icon = L.divIcon({
      html:       pinHTML(poi.id, poi.confidence, { focus, dim }),
      className:  '', // no default Leaflet class (keeps our custom styles clean)
      iconSize:   [size, size],
      iconAnchor: [size / 2, size],
    });

    const marker = L.marker([poi.lat, poi.lon], {
      icon,
      zIndexOffset: focus ? 1000 : (dim ? 0 : 200),
      title:        poi.name,
      alt:          `POI ${poi.id}: ${poi.name}`,
    });

    marker.on('click', () => {
      if (_onPoiClick) _onPoiClick(poi.id);
    });

    _layer.addLayer(marker);
  });
}

/** Remove all markers without rebuilding. */
export function clearMarkers() {
  if (_layer) _layer.clearLayers();
}

/**
 * Fly map to a single POI coordinate.
 * @param {number} lat
 * @param {number} lon
 * @param {number} [zoom=17]
 */
export function flyToPoi(lat, lon, zoom = 17) {
  if (!_map) return;
  _map.flyTo([lat, lon], zoom, { duration: 0.6 });
}

/**
 * Fly to fit all POIs in the viewport.
 * paddingTopLeft accounts for the left panel (~308px); paddingBottomRight for narrative (~300px).
 * @param {Array<{lat:number, lon:number}>} pois
 * @param {number} [maxZoom=17]
 */
export function flyToBounds(pois, maxZoom = 17) {
  if (!_map || pois.length === 0) return;
  const bounds = L.latLngBounds(pois.map(p => [p.lat, p.lon]));
  _map.flyToBounds(bounds, {
    paddingTopLeft:     [345, 30],
    paddingBottomRight: [40, 300],
    maxZoom,
    duration: 0.8,
  });
}

/** Reset map to default Roma overview. */
export function resetView() {
  if (!_map) return;
  _map.flyTo(DEFAULT_CENTER, DEFAULT_ZOOM, { duration: 0.6 });
}

/** Force a map resize — call after any panel show/hide/transition. */
export function invalidateSize() {
  if (_map) setTimeout(() => _map.invalidateSize(), 60);
}
