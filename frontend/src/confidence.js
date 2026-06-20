// src/confidence.js — Confidence levels, colors, and derived display helpers

export const CONF = Object.freeze({
  confermato:  { color: '#1a7a40', bg: '#eef7f1', dot: '●', label: 'Confermato' },
  plausibile:  { color: '#b8870a', bg: '#fbf4e4', dot: '◐', label: 'Plausibile' },
  speculativo: { color: '#c2620a', bg: '#fbeee2', dot: '○', label: 'Speculativo' },
});

export const DIM_COLOR = '#b6b3a9';

/**
 * Returns pin/badge color for a confidence level.
 * Falls back to dim grey for unknown values.
 * @param {string} level
 * @returns {string} hex color
 */
export function pinColor(level) {
  return CONF[level]?.color ?? DIM_COLOR;
}

/**
 * Derives coverage totals from canonical backend fields — no backend `coverage` field needed.
 * Spec-frontend §4 / §Allineamenti tecnici #4.
 *
 * - total   = sum of confidence_summary values (number of POI-level confidence records)
 * - anchored = count of risks with tag === 'ONTOLOGIA' across all risk_models
 *
 * @param {{ confermato?: number, plausibile?: number, speculativo?: number }} confidenceSummary
 * @param {Array<{ poi: string, risks: Array<{ tag: string }> }>} riskModels
 * @returns {{ total: number, anchored: number }}
 */
export function deriveCoverage(confidenceSummary, riskModels) {
  // Somma SOLO le 3 chiavi canoniche del vocabolario chiuso — qualunque chiave
  // extra nel payload (es. un campo futuro del backend) non deve gonfiare il totale.
  const total = ['confermato', 'plausibile', 'speculativo']
    .reduce((acc, k) => acc + (Number(confidenceSummary?.[k]) || 0), 0);

  const anchored = (riskModels ?? []).reduce((acc, model) => {
    return acc + (model.risks ?? []).filter(r => r.tag === 'ONTOLOGIA').length;
  }, 0);

  return { total, anchored };
}

/**
 * Formats the qualitative coverage badge text.
 * Badge is qualitative (quanti rischi trovati / ancorati), NOT a pericolosità score.
 * Spec-frontend §Decisioni recepite #2.
 *
 * @param {number} total   - total risk records
 * @param {number} anchored - risks anchored to ontology (tag ONTOLOGIA)
 * @returns {string}
 */
export function coverageBadgeText(total, anchored) {
  return `Copertura ${total} rischi · ${anchored} ancorati a ontologia`;
}

/**
 * Builds the teardrop pin HTML string for a Leaflet divIcon.
 * Rotation -45° gives the teardrop shape; inner number rotated back +45°.
 * @param {number|string} n - pin number label
 * @param {string} conf - confidence level key
 * @param {{ focus?: boolean, dim?: boolean }} opts
 * @returns {string} HTML string (safe to use as divIcon html)
 */
export function pinHTML(n, conf, { focus = false, dim = false } = {}) {
  const color   = dim ? DIM_COLOR : pinColor(conf);
  const size    = focus ? 34 : 26;
  const opacity = dim ? 0.45 : 1;
  const shadow  = focus
    ? '0 3px 10px rgba(0,0,0,0.35)'
    : '0 1px 4px rgba(0,0,0,0.3)';
  const fontSize = focus ? 14 : 11;

  return (
    `<div style="opacity:${opacity};width:${size}px;height:${size}px;` +
    `border-radius:50% 50% 50% 0;transform:rotate(-45deg);background:${color};` +
    `border:2px solid rgba(0,0,0,0.22);box-shadow:${shadow};` +
    `display:flex;align-items:center;justify-content:center;">` +
    `<span style="transform:rotate(45deg);color:#fff;` +
    `font-family:'IBM Plex Sans',sans-serif;font-weight:700;font-size:${fontSize}px;">${n}</span>` +
    `</div>`
  );
}
