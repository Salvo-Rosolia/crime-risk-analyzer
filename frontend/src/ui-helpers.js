// src/ui-helpers.js — Pure helper functions for UI derivations.
// Separates testable pure logic from DOM-touching render code.

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
  /** @type {Map<string, string[]>} */
  const byTag = new Map();

  for (const model of (riskModels ?? [])) {
    for (const risk of (model.risks ?? [])) {
      const tag = risk.tag || 'SPECULATIVO';
      if (!byTag.has(tag)) byTag.set(tag, []);
      byTag.get(tag).push(risk.hazard);
    }
  }

  // Preserve canonical display order: ONTOLOGIA → CONTESTO → SPECULATIVO
  const ORDER = ['ONTOLOGIA', 'CONTESTO', 'SPECULATIVO'];
  const sections = [];
  for (const tag of ORDER) {
    if (byTag.has(tag)) {
      sections.push({ tag, hazards: byTag.get(tag) });
    }
  }
  // Include any unexpected tags at the end
  for (const [tag, hazards] of byTag) {
    if (!ORDER.includes(tag)) sections.push({ tag, hazards });
  }

  return sections;
}
