import { Poi, RiskItem, RiskModel, SourceTag } from '@core/models/models';

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

export function validateInputPanel(
  { zona }: { zona?: string; domanda?: string } = {},
): { ok: boolean; error: string | null } {
  if (!zona || !zona.trim()) {
    return { ok: false, error: 'Inserisci una zona.' };
  }
  return { ok: true, error: null };
}

export interface NarrativeSection { tag: string; hazards: string[]; }

export function buildNarrativeSections(riskModels: RiskModel[] | null | undefined): NarrativeSection[] {
  const byTag = new Map<string, string[]>();
  for (const model of riskModels ?? []) {
    for (const risk of model.risks ?? []) {
      const tag = risk.tag || 'SPECULATIVO';
      const list = byTag.get(tag) ?? [];
      list.push(risk.hazard);
      byTag.set(tag, list);
    }
  }
  const ORDER: SourceTag[] = ['ONTOLOGIA', 'CONTESTO', 'SPECULATIVO'];
  const sections: NarrativeSection[] = [];
  for (const tag of ORDER) {
    const hazards = byTag.get(tag);
    if (hazards) sections.push({ tag, hazards });
  }
  for (const [tag, hazards] of byTag) {
    if (!ORDER.includes(tag as SourceTag)) sections.push({ tag, hazards });
  }
  return sections;
}

export interface DetailModel {
  poi: Poi;
  sparqlParts: string[];
  groups: Record<string, RiskItem[]>;
}

export function buildDetailModel(poi: Poi, riskModels: RiskModel[] | null | undefined): DetailModel {
  const sparqlParts = poi.sparql_path ? poi.sparql_path.split(' → ') : [];
  const model = (riskModels ?? []).find(r => r.poi === poi.name);
  const groups: Record<string, RiskItem[]> = {};
  for (const risk of model?.risks ?? []) {
    const tag = risk.tag || 'SPECULATIVO';
    const list = groups[tag] ?? [];
    list.push(risk);
    groups[tag] = list;
  }
  return { poi, sparqlParts, groups };
}

export function filterVisiblePOIs(pois: Poi[], filter: string | null): Poi[] {
  if (!filter) return pois.slice();
  return pois.filter(p => p.confidence === filter);
}
