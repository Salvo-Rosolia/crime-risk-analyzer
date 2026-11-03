import { confMeta } from '@core/confidence';
import {
  Confidence,
  IstatLink,
  IstatMatchKind,
  IstatPoi,
  IstatRow,
  NarrativeSourceTag,
  OntologyItem,
  Poi,
  RiskItem,
  RiskModel,
  SourceProse,
  SourceTag,
} from '@core/models/models';

/**
 * Canonical order of the source tags (spec-frontend.md, cross-cutting: State C risk factors by
 * source). Shared by `orderGroupsByTag`; the narrative tabs use `NARRATIVE_TAG_ORDER`
 * (includes ISTAT, which a risk can never have).
 */
const SOURCE_TAG_ORDER: readonly SourceTag[] = ['ONTOLOGIA', 'CONTESTO', 'SPECULATIVO'];

/**
 * Order of the narrative tabs (#345): the blocks in the order in which the model writes them
 * (ONTOLOGIA, CONTESTO, ISTAT), then SPECULATIVO. Separate from `SOURCE_TAG_ORDER`, which orders
 * the risk groups and cannot contain ISTAT.
 */
const NARRATIVE_TAG_ORDER: readonly NarrativeSourceTag[] = [
  'ONTOLOGIA',
  'CONTESTO',
  'ISTAT',
  'SPECULATIVO',
];

const CITY_COLOR_MAP: Readonly<Record<string, string>> = Object.freeze({
  Roma: '#0e7b80',
  Milano: '#3a5a8c',
  Napoli: '#b8870a',
  Torino: '#8a5a2b',
});
const CITY_COLOR_FALLBACK = '#928d82';

export function cityColorFor(city: string): string {
  return CITY_COLOR_MAP[city] ?? CITY_COLOR_FALLBACK;
}

export interface InputPanelValidation {
  ok: boolean;
  error: string | null;
  /** Field the error is attributed to (to highlight only the relevant border in the UI). */
  field: 'city' | 'zone' | null;
}

/**
 * Client validation of the city/zone pair (restored from before #318): used by the
 * "Analisi zona" and "Sistema base" panels when the area is not already a drawn circle — a submit
 * with a circle present does not even invoke it, because a circle is by construction already a
 * valid area.
 */
export function validateInputPanel({
  city,
  zone,
}: {
  city?: string;
  zone?: string;
} = {}): InputPanelValidation {
  if (!city || !city.trim()) {
    return { ok: false, error: 'Inserisci una città.', field: 'city' };
  }
  if (!zone || !zone.trim()) {
    return { ok: false, error: 'Inserisci una zona.', field: 'zone' };
  }
  return { ok: true, error: null, field: null };
}

/** Controlled IT label of the hazard (#77) with fallback to the raw class identifier. */
export function hazardDisplayLabel(risk: Pick<RiskItem, 'hazard' | 'hazard_label_it'>): string {
  return risk.hazard_label_it || risk.hazard;
}

/** Controlled IT label of an ontology entity (#256) with fallback to the raw identifier.
 * Same pattern as `hazardDisplayLabel`/`poiDisplayLabel`: the rule lives here and not in the
 * template, so the fallback branch can be exercised by a test. */
export function ontologyDisplayLabel(item: Pick<OntologyItem, 'name' | 'label_it'>): string {
  return item.label_it || item.name;
}

/** Controlled IT label of the POI class (#77) with fallback to the raw class identifier. */
export function poiDisplayLabel(poi: Pick<Poi, 'ontology_class' | 'ontology_label_it'>): string {
  return poi.ontology_label_it || poi.ontology_class;
}

/**
 * Fallback label for a POI without `name` (#261): OSM names are not always present (anonymous
 * features arrive with an empty `name`, same reason why the POI is `da_confermare`, #220). The
 * fallback is built on the class (`poiDisplayLabel`) and explicitly declares the absence,
 * instead of leaving a blank row in list/popup/detail. `trim()` before the check: a name made of
 * spaces only is real OSM data, it is truthy in JS, and without trim it would reproduce the same
 * empty row — `confidence_from_poi_name` (backend, rag/grounding.py) already does the same trim,
 * so here it aligns the UI with a POI that the backend marks da_confermare.
 */
export function poiNameDisplayLabel(
  poi: Pick<Poi, 'name' | 'ontology_class' | 'ontology_label_it'>,
): string {
  const name = poi.name?.trim();
  return name || `${poiDisplayLabel(poi)} (senza nome su OSM)`;
}

export interface DetailModel {
  poi: Poi;
  /** Preferred IT label of the POI (fallback to ontology_class if missing). */
  poiLabel: string;
  sparqlParts: string[];
  groups: Record<string, RiskItem[]>;
}

export function buildDetailModel(
  poi: Poi,
  riskModels: RiskModel[] | null | undefined,
): DetailModel {
  const sparqlParts = poi.sparql_path ? poi.sparql_path.split(' → ') : [];
  // Join by `poi_id`, not by name: OSM names are neither unique nor always present,
  // so a `find` by name shows on a point's detail the risks of another one.
  const model = (riskModels ?? []).find((r) => r.poi_id === poi.id);
  const groups: Record<string, RiskItem[]> = {};
  for (const risk of model?.risks ?? []) {
    const tag = risk.tag || 'SPECULATIVO';
    const list = groups[tag] ?? [];
    list.push(risk);
    groups[tag] = list;
  }
  return { poi, poiLabel: poiDisplayLabel(poi), sparqlParts, groups };
}

export interface TagGroup {
  tag: string;
  risks: RiskItem[];
}

/**
 * Orders the `groups` of `buildDetailModel` (unordered Record) in the canonical order
 * ONTOLOGIA → CONTESTO → SPECULATIVO required by State C (spec-frontend.md); any
 * out-of-contract tags stay at the end. Missing tags
 * or tags with an empty list are omitted.
 */
export function orderGroupsByTag(groups: Record<string, RiskItem[]>): TagGroup[] {
  const ordered: TagGroup[] = [];
  for (const tag of SOURCE_TAG_ORDER) {
    const risks = groups[tag];
    if (risks?.length) ordered.push({ tag, risks });
  }
  for (const tag of Object.keys(groups)) {
    if (!SOURCE_TAG_ORDER.includes(tag as SourceTag) && groups[tag]?.length)
      ordered.push({ tag, risks: groups[tag] });
  }
  return ordered;
}

/**
 * Minimum threshold of crimes in the place in the last year for an ISTAT item to count as data
 * (#346, O8, after /code-review): same `SOGLIA_TENDENZA` threshold as
 * `backend/src/crime_risk_analyzer/istat/rows.py`, below which the backend does not even compute
 * the trend. Without this threshold 1-19 crimes in the whole municipality (e.g. a single bank
 * robbery in Como, weight 12) would put that risk at the top of the order.
 */
export const ISTAT_MIN_DELITTI = 20;

/** ISTAT row attached to a risk, with the link that binds it and the weight (#346/#347). */
interface IstatMatch {
  row: IstatRow;
  link: IstatLink;
  weight: number;
}

/**
 * The single risk → ISTAT item matching logic (#346/#347): used both by the order weight
 * (`istatWeight`) and by the indicator (`withIstatIndicators`), so order and indicator cannot
 * diverge. `null` = no data: risk without an item, item with fewer than `ISTAT_MIN_DELITTI`
 * crimes in the place (or missing count, O8), or rate/national rate missing or national
 * rate 0. The "less than 0.1" published by ISTAT weighs 0 (not `null`): the datum exists.
 */
function istatMatch(hazard: string, istat: IstatPoi | null | undefined): IstatMatch | null {
  for (const row of istat?.righe ?? []) {
    const link = row.collegamenti.find((c) => c.hazard === hazard);
    if (!link) continue;
    if (row.delitti == null || row.delitti < ISTAT_MIN_DELITTI) return null;
    if (row.tasso_sotto_soglia) return { row, link, weight: 0 };
    if (row.tasso == null || row.tasso_italia == null || row.tasso_italia === 0) return null;
    return { row, link, weight: row.tasso / row.tasso_italia };
  }
  return null;
}

/**
 * ISTAT weight of a risk (#346): rate of the POI's place divided by the national rate, same year.
 * It is the only comparable measure across different items (thefts are always far more than
 * robberies). The item's match kind does not weigh: the indicator says it (#347). `null` = no
 * data (see `istatMatch`). Never shown on screen (D9).
 */
export function istatWeight(hazard: string, istat: IstatPoi | null | undefined): number | null {
  return istatMatch(hazard, istat)?.weight ?? null;
}

export interface IstatOrdering {
  risks: RiskItem[];
  /**
   * Number of risks with ISTAT data, at the head of `risks` (#346, O9): 0 if none (order
   * unchanged, no note). `rankedCount > 0` replaces the old `byIstat` flag — it is derived from
   * here instead of carrying a redundant bit.
   */
  rankedCount: number;
}

/**
 * Orders the risks of a source group with the ISTAT datum of the POI's place (#346): first those
 * with data by decreasing weight, then the others in arrival order. Stable: at equal weight (risks
 * on the same item) the arrival order is kept. Does not mutate the input array.
 */
export function orderRisksByIstat(
  risks: RiskItem[],
  istat: IstatPoi | null | undefined,
): IstatOrdering {
  const withData: { risk: RiskItem; index: number; weight: number }[] = [];
  const withoutData: RiskItem[] = [];
  risks.forEach((risk, index) => {
    const weight = istatWeight(risk.hazard, istat);
    if (weight === null) withoutData.push(risk);
    else withData.push({ risk, index, weight });
  });
  if (withData.length === 0) return { risks, rankedCount: 0 };
  withData.sort((a, b) => b.weight - a.weight || a.index - b.index);
  return {
    risks: [...withData.map((w) => w.risk), ...withoutData],
    rankedCount: withData.length,
  };
}

/**
 * Warning when the ISTAT item does not coincide with the risk (#345, D3): the exact one has
 * none. An out-of-contract value (legacy data, version mismatch) gets a generic warning instead
 * of none: staying silent would make the item pass for coincident.
 */
function istatMatchNote(match: IstatMatchKind): string | null {
  switch (match) {
    case 'esatta':
      return null;
    case 'piu_larga':
      return 'voce ISTAT più ampia del rischio';
    case 'piu_stretta':
      return 'voce ISTAT che copre solo una parte del rischio';
    default:
      return 'voce ISTAT non coincidente col rischio';
  }
}

/** Thousands dot on the integer part (134169 → 134.169). */
function withThousandsDots(integer: string): string {
  return integer.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
}

/** Integer with thousands dot (134.169), like the backend's `formatta_intero`. */
function formatIstatCount(n: number): string {
  return withThousandsDots(String(n));
}

/**
 * One decimal, decimal comma and thousands dot (1.162,7), like the backend's `formatta_decimale`
 * (`istat/rows.py`).
 */
function formatIstatDecimal(x: number): string {
  const [integer, decimal] = x.toFixed(1).split('.');
  return `${withThousandsDots(integer)},${decimal}`;
}

/** Rate published per 100,000 inhabitants: "meno di 0,1" if ISTAT publishes it that way (`_tasso`). */
function formatIstatRate(value: number | null, belowThreshold: boolean): string {
  if (value != null) return formatIstatDecimal(value);
  return belowThreshold ? 'meno di 0,1' : 'non disponibile';
}

/**
 * 10-year trend with only the sign of the change, without a "stable" band: the same criterion as
 * the narrative's figures check (`istat/figures.py`), which accepts "in aumento/in calo" for any
 * change with the right sign. It also reports the crimes of the base year (absolute values of
 * both years), so a huge percentage on few cases reads for what it is.
 */
function istatTrend(row: IstatRow): Pick<IstatIndicator, 'arrow' | 'trend'> {
  const v = row.variazione_pct;
  if (v == null) {
    const reason = row.motivo_senza_variazione;
    const trend = reason ? `tendenza non calcolabile: ${reason}` : 'tendenza non calcolabile';
    return { arrow: null, trend };
  }
  const were =
    row.delitti_confronto != null ? `, erano ${formatIstatCount(row.delitti_confronto)}` : '';
  const sign = v > 0 ? '+' : v < 0 ? '−' : '';
  const pct = `${sign}${Math.abs(v)}% dal ${row.anno_confronto}${were}`;
  if (v > 0) return { arrow: '▲', trend: `in crescita (${pct})` };
  if (v < 0) return { arrow: '▼', trend: `in calo (${pct})` };
  return { arrow: null, trend: `stabile (${pct})` };
}

/**
 * ISTAT indicator next to a risk (#347), in parts: `data` is the text before the trend;
 * the `arrow` is decorative (the template renders it `aria-hidden`, the `trend` already says "in
 * crescita"/"in calo"), so screen readers do not read "black triangle". On an item already
 * shown by a previous risk of the same group `data` is "stessa voce ISTAT: …" and
 * `trend` is `null`.
 */
export interface IstatIndicator {
  data: string;
  arrow: '▲' | '▼' | null;
  trend: string | null;
}

/** A risk of the Detail with its ISTAT indicator (`null` if the risk has no data). */
export interface IstatEntry {
  risk: RiskItem;
  indicator: IstatIndicator | null;
}

/**
 * ISTAT indicators of the risks of a group in the Detail (#347), in the given order. Full row:
 * item (with the warning if it does not coincide with the risk), crimes reported in the last
 * year, the place's rate and the Italian rate as published (never their ratio, D9) and 10-year
 * trend. The place is in the group's note. `null` exactly when `istatWeight` is `null` (same
 * `istatMatch`), so indicator and order do not diverge. When several risks share the same item
 * only the first occurrence (in order, not by adjacency) is full: the others say
 * "stessa voce ISTAT: …" with their own warning, because the match is per risk.
 */
export function withIstatIndicators(
  risks: RiskItem[],
  istat: IstatPoi | null | undefined,
): IstatEntry[] {
  const seen = new Set<string>();
  return risks.map((risk) => {
    const found = istatIndicatorFor(risk.hazard, istat);
    if (!found) return { risk, indicator: null };
    if (seen.has(found.item)) {
      const data = `stessa voce ISTAT: ${found.itemLabel}`;
      return { risk, indicator: { data, arrow: null, trend: null } };
    }
    seen.add(found.item);
    return { risk, indicator: found.indicator };
  });
}

/**
 * Compact ISTAT indicator for the prose (#365): place and year, item, rates (same formatters as
 * the Detail), short trend and, only if the item does not coincide with the risk, the warning at
 * the end. No crime counts nor "erano …": inside a sentence it must stay short. The place is that
 * of the row used (municipality or province).
 */
export interface IstatProseIndicator {
  data: string;
  arrow: '▲' | '▼' | null;
  trend: string;
  note: string | null;
}

function istatProseIndicator(row: IstatRow, matchNote: string | null): IstatProseIndicator {
  const rate = formatIstatRate(row.tasso, row.tasso_sotto_soglia);
  const italy = formatIstatRate(row.tasso_italia, row.tasso_italia_sotto_soglia);
  const data = `ISTAT · ${row.luogo_nome} ${row.anno} · ${row.voce_label}: ${rate} ogni 100.000 ab. (Italia ${italy})`;
  const v = row.variazione_pct;
  let arrow: '▲' | '▼' | null = null;
  let trend = 'tendenza n.d.';
  if (v != null) {
    const sign = v > 0 ? '+' : v < 0 ? '−' : '';
    trend = `${sign}${Math.abs(v)}% dal ${row.anno_confronto}`;
    arrow = v > 0 ? '▲' : v < 0 ? '▼' : null;
  }
  // The Detail notes all start with "voce ISTAT": here "ISTAT" is already at the head of the indicator.
  const note = matchNote ? matchNote.replace(/^voce ISTAT /, 'voce ') : null;
  return { data, arrow, trend, note };
}

/**
 * Full indicator of a hazard (#347, reused by the narrative #365): the single point that
 * translates an `istatMatch` into the displayed text, so Detail and prose cannot diverge in
 * formats. `item` is the item code (dedup key), `itemLabel` the label with the possible
 * match warning. `null` exactly when `istatMatch` is `null`.
 */
function istatIndicatorFor(
  hazard: string,
  istat: IstatPoi | null | undefined,
): {
  item: string;
  itemLabel: string;
  indicator: IstatIndicator;
  prose: IstatProseIndicator;
} | null {
  const match = istatMatch(hazard, istat);
  if (!match) return null;
  const { row, link } = match;
  const note = istatMatchNote(link.corrispondenza);
  const itemLabel = note ? `${row.voce_label} (${note})` : row.voce_label;
  // `istatMatch` already excludes missing counts: `delitti` here is always a number.
  const crimes = `${formatIstatCount(row.delitti ?? 0)} delitti denunciati nel ${row.anno}`;
  const rate = formatIstatRate(row.tasso, row.tasso_sotto_soglia);
  const italy = formatIstatRate(row.tasso_italia, row.tasso_italia_sotto_soglia);
  const data = `${itemLabel} · ${crimes} · ${rate} ogni 100.000 ab. (Italia: ${italy})`;
  return {
    item: row.voce,
    itemLabel,
    indicator: { data, ...istatTrend(row) },
    prose: istatProseIndicator(row, note),
  };
}

/** A risk (with its Italian label) seen on a POI, with the ISTAT datum of that POI (#365). */
export interface IstatHazardOccurrence {
  hazardLabel: string;
  hazard: string;
  istat: IstatPoi | null | undefined;
}

/** Risk with valid ISTAT data, ready to be searched in the prose (#365). */
export interface IstatProseCandidate {
  /** Exact Italian label of the risk, searched in the text. */
  hazardLabel: string;
  /** Code of the ISTAT item: one indicator per item. */
  item: string;
  indicator: IstatProseIndicator;
}

/** Piece of prose: plain text or inline ISTAT indicator (#365). */
export type ProseSegment =
  { kind: 'text'; text: string } | { kind: 'istat'; indicator: IstatProseIndicator };

/**
 * Flattens POIs + risk models in the order of the POIs (join by `poi_id`, like
 * `buildDetailModel`): each entry carries the `istat` of its own POI. It applies to the zone (all
 * the POIs) and to the point (one POI and its model).
 */
export function flattenIstatOccurrences(
  poi: Poi[] | null | undefined,
  riskModels: RiskModel[] | null | undefined,
): IstatHazardOccurrence[] {
  const out: IstatHazardOccurrence[] = [];
  for (const p of poi ?? []) {
    const model = (riskModels ?? []).find((r) => r.poi_id === p.id);
    for (const risk of model?.risks ?? []) {
      out.push({ hazardLabel: hazardDisplayLabel(risk), hazard: risk.hazard, istat: p.istat });
    }
  }
  return out;
}

/**
 * Candidates for the prose (#365): for each risk, the first POI (in order) that has it with a
 * valid ISTAT datum (`istatMatch` not null, hence `ISTAT_MIN_DELITTI` threshold included). Risks
 * without data in any POI produce no candidates.
 */
export function buildIstatProseCandidates(
  occurrences: IstatHazardOccurrence[],
): IstatProseCandidate[] {
  const found = new Set<string>();
  const out: IstatProseCandidate[] = [];
  for (const occ of occurrences) {
    if (found.has(occ.hazard)) continue;
    const hit = istatIndicatorFor(occ.hazard, occ.istat);
    if (!hit) continue;
    found.add(occ.hazard);
    out.push({ hazardLabel: occ.hazardLabel, item: hit.item, indicator: hit.prose });
  }
  return out;
}

/** Characters that close a quotation or markdown formatting after the mention (#365). */
const CLOSERS = new Set(['\u201D', '"', '\u00BB', '\u2019', '\u2018', '*', '_']);
const SINGLE_QUOTES = new Set(['’', '‘']);
/** A single punctuation mark right after the mention: the indicator follows it, it does not precede it. */
const TRAILING_PUNCTUATION = new Set([',', '.', ';', ':', ')']);

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Typographic apostrophes → straight, one character for one: indices remain those of the prose. */
function normalizeApostrophes(value: string): string {
  return value.replace(/[\u2018\u2019]/g, "'");
}

/**
 * Prose in segments (#365, D6): after the FIRST mention of the exact Italian label of a risk
 * with ISTAT data the indicator is inserted. Case-insensitive comparison, straight or
 * typographic apostrophe equivalent; word boundaries with Unicode letters/digits and `_` (the
 * opening and closing quotes and markdown markers `*`/`_` are not word characters, so they do
 * not prevent the match; `furto_di_rame` instead is a single word). Longer labels are
 * tried first. `blocks` are the labels of ALL the risks of the scope, even without data:
 * they consume the match without an indicator, so "Furto con strappo" (without data) is not read
 * as "Furto" (with data). With the same label on several candidates the first wins (POI order).
 * Known limit: attribution is by EXACT WORD of the label in the text. If a risk with data
 * ("Furto") appears inside a longer phrase that is not a risk of the scope ("Aggressione a
 * scopo di furto"), the indicator attaches there.
 * One indicator per ISTAT item. After the mention the indicator skips the closing quotes
 * and the closing markdown markers (`**`, `*`, `_`). No HTML: the template renders the segments.
 */
export function withIstatProseIndicators(
  prose: string,
  candidates: IstatProseCandidate[],
  blocks: string[] = [],
): ProseSegment[] {
  if (!prose) return [];
  const byLabel = new Map<string, IstatProseCandidate | null>();
  for (const c of candidates) {
    const key = normalizeApostrophes(c.hazardLabel).toLowerCase();
    if (c.hazardLabel && !byLabel.get(key)) byLabel.set(key, c);
  }
  if (byLabel.size === 0) return [{ kind: 'text', text: prose }];
  for (const label of blocks) {
    const key = normalizeApostrophes(label).toLowerCase();
    if (label && !byLabel.has(key)) byLabel.set(key, null);
  }
  const alternation = [...byLabel.keys()]
    .sort((a, b) => b.length - a.length)
    .map(escapeRegExp)
    .join('|');
  // No lookbehind (Safari 16.0-16.3 does not support it, #387): the left boundary is a captured
  // prefix group (start of text, or a non-word, plus at most two opening markdown `_`)
  // and the mention starts at `m.index + m[1].length`. On the right a lookahead, which Safari
  // knows: `_` is a word character (identifiers like `furto_di_rame`), but a closing markdown
  // `_` (`_furto_`, `__furto__`) is not, i.e. it does not count if another word follows.
  const re = new RegExp(
    `((?:^|[^\\p{L}\\p{N}_])_{0,2})(?:${alternation})(?!_*[\\p{L}\\p{N}])`,
    'giu',
  );
  const haystack = normalizeApostrophes(prose);

  const segments: ProseSegment[] = [];
  const seenLabels = new Set<string>();
  const shownItems = new Set<string>();
  let cursor = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(haystack)) !== null) {
    const mention = m[0].slice(m[1].length);
    const label = mention.toLowerCase();
    if (seenLabels.has(label)) continue;
    seenLabels.add(label);
    const candidate = byLabel.get(label);
    if (!candidate || shownItems.has(candidate.item)) continue;
    shownItems.add(candidate.item);
    let end = m.index + m[0].length;
    while (end < prose.length && CLOSERS.has(prose[end])) {
      // ’ and ‘ close only if they are not a word's apostrophe (dell’area): no letter after.
      if (SINGLE_QUOTES.has(prose[end]) && /[\p{L}\p{N}]/u.test(prose[end + 1] ?? '')) break;
      end += 1;
    }
    if (end < prose.length && TRAILING_PUNCTUATION.has(prose[end])) end += 1;
    segments.push({ kind: 'text', text: prose.slice(cursor, end) });
    segments.push({ kind: 'istat', indicator: candidate.indicator });
    cursor = end;
  }
  if (cursor < prose.length) segments.push({ kind: 'text', text: prose.slice(cursor) });
  return segments;
}

/**
 * Note of the groups ordered with the ISTAT datum (#346): says what is compared (rates of the
 * place and the Italian one, not the number of crimes), with place and year; no values (D9).
 */
export function istatOrderNote(istat: IstatPoi): string {
  return `Ordinati confrontando il tasso per 100.000 abitanti del luogo con quello italiano, non in base al numero di delitti (ISTAT ${istat.cornice.anno}, ${istat.cornice.luogo_nome}).`;
}

export interface BaseRow {
  poiId: string;
  poiName: string;
  hazardLabel: string;
  category: string;
}

/**
 * Rows of the "POI · Hazard · Categoria" table of the Base system State (ablation,
 * spec-frontend.md §Base system State): one row for each (POI, hazard) pair, same
 * POI↔RiskModel matching by `poi_id` used by `buildDetailModel`. "Categoria" stays the raw
 * terminus class (`tc:` prefix), deliberately technical and untranslated — consistent
 * with the visual poverty wanted by the ablation comparison (the full system instead shows
 * the curated IT label in `poiDisplayLabel`).
 */
export function buildBaseRows(
  poi: Poi[] | null | undefined,
  riskModels: RiskModel[] | null | undefined,
): BaseRow[] {
  const rows: BaseRow[] = [];
  for (const p of poi ?? []) {
    const model = (riskModels ?? []).find((r) => r.poi_id === p.id);
    for (const risk of model?.risks ?? []) {
      rows.push({
        poiId: p.id,
        poiName: p.name,
        hazardLabel: hazardDisplayLabel(risk),
        category: `tc:${p.ontology_class}`,
      });
    }
  }
  return rows;
}

/**
 * Single rule "the POI matches the active confidence filter" — consumed both by
 * `PoiPanelComponent` ("hide" semantics: excludes non-matching ones from the list)
 * and by `MapComponent` ("dim" semantics: non-matching ones stay visible but `dim`).
 * Null `filter` = no active filter, all POIs match (including a POI outside the ontology,
 * `confidence: null`, #220). With an active filter a `null` POI NEVER matches: it is not
 * filterable as a category (no level represents it in `LEVELS`).
 */
export function matchesFilter(confidence: Confidence | null, filter: Confidence | null): boolean {
  return filter == null || confidence === filter;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export interface SourceTab {
  tag: NarrativeSourceTag;
  prose: string;
}
export interface NarrativeTabsModel {
  overview: string;
  tabs: SourceTab[];
}

const SOURCE_PROSE_KEY: Readonly<Record<NarrativeSourceTag, keyof Omit<SourceProse, 'overview'>>> =
  {
    ONTOLOGIA: 'ontologia',
    CONTESTO: 'contesto',
    SPECULATIVO: 'speculativo',
    ISTAT: 'istat',
  };

/**
 * Builds the narrative's tab model (State B) from the per-source prose alone
 * (`narrativa_fonti`). A tab is included only if it has non-empty prose; canonical order
 * ONTOLOGIA→CONTESTO→ISTAT→SPECULATIVO. `overview` is exposed separately (shown above the tabs).
 *
 * #329: the panel also showed, under the prose, the list of hazards per source — all the
 * risks of all the POIs of the zone, flattened and not deduplicated. On a 20-point zone that was
 * about 160 entries, with the same blocks repeated: the risks depend only on the TERMINUS class,
 * so three railway stations poured the same eleven hazards three times. Detached from their own
 * POI they were not even interpretable. They stayed where they make sense, i.e. in the Detail
 * panel: there each risk is attributed to its point and carries the SPARQL citation.
 *
 * Consequently `riskModels` is no longer needed here, and a tag with only hazards no longer opens
 * a tab (which would be empty). With the narrative in fallback there is no tab: the fallback
 * message points to the Detail.
 */
export function buildSourceTabs(sources: SourceProse | null | undefined): NarrativeTabsModel {
  const tabs: SourceTab[] = [];
  for (const tag of NARRATIVE_TAG_ORDER) {
    const prose = (sources?.[SOURCE_PROSE_KEY[tag]] ?? '').trim();
    if (prose) tabs.push({ tag, prose });
  }
  return { overview: (sources?.overview ?? '').trim(), tabs };
}

/**
 * Leaflet popup markup for a POI marker: number, name, IT label and confidence badge.
 * A POI outside the ontology (`confidence: null`, #220) does not show the badge row (no badge,
 * consistent with the card of `PoiPanelComponent` and the header of `DetailPanelComponent`).
 * Defensive fallback (`confMeta`, `core/confidence.ts`) if `confidence` is an out-of-contract
 * string (not one of the 2 known levels): an unexpected entry must not interrupt the redraw
 * `forEach` of the following markers.
 */
export function poiPopupHTML(
  poi: Pick<Poi, 'name' | 'confidence' | 'ontology_class' | 'ontology_label_it'>,
  n: number,
): string {
  const confLine = poi.confidence
    ? (() => {
        const meta = confMeta(poi.confidence);
        return `<div class="cra-poi-popup-conf" style="color:${meta.color}">${meta.dot} ${meta.label}</div>`;
      })()
    : '';
  return (
    `<div class="cra-poi-popup">` +
    `<strong>${n}. ${escapeHtml(poiNameDisplayLabel(poi))}</strong>` +
    `<div class="cra-poi-popup-class">${escapeHtml(poiDisplayLabel(poi))}</div>` +
    confLine +
    `</div>`
  );
}
