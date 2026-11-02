import { Confidence, NarrativeSourceTag, Poi, SourceTag } from '@core/models/models';

export interface ConfMeta {
  color: string;
  bg: string;
  dot: string;
  label: string;
}

/**
 * Labels of the 2 confidence levels (#258): they state the real SIGNAL — merely the presence of
 * the `name` tag on OSM (#202) — not a broader verification process. The previous names
 * ("Verificato"/"Da confermare") hinted at a check the system does not perform; here they are
 * renamed for honesty (consistent with `MEANINGS` in `confidence-filter.component.ts`, already
 * phrased in these terms). The literal values of the `Confidence` type (`verificato`/
 * `da_confermare`, API/eval contract) stay unchanged: only the displayed text changes.
 */
export const CONF: Readonly<Record<Confidence, ConfMeta>> = Object.freeze({
  verificato: { color: '#1a7a40', bg: '#eef7f1', dot: '●', label: 'Identificato' },
  da_confermare: { color: '#b8870a', bg: '#fbf4e4', dot: '◐', label: 'Anonimo' },
});

export const DIM_COLOR = '#b6b3a9';

/**
 * Color of the SPECULATIVO source tag (per-source sections State B/C, badge, chip). It used to
 * be "borrowed" from `CONF.ipotesi` (confidence level removed, #220): the vocabulary of the
 * `SourceTag` (ONTOLOGIA/CONTESTO/SPECULATIVO) is an axis ORTHOGONAL to confidence (a
 * SPECULATIVO risk today still carries `confidence: 'da_confermare'`, never `null`) and must not
 * depend on its levels. Dedicated named constant: the palette of the source tags stays unchanged
 * even if the confidence levels change.
 */
export const SPECULATIVE_TAG_COLOR = '#c2620a';

/**
 * Color + short description for the section titles of the source tags (State C "Fattori di
 * rischio · per fonte", State B narrative structured by source): ONTOLOGIA/CONTESTO mirror the
 * color of the analogous confidence level, SPECULATIVO uses its own dedicated constant (see above).
 */
export const SRC_TAG_META: Readonly<Record<SourceTag, { color: string; description: string }>> =
  Object.freeze({
    ONTOLOGIA: { color: CONF.verificato.color, description: 'da ontologia formale' },
    CONTESTO: { color: CONF.da_confermare.color, description: 'da contesto ambientale' },
    SPECULATIVO: { color: SPECULATIVE_TAG_COLOR, description: 'inferenza non verificata' },
  });

/** Color of the ISTAT source (#345): a blue distinct from the palette of the confidence levels. */
export const ISTAT_TAG_COLOR = '#2f5d8a';

/**
 * Meta of the NARRATIVE sources (#345): those of the risks plus ISTAT. `SRC_TAG_META` stays
 * limited to the risk tags (State C), which cannot be ISTAT.
 */
export const NARRATIVE_TAG_META: Readonly<
  Record<NarrativeSourceTag, { color: string; description: string }>
> = Object.freeze({
  ...SRC_TAG_META,
  ISTAT: { color: ISTAT_TAG_COLOR, description: 'dati ISTAT del comune o della provincia' },
});

const UNKNOWN_TAG_META = { color: SPECULATIVE_TAG_COLOR, description: '' };

/**
 * Variant of `NARRATIVE_TAG_META` safe for generic tags (`string`, not restricted to
 * `NarrativeSourceTag`): used by the components (`DetailPanelComponent`, `NarrativeSheetComponent`)
 * that iterate the groups of `orderGroupsByTag` or the tabs of `buildSourceTabs`, where an
 * out-of-contract tag is allowed and must degrade to the same defensive fallback as `pinColor`
 * instead of throwing.
 */
export function srcTagMeta(tag: string): { color: string; description: string } {
  return (
    (NARRATIVE_TAG_META as Record<string, { color: string; description: string }>)[tag] ??
    UNKNOWN_TAG_META
  );
}

const UNKNOWN_CONF_META: ConfMeta = Object.freeze({
  color: DIM_COLOR,
  bg: DIM_COLOR,
  dot: '?',
  label: 'Sconosciuto',
});

/**
 * Variant of `CONF` safe for a confidence level potentially out of contract OR absent
 * (defense in depth, story #207/#220): an unrecognized value (typo, legacy data, vocabulary
 * migration mismatch) or `null`/`undefined` (POI outside the ontology, #220: no risk to
 * qualify) degrades to a placeholder — neutral pin — instead of making the template collapse
 * into a change detection TypeError (`CONF[level]` indexed directly would be `undefined`).
 * Same pattern as `srcTagMeta` for the source tags.
 */
export function confMeta(level: string | null | undefined): ConfMeta {
  return (
    (level != null ? (CONF as Record<string, ConfMeta>)[level] : undefined) ?? UNKNOWN_CONF_META
  );
}

export function pinColor(level: string | null | undefined): string {
  return confMeta(level).color;
}

export function deriveCoverage(poi: Poi[] | null | undefined): { total: number; anchored: number } {
  const list = poi ?? [];
  return {
    total: list.length,
    anchored: list.filter((p) => p.confidence != null).length,
  };
}

export function coverageBadgeText(total: number, anchored: number): string {
  return `Copertura ${anchored} su ${total} POI coperti da ontologia`;
}

/**
 * Count of POIs per their confidence level (`Poi.confidence` field, not the risks
 * of `confidence_summary`): source of both the filter chips of `PoiPanelComponent` and those in
 * `HeaderControlsComponent` — one place for the same counting rule (DRY). POIs outside the
 * ontology (`confidence: null`, #220) are not filterable as a category: they contribute to
 * neither of the 2 keys (no dedicated chip/row, consistent with the 2-valued `LEVELS`).
 */
export function poiConfidenceCounts(pois: Poi[] | null | undefined): Record<Confidence, number> {
  const counts: Record<Confidence, number> = { verificato: 0, da_confermare: 0 };
  for (const poi of pois ?? []) {
    if (poi.confidence) counts[poi.confidence]++;
  }
  return counts;
}

export function pinHTML(
  n: number,
  conf: string | null | undefined,
  { focus = false, dim = false }: { focus?: boolean; dim?: boolean } = {},
): string {
  const color = dim ? DIM_COLOR : pinColor(conf);
  const size = focus ? 34 : 26;
  const opacity = dim ? 0.45 : 1;
  const shadow = focus ? '0 3px 10px rgba(0,0,0,0.35)' : '0 1px 4px rgba(0,0,0,0.3)';
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
