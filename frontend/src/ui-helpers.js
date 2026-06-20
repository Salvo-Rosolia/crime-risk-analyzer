// src/ui-helpers.js — Pure helper functions for UI derivations.
// Separates testable pure logic from DOM-touching render code.
// Exported pure helpers (all side-effect free):
//   validateInputPanel, buildNarrativeSections, buildDetailModel, filterVisiblePOIs,
//   cityColorFor, buildScenarioCardData, groupRisksByTag, cacheChipHTML
// Exported constants: TAG_ORDER

// ── Canonical tag order (single source of truth — imported by ui.js too) ─────
/**
 * Canonical display order for risk source tags.
 * Imported by buildNarrativeSections, buildDetailModel, and ui.js render code.
 * @type {string[]}
 */
export const TAG_ORDER = ['ONTOLOGIA', 'CONTESTO', 'SPECULATIVO'];

// ── groupRisksByTag ─────────────────────────────────────────────────────────

/**
 * Groups risks from all risk_models by their tag key.
 * Shared by buildDetailModel and buildNarrativeSections to avoid duplication.
 *
 * @param {Array<{ poi: string, risks: Array<{ tag?: string, [key: string]: any }> }>|null|undefined} riskModels
 * @param {((risk: object) => any)|null} [valueFn] - optional transform applied to each risk before storing.
 *   When omitted, the raw risk object is stored.
 * @returns {Record<string, Array>} map of tag → array of risk objects (or valueFn results)
 */
export function groupRisksByTag(riskModels, valueFn = null) {
  const groups = {};
  for (const model of (riskModels ?? [])) {
    for (const risk of (model.risks ?? [])) {
      const tag = risk.tag || 'SPECULATIVO';
      if (!groups[tag]) groups[tag] = [];
      groups[tag].push(valueFn ? valueFn(risk) : risk);
    }
  }
  return groups;
}

// ── cacheChipHTML ────────────────────────────────────────────────────────────

/**
 * Returns the HTML string for the "dati da cache" chip/banner.
 * Shown in the header-right area (modalità completo) when state.data._fromCache is true.
 * In modalità BASE (ablation view) il chip NON viene mostrato by design — quella vista
 * è volutamente spartana e non espone metriche né indicatori di provenienza dei dati.
 * Pure function — no DOM access.
 *
 * @param {boolean|undefined|null} fromCache
 * @returns {string} HTML string, or '' when fromCache is falsy
 */
export function cacheChipHTML(fromCache) {
  if (!fromCache) return '';
  return `<span class="cache-chip" title="I dati provengono dalla cache demo offline — il backend non era raggiungibile.">` +
    `&#9632; dati da cache offline</span>`;
}

// ── City colour palette (spec §City color coding) ─────────────────────────────
// Exported so ui.js and tests share the single source of truth.
const CITY_COLOR_MAP = Object.freeze({
  Roma:   '#0e7b80',
  Milano: '#3a5a8c',
  Napoli: '#b8870a',
  Torino: '#8a5a2b',
});
const CITY_COLOR_FALLBACK = '#928d82';

/**
 * Returns the accent colour for a city name (spec §City color coding).
 * City-agnostic: falls back to neutral grey for unlisted cities.
 * @param {string} city
 * @returns {string} hex colour
 */
export function cityColorFor(city) {
  return CITY_COLOR_MAP[city] ?? CITY_COLOR_FALLBACK;
}

/**
 * Derives the display data for a scenario card.
 * Pure function — no DOM access. Used by renderScenariosPanel and tests.
 *
 * Normalises the backend ScenarioPreset shape:
 *   { id, city, zone, type, zona? }
 * into a stable display object:
 *   { id, city, zone, type, zona, color }
 *
 * `zona` fallback mirrors app.js startAnalysis (scenario path) so both paths
 * produce the same string when zona is absent from the backend response.
 *
 * @param {{ id: string, city: string, zone: string, type: string, zona?: string }|null|undefined} scenario
 * @returns {{ id: string|undefined, city: string, zone: string, type: string, zona: string, color: string }}
 */
export function buildScenarioCardData(scenario) {
  const { id, city = '', zone = '', type = '', zona } = scenario ?? {};
  return {
    id,
    city,
    zone,
    type,
    zona: zona || `${zone}, ${city}`,
    color: cityColorFor(city),
  };
}

/**
 * Validates the input panel fields before submitting an analysis.
 * Pure function: no DOM access, fully testable.
 *
 * @param {{ zona: string, domanda?: string }} fields
 *   `domanda` è accettata nella shape (i chiamanti passano l'intero oggetto) ma
 *   non è validata: è sempre opzionale. Si valida solo `zona`.
 * @returns {{ ok: boolean, error: string|null }}
 */
export function validateInputPanel({ zona } = {}) {
  if (!zona || !zona.trim()) {
    return { ok: false, error: 'Inserisci una zona o scegli uno scenario.' };
  }
  return { ok: true, error: null };
}

/**
 * Derives narrative sections from risk_models, grouping risks by tag.
 * No `narrative_sections` backend field needed (spec-frontend §Allineamenti tecnici #4).
 *
 * The spec calls for narrative structured by source tag — three thematic columns
 * (ONTOLOGIA / CONTESTO / SPECULATIVO) — each collecting hazards from that source.
 * Since the backend returns `narrativa` (a single prose block) and `risk_models`
 * (structured risks with tags), we build the sections client-side from the tags.
 *
 * @param {Array<{ poi: string, risks: Array<{ hazard: string, confidence: string, tag: string }> }>} riskModels
 * @returns {Array<{ tag: string, hazards: string[] }>}
 */
export function buildNarrativeSections(riskModels) {
  const groups = groupRisksByTag(riskModels, r => r.hazard);

  const sections = [];
  // Preserve canonical display order via TAG_ORDER
  for (const tag of TAG_ORDER) {
    if (groups[tag]?.length) {
      sections.push({ tag, hazards: groups[tag] });
    }
  }
  // Include any unexpected tags at the end
  for (const tag of Object.keys(groups)) {
    if (!TAG_ORDER.includes(tag)) sections.push({ tag, hazards: groups[tag] });
  }

  return sections;
}

/**
 * Builds the data model for the Detail card (Stato C) from a single POI and
 * the full risk_models array. Pure function — no DOM access.
 *
 * Returns:
 *   { poi, sparqlParts, groups }
 *
 *   - poi        — the input POI object as-is
 *   - sparqlParts — poi.sparql_path split on " → " (empty array when absent)
 *   - groups     — risks from the matching risk_model, keyed by tag
 *                  e.g. { ONTOLOGIA: [{hazard,confidence,tag}], CONTESTO: [...] }
 *
 * Spec-frontend §Stato C: path SPARQL lineare + fattori per fonte.
 *
 * @param {{ name: string, sparql_path?: string }} poi
 * @param {Array<{ poi: string, risks: Array<{ hazard: string, confidence: string, tag?: string }> }>} riskModels
 * @returns {{ poi: object, sparqlParts: string[], groups: Record<string, Array> }}
 */
export function buildDetailModel(poi, riskModels) {
  const sparqlParts = poi.sparql_path
    ? poi.sparql_path.split(' → ')
    : [];

  const model = (riskModels ?? []).find(r => r.poi === poi.name);
  // Re-use groupRisksByTag on the single matching model's risks (wrapped as one-element array)
  const groups = model ? groupRisksByTag([model]) : {};

  return { poi, sparqlParts, groups };
}

/**
 * Returns the subset of POIs visible under the given confidence filter.
 * When filter is null, all POIs are returned (no filtering).
 * Does not mutate the original array.
 *
 * Used by renderPOIPanel (count/eyebrow), renderMarkers (dim logic),
 * and the filter-bar "N nascosti" counter.
 *
 * Spec-frontend §Stato B·Filtro.
 *
 * @param {Array<{ id: string, confidence: string }>} pois
 * @param {string|null} filter - 'confermato'|'plausibile'|'speculativo'|null
 * @returns {Array<{ id: string, confidence: string }>}
 */
export function filterVisiblePOIs(pois, filter) {
  if (!filter) return pois.slice();
  return pois.filter(p => p.confidence === filter);
}
