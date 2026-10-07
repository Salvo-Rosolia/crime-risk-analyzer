import { confMeta } from '@core/confidence';
import {
  Confidence,
  IstatPoi,
  NarrativeSourceTag,
  OntologyItem,
  Poi,
  RiskItem,
  RiskModel,
  SourceProse,
  SourceTag,
} from '@core/models/models';

/**
 * Ordine canonico dei tag fonte (spec-frontend.md, cross-cutting: Stato C fattori di rischio per
 * fonte). Condivisa da `orderGroupsByTag`; le schede della narrativa usano `NARRATIVE_TAG_ORDER`
 * (include ISTAT, che un rischio non può mai avere).
 */
const SOURCE_TAG_ORDER: readonly SourceTag[] = ['ONTOLOGIA', 'CONTESTO', 'SPECULATIVO'];

/**
 * Ordine delle schede della narrativa (#345): i blocchi nell'ordine in cui il modello li scrive
 * (ONTOLOGIA, CONTESTO, ISTAT), poi SPECULATIVO. Separato da `SOURCE_TAG_ORDER`, che ordina i
 * gruppi di rischi e non può contenere ISTAT.
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
  /** Campo a cui imputare l'errore (per evidenziare solo il bordo pertinente in UI). */
  field: 'citta' | 'zona' | null;
}

/**
 * Validazione client della coppia città/zona (restaurata da prima di #318): usata dai pannelli
 * "Analisi zona" e "Sistema base" quando l'area non è già un cerchio disegnato — un submit con un
 * cerchio presente non la invoca nemmeno, perché un cerchio è per costruzione già un'area valida.
 */
export function validateInputPanel({
  citta,
  zona,
}: {
  citta?: string;
  zona?: string;
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

/** Etichetta IT controllata di un'entità ontologica (#256) con fallback all'identificatore grezzo.
 * Stesso pattern di `hazardDisplayLabel`/`poiDisplayLabel`: la regola vive qui e non nel template,
 * così il ramo di fallback è esercitabile da un test. */
export function ontologyDisplayLabel(item: Pick<OntologyItem, 'name' | 'label_it'>): string {
  return item.label_it || item.name;
}

/** Etichetta IT controllata della classe POI (#77) con fallback all'identificatore di classe grezzo. */
export function poiDisplayLabel(poi: Pick<Poi, 'terminus_class' | 'terminus_label_it'>): string {
  return poi.terminus_label_it || poi.terminus_class;
}

/**
 * Etichetta di ripiego per un POI senza `name` (#261): i nomi OSM non sono sempre presenti (le
 * feature anonime arrivano con `name` vuoto, stessa ragione per cui il POI è `da_confermare`,
 * #220). Il ripiego è costruito sulla classe (`poiDisplayLabel`) e dichiara esplicitamente
 * l'assenza, invece di lasciare una riga bianca in lista/popup/dettaglio. `trim()` prima del
 * controllo: un nome fatto di soli spazi è dato OSM reale, è truthy in JS, e senza trim
 * riprodurrebbe la stessa riga vuota — `confidence_from_poi_name` (backend, rag/grounding.py)
 * fa già lo stesso trim, quindi qui allinea la UI a un POI che il backend marca da_confermare.
 */
export function poiNameDisplayLabel(
  poi: Pick<Poi, 'name' | 'terminus_class' | 'terminus_label_it'>,
): string {
  const name = poi.name?.trim();
  return name || `${poiDisplayLabel(poi)} (senza nome su OSM)`;
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
  // Aggancio per `poi_id`, non per nome: i nomi OSM non sono né unici né sempre presenti,
  // quindi un `find` per nome fa vedere sul dettaglio di un punto i rischi di un altro.
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
 * Ordina i `groups` di `buildDetailModel` (Record non ordinato) nell'ordine canonico
 * ONTOLOGIA → CONTESTO → SPECULATIVO richiesto dallo Stato C (spec-frontend.md); eventuali tag
 * fuori contratto restano in coda. Tag assenti
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

/**
 * Peso ISTAT di un rischio (#346): tasso del luogo del POI diviso tasso nazionale, stesso anno.
 * È l'unica misura confrontabile fra voci diverse (i furti sono sempre molti più delle rapine).
 * La corrispondenza della voce non pesa: lo dirà l'indicatore della #347. `null` = nessun dato
 * (rischio senza voce, tasso o tasso nazionale assenti, tasso nazionale 0); il «meno di 0,1»
 * pubblicato da ISTAT vale 0, perché il dato c'è. Mai mostrato a schermo (D9).
 */
export function istatWeight(hazard: string, istat: IstatPoi | null | undefined): number | null {
  const riga = istat?.righe.find((r) => r.collegamenti.some((c) => c.hazard === hazard));
  if (!riga) return null;
  if (riga.tasso_sotto_soglia) return 0;
  if (riga.tasso == null || riga.tasso_italia == null || riga.tasso_italia === 0) return null;
  return riga.tasso / riga.tasso_italia;
}

export interface IstatOrdering {
  risks: RiskItem[];
  /** Vero se almeno un rischio ha un dato ISTAT: il gruppo è stato ordinato e porta la nota. */
  byIstat: boolean;
}

/**
 * Ordina i rischi di un gruppo-fonte col dato ISTAT del luogo del POI (#346): prima quelli con
 * dato per peso decrescente, poi gli altri nell'ordine di arrivo. Stabile: a pari peso (rischi
 * sulla stessa voce) resta l'ordine di arrivo. Non muta l'array in ingresso.
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
  if (withData.length === 0) return { risks, byIstat: false };
  withData.sort((a, b) => b.weight - a.weight || a.index - b.index);
  return { risks: [...withData.map((w) => w.risk), ...withoutData], byIstat: true };
}

/** Nota dei gruppi ordinati col dato ISTAT (#346): luogo e anno, nessuna cifra (D9). */
export function istatOrderNote(istat: IstatPoi): string {
  return `Ordinati in base ai delitti denunciati rispetto alla media italiana (ISTAT ${istat.cornice.anno}, ${istat.cornice.luogo_nome}).`;
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
 * abbinamento POI↔RiskModel per `poi_id` usato da `buildDetailModel`. "Categoria" resta la
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
    const model = (riskModels ?? []).find((r) => r.poi_id === p.id);
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
 * `filter` nullo = nessun filtro attivo, tutti i POI corrispondono (incluso un POI fuori ontologia,
 * `confidence: null`, #220). Con un filtro attivo un POI `null` non corrisponde MAI: non è
 * filtrabile come categoria (nessun livello lo rappresenta in `LEVELS`).
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
 * Costruisce il modello a tab della narrativa (Stato B) dalla sola prosa per fonte
 * (`narrativa_fonti`). Un tab è incluso solo se ha prosa non vuota; ordine canonico
 * ONTOLOGIA→CONTESTO→ISTAT→SPECULATIVO. `overview` è esposto a parte (mostrato sopra i tab).
 *
 * #329: il pannello mostrava anche, sotto la prosa, l'elenco degli hazard per fonte — tutti i
 * rischi di tutti i POI della zona, appiattiti e non deduplicati. Su una zona da 20 punti erano
 * circa 160 voci, con gli stessi blocchi ripetuti: i rischi dipendono solo dalla classe TERMINUS,
 * quindi tre stazioni ferroviarie versavano tre volte gli stessi undici hazard. Staccati dal
 * proprio POI non erano nemmeno interpretabili. Sono rimasti dove hanno senso, cioè nel pannello
 * Dettaglio: lì ogni rischio è attribuito al suo punto e porta la citazione SPARQL.
 *
 * Di conseguenza `riskModels` non serve più qui, e un tag con soli hazard non apre più un tab
 * (che sarebbe vuoto). Con la narrativa in fallback non c'è alcun tab: il messaggio di fallback
 * rimanda al Dettaglio.
 */
export function buildSourceTabs(fonti: SourceProse | null | undefined): NarrativeTabsModel {
  const tabs: SourceTab[] = [];
  for (const tag of NARRATIVE_TAG_ORDER) {
    const prose = (fonti?.[SOURCE_PROSE_KEY[tag]] ?? '').trim();
    if (prose) tabs.push({ tag, prose });
  }
  return { overview: (fonti?.overview ?? '').trim(), tabs };
}

/**
 * Markup del popup Leaflet per un marker POI: numero, nome, etichetta IT e badge confidence.
 * Un POI fuori ontologia (`confidence: null`, #220) non mostra la riga di badge (nessun badge,
 * coerente con la card di `PoiPanelComponent` e l'header di `DetailPanelComponent`). Fallback
 * difensivo (`confMeta`, `core/confidence.ts`) se `confidence` è una stringa fuori contratto (non
 * uno dei 2 livelli noti): una voce imprevista non deve interrompere il `forEach` di redraw dei
 * marker successivi.
 */
export function poiPopupHTML(
  poi: Pick<Poi, 'name' | 'confidence' | 'terminus_class' | 'terminus_label_it'>,
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
