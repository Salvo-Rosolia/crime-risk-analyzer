import { CONF, ConfMeta, DIM_COLOR } from '@core/confidence';
import { Confidence, Poi, RiskItem, RiskModel, SourceProse, SourceTag } from '@core/models/models';

/**
 * Ordine canonico dei tag fonte (spec-frontend.md, cross-cutting: Stato B narrativa per fonte E
 * Stato C fattori di rischio per fonte). Unica costante condivisa da `buildNarrativeSections` e
 * `orderGroupsByTag` — prima duplicata in due array locali identici (review #67, non-bloccante).
 */
const SOURCE_TAG_ORDER: readonly SourceTag[] = ['ONTOLOGIA', 'CONTESTO', 'SPECULATIVO'];

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

export function validateInputPanel({
  citta,
  zona,
}: {
  citta?: string;
  zona?: string;
  domanda?: string;
} = {}): InputPanelValidation {
  if (!citta || !citta.trim()) {
    return { ok: false, error: 'Inserisci una città.', field: 'citta' };
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

export interface NarrativeSection {
  tag: string;
  hazards: string[];
}

export function buildNarrativeSections(
  riskModels: RiskModel[] | null | undefined,
): NarrativeSection[] {
  const byTag = new Map<string, string[]>();
  for (const model of riskModels ?? []) {
    for (const risk of model.risks ?? []) {
      const tag = risk.tag || 'SPECULATIVO';
      const list = byTag.get(tag) ?? [];
      list.push(hazardDisplayLabel(risk));
      byTag.set(tag, list);
    }
  }
  const sections: NarrativeSection[] = [];
  for (const tag of SOURCE_TAG_ORDER) {
    const hazards = byTag.get(tag);
    if (hazards) sections.push({ tag, hazards });
  }
  for (const [tag, hazards] of byTag) {
    if (!SOURCE_TAG_ORDER.includes(tag as SourceTag)) sections.push({ tag, hazards });
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

export function buildDetailModel(
  poi: Poi,
  riskModels: RiskModel[] | null | undefined,
): DetailModel {
  const sparqlParts = poi.sparql_path ? poi.sparql_path.split(' → ') : [];
  const model = (riskModels ?? []).find((r) => r.poi === poi.name);
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
 * Ordina i `groups` di `buildDetailModel` (Record non ordinato) nell'ordine canonico
 * ONTOLOGIA → CONTESTO → SPECULATIVO richiesto dallo Stato C (spec-frontend.md); eventuali tag
 * fuori contratto restano in coda, stessa convenzione di `buildNarrativeSections`. Tag assenti
 * o con lista vuota vengono omessi.
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

export interface BaseRow {
  poiId: string;
  poiName: string;
  hazardLabel: string;
  category: string;
}

/**
 * Righe della tabella "POI · Hazard · Categoria" dello Stato Sistema base (ablation,
 * spec-frontend.md §Stato Sistema base): una riga per ogni coppia (POI, hazard), stesso
 * abbinamento POI↔RiskModel per nome usato da `buildDetailModel`. "Categoria" resta la
 * terminus class grezza (prefisso `tc:`), deliberatamente tecnica e non tradotta — coerente
 * con la povertà visiva voluta dal confronto ablation (il sistema completo mostra invece
 * l'etichetta IT curata in `poiDisplayLabel`).
 */
export function buildBaseRows(
  poi: Poi[] | null | undefined,
  riskModels: RiskModel[] | null | undefined,
): BaseRow[] {
  const rows: BaseRow[] = [];
  for (const p of poi ?? []) {
    const model = (riskModels ?? []).find((r) => r.poi === p.name);
    for (const risk of model?.risks ?? []) {
      rows.push({
        poiId: p.id,
        poiName: p.name,
        hazardLabel: hazardDisplayLabel(risk),
        category: `tc:${p.terminus_class}`,
      });
    }
  }
  return rows;
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

const UNKNOWN_CONF_META: ConfMeta = {
  color: DIM_COLOR,
  bg: DIM_COLOR,
  dot: '?',
  label: 'Sconosciuto',
};

export interface SourceTab {
  tag: SourceTag;
  prose: string;
  hazards: string[];
}
export interface NarrativeTabsModel {
  overview: string;
  tabs: SourceTab[];
}

const SOURCE_PROSE_KEY: Readonly<Record<SourceTag, keyof Omit<SourceProse, 'overview'>>> = {
  ONTOLOGIA: 'ontologia',
  CONTESTO: 'contesto',
  SPECULATIVO: 'speculativo',
};

/**
 * Unisce la prosa per fonte (`narrativa_fonti`) con gli hazard per fonte (deterministici, via
 * `buildNarrativeSections`) in un modello a tab (Stato B). Un tab è incluso solo se ha prosa non
 * vuota OPPURE almeno un hazard; ordine canonico ONTOLOGIA→CONTESTO→SPECULATIVO. `overview` è
 * esposto a parte (mostrato sopra i tab). `fonti` null/assente → prosa vuota (tab solo da hazard).
 */
export function buildSourceTabs(
  fonti: SourceProse | null | undefined,
  riskModels: RiskModel[] | null | undefined,
): NarrativeTabsModel {
  const hazByTag = new Map(buildNarrativeSections(riskModels).map((s) => [s.tag, s.hazards]));
  const tabs: SourceTab[] = [];
  for (const tag of SOURCE_TAG_ORDER) {
    const prose = (fonti?.[SOURCE_PROSE_KEY[tag]] ?? '').trim();
    const hazards = hazByTag.get(tag) ?? [];
    if (prose || hazards.length) tabs.push({ tag, prose, hazards });
  }
  return { overview: (fonti?.overview ?? '').trim(), tabs };
}

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
