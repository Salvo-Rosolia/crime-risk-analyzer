import { CONF, ConfMeta, DIM_COLOR } from '@core/confidence';
import { Confidence, Poi, RiskItem, RiskModel, SourceTag } from '@core/models/models';

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
  /** Campo a cui imputare l'errore (per evidenziare solo il bordo pertinente in UI). */
  field: 'citta' | 'zona' | null;
}

export function validateInputPanel(
  { citta, zona, cities }: { citta?: string; zona?: string; domanda?: string; cities?: string[] } = {},
): InputPanelValidation {
  if (!citta || !citta.trim()) {
    return { ok: false, error: 'Seleziona una città.', field: 'citta' };
  }
  if (cities && cities.length > 0 && !cities.includes(citta)) {
    return { ok: false, error: `Città non supportata: ${citta}.`, field: 'citta' };
  }
  if (!zona || !zona.trim()) {
    return { ok: false, error: 'Inserisci una zona.', field: 'zona' };
  }
  return { ok: true, error: null, field: null };
}

/** Etichetta IT controllata dell'hazard (#77) con fallback all'identificatore di classe grezzo. */
export function hazardDisplayLabel(risk: Pick<RiskItem, 'hazard' | 'hazard_label_it'>): string {
  return risk.hazard_label_it || risk.hazard;
}

/** Etichetta IT controllata della classe POI (#77) con fallback all'identificatore di classe grezzo. */
export function poiDisplayLabel(poi: Pick<Poi, 'terminus_class' | 'terminus_label_it'>): string {
  return poi.terminus_label_it || poi.terminus_class;
}

export interface NarrativeSection { tag: string; hazards: string[]; }

export function buildNarrativeSections(riskModels: RiskModel[] | null | undefined): NarrativeSection[] {
  const byTag = new Map<string, string[]>();
  for (const model of riskModels ?? []) {
    for (const risk of model.risks ?? []) {
      const tag = risk.tag || 'SPECULATIVO';
      const list = byTag.get(tag) ?? [];
      list.push(hazardDisplayLabel(risk));
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
  /** Etichetta IT preferita del POI (fallback a terminus_class se manca). */
  poiLabel: string;
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
  return { poi, poiLabel: poiDisplayLabel(poi), sparqlParts, groups };
}

/**
 * Regola unica "il POI corrisponde al filtro di confidence attivo" — consumata sia da
 * `PoiPanelComponent` (semantica "nascondi": esclude i non corrispondenti dalla lista)
 * sia da `MapComponent` (semantica "attenua": i non corrispondenti restano visibili ma `dim`).
 * `filter` nullo = nessun filtro attivo, tutti i POI corrispondono.
 */
export function matchesFilter(confidence: Confidence, filter: Confidence | null): boolean {
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

const UNKNOWN_CONF_META: ConfMeta = { color: DIM_COLOR, bg: DIM_COLOR, dot: '?', label: 'Sconosciuto' };

/**
 * Markup del popup Leaflet per un marker POI: numero, nome, etichetta IT e badge confidence.
 * Fallback difensivo (come `pinColor`) se `confidence` non è uno dei 3 livelli noti: una voce
 * imprevista non deve interrompere il `forEach` di redraw dei marker successivi.
 */
export function poiPopupHTML(
  poi: Pick<Poi, 'name' | 'confidence' | 'terminus_class' | 'terminus_label_it'>,
  n: number,
): string {
  const meta = (CONF as Record<string, ConfMeta>)[poi.confidence] ?? UNKNOWN_CONF_META;
  return (
    `<div class="cra-poi-popup">` +
    `<strong>${n}. ${escapeHtml(poi.name)}</strong>` +
    `<div class="cra-poi-popup-class">${escapeHtml(poiDisplayLabel(poi))}</div>` +
    `<div class="cra-poi-popup-conf" style="color:${meta.color}">${meta.dot} ${meta.label}</div>` +
    `</div>`
  );
}
