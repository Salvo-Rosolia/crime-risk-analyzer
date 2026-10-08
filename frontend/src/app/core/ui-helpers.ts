import { confMeta } from '@core/confidence';
import {
  Confidence,
  IstatCollegamento,
  IstatCorrispondenza,
  IstatPoi,
  IstatRiga,
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
 * Soglia minima di delitti nel luogo nell'ultimo anno perché una voce ISTAT valga come dato
 * (#346, O8, dopo /code-review): stessa soglia `SOGLIA_TENDENZA` di
 * `backend/src/crime_risk_analyzer/istat/righe.py`, sotto la quale il backend non calcola
 * nemmeno la tendenza. Senza questa soglia 1-19 delitti in tutto il comune (es. una sola rapina
 * in banca a Como, peso 12) metterebbero quel rischio in cima all'ordine.
 */
export const ISTAT_MIN_DELITTI = 20;

/** Riga ISTAT agganciata a un rischio, con il collegamento che la lega e il peso (#346/#347). */
interface IstatMatch {
  riga: IstatRiga;
  collegamento: IstatCollegamento;
  weight: number;
}

/**
 * Unica logica di aggancio rischio → voce ISTAT (#346/#347): la usano sia il peso dell'ordine
 * (`istatWeight`) sia l'indicatore (`withIstatIndicators`), così ordine e indicatore non possono
 * divergere. `null` = nessun dato: rischio senza voce, voce con meno di `ISTAT_MIN_DELITTI`
 * delitti nel luogo (o conteggio assente, O8), oppure tasso/tasso nazionale assenti o tasso
 * nazionale 0. Il «meno di 0,1» pubblicato da ISTAT pesa 0 (non `null`): il dato c'è.
 */
function istatMatch(hazard: string, istat: IstatPoi | null | undefined): IstatMatch | null {
  for (const riga of istat?.righe ?? []) {
    const collegamento = riga.collegamenti.find((c) => c.hazard === hazard);
    if (!collegamento) continue;
    if (riga.delitti == null || riga.delitti < ISTAT_MIN_DELITTI) return null;
    if (riga.tasso_sotto_soglia) return { riga, collegamento, weight: 0 };
    if (riga.tasso == null || riga.tasso_italia == null || riga.tasso_italia === 0) return null;
    return { riga, collegamento, weight: riga.tasso / riga.tasso_italia };
  }
  return null;
}

/**
 * Peso ISTAT di un rischio (#346): tasso del luogo del POI diviso tasso nazionale, stesso anno.
 * È l'unica misura confrontabile fra voci diverse (i furti sono sempre molti più delle rapine).
 * La corrispondenza della voce non pesa: la dice l'indicatore (#347). `null` = nessun dato (vedi
 * `istatMatch`). Mai mostrato a schermo (D9).
 */
export function istatWeight(hazard: string, istat: IstatPoi | null | undefined): number | null {
  return istatMatch(hazard, istat)?.weight ?? null;
}

export interface IstatOrdering {
  risks: RiskItem[];
  /**
   * Numero di rischi con dato ISTAT, in testa a `risks` (#346, O9): 0 se nessuno (ordine
   * invariato, nessuna nota). `rankedCount > 0` sostituisce il vecchio flag `byIstat` — si
   * deriva da qui invece di portare un bit ridondante.
   */
  rankedCount: number;
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
  if (withData.length === 0) return { risks, rankedCount: 0 };
  withData.sort((a, b) => b.weight - a.weight || a.index - b.index);
  return {
    risks: [...withData.map((w) => w.risk), ...withoutData],
    rankedCount: withData.length,
  };
}

/**
 * Avviso quando la voce ISTAT non coincide col rischio (#345, D3): l'esatta non ne ha. Un valore
 * fuori contratto (dato legacy, mismatch di versione) riceve un avviso generico invece di
 * nessuno: tacere farebbe passare la voce per coincidente.
 */
function istatCorrispondenzaNote(corrispondenza: IstatCorrispondenza): string | null {
  switch (corrispondenza) {
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

/** Punto delle migliaia sulla parte intera (134169 → 134.169). */
function withThousandsDots(intero: string): string {
  return intero.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
}

/** Intero col punto delle migliaia (134.169), come `formatta_intero` del backend. */
function formatIstatCount(n: number): string {
  return withThousandsDots(String(n));
}

/**
 * Un decimale, virgola decimale e punto delle migliaia (1.162,7), come `formatta_decimale` del
 * backend (`istat/righe.py`).
 */
function formatIstatDecimal(x: number): string {
  const [intero, decimale] = x.toFixed(1).split('.');
  return `${withThousandsDots(intero)},${decimale}`;
}

/** Tasso pubblicato ogni 100.000 abitanti: «meno di 0,1» se ISTAT lo pubblica così (`_tasso`). */
function formatIstatRate(valore: number | null, sottoSoglia: boolean): string {
  if (valore != null) return formatIstatDecimal(valore);
  return sottoSoglia ? 'meno di 0,1' : 'non disponibile';
}

/**
 * Tendenza 10 anni col solo segno della variazione, senza banda «stabile»: lo stesso criterio del
 * controllo cifre della narrativa (`istat/cifre.py`), che accetta «in aumento/in calo» per
 * qualunque variazione col segno giusto. Riporta anche i delitti dell'anno base (valori assoluti
 * di entrambi gli anni), così una percentuale enorme su pochi casi si legge per quello che è.
 */
function istatTrend(riga: IstatRiga): Pick<IstatIndicator, 'freccia' | 'tendenza'> {
  const v = riga.variazione_pct;
  if (v == null) {
    const motivo = riga.motivo_senza_variazione;
    const tendenza = motivo ? `tendenza non calcolabile: ${motivo}` : 'tendenza non calcolabile';
    return { freccia: null, tendenza };
  }
  const erano =
    riga.delitti_confronto != null ? `, erano ${formatIstatCount(riga.delitti_confronto)}` : '';
  const segno = v > 0 ? '+' : v < 0 ? '−' : '';
  const pct = `${segno}${Math.abs(v)}% dal ${riga.anno_confronto}${erano}`;
  if (v > 0) return { freccia: '▲', tendenza: `in crescita (${pct})` };
  if (v < 0) return { freccia: '▼', tendenza: `in calo (${pct})` };
  return { freccia: null, tendenza: `stabile (${pct})` };
}

/**
 * Indicatore ISTAT accanto a un rischio (#347), in parti: `dati` è il testo prima della tendenza;
 * la `freccia` è decorativa (il template la rende `aria-hidden`, la `tendenza` dice già «in
 * crescita»/«in calo»), così i lettori di schermo non leggono «triangolo nero». Su una voce già
 * mostrata da un rischio precedente dello stesso gruppo `dati` è «stessa voce ISTAT: …» e
 * `tendenza` è `null`.
 */
export interface IstatIndicator {
  dati: string;
  freccia: '▲' | '▼' | null;
  tendenza: string | null;
}

/** Un rischio del Dettaglio col suo indicatore ISTAT (`null` se il rischio non ha dato). */
export interface IstatEntry {
  risk: RiskItem;
  indicator: IstatIndicator | null;
}

/**
 * Indicatori ISTAT dei rischi di un gruppo nel Dettaglio (#347), nell'ordine dato. Riga completa:
 * voce (con l'avviso se non coincide col rischio), delitti denunciati dell'ultimo anno, tasso del
 * luogo e tasso italiano così come pubblicati (mai il loro rapporto, D9) e tendenza 10 anni. Il
 * luogo sta nella nota del gruppo. `null` esattamente quando `istatWeight` è `null` (stesso
 * `istatMatch`), così indicatore e ordine non divergono. Quando più rischi condividono la stessa
 * voce solo la prima occorrenza (in ordine, non per adiacenza) è completa: le altre dicono
 * «stessa voce ISTAT: …» col proprio avviso, perché la corrispondenza è per rischio.
 */
export function withIstatIndicators(
  risks: RiskItem[],
  istat: IstatPoi | null | undefined,
): IstatEntry[] {
  const seen = new Set<string>();
  return risks.map((risk) => {
    const match = istatMatch(risk.hazard, istat);
    if (!match) return { risk, indicator: null };
    const { riga, collegamento } = match;
    const nota = istatCorrispondenzaNote(collegamento.corrispondenza);
    const voce = nota ? `${riga.voce_label} (${nota})` : riga.voce_label;
    if (seen.has(riga.voce)) {
      const dati = `stessa voce ISTAT: ${voce}`;
      return { risk, indicator: { dati, freccia: null, tendenza: null } };
    }
    seen.add(riga.voce);
    // `istatMatch` esclude già i conteggi assenti: `delitti` qui è sempre un numero.
    const delitti = `${formatIstatCount(riga.delitti ?? 0)} delitti denunciati nel ${riga.anno}`;
    const tasso = formatIstatRate(riga.tasso, riga.tasso_sotto_soglia);
    const italia = formatIstatRate(riga.tasso_italia, riga.tasso_italia_sotto_soglia);
    const dati = `${voce} · ${delitti} · ${tasso} ogni 100.000 ab. (Italia: ${italia})`;
    return { risk, indicator: { dati, ...istatTrend(riga) } };
  });
}

/**
 * Nota dei gruppi ordinati col dato ISTAT (#346): dice cosa si confronta (tassi del luogo e
 * italiano, non il numero di delitti), con luogo e anno; nessun valore (D9).
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
