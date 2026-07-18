import { Confidence, ConfidenceSummary, Poi, RiskModel, SourceTag } from '@core/models/models';

export interface ConfMeta {
  color: string;
  bg: string;
  dot: string;
  label: string;
}

export const CONF: Readonly<Record<'confermato' | 'plausibile' | 'speculativo', ConfMeta>> =
  Object.freeze({
    confermato: { color: '#1a7a40', bg: '#eef7f1', dot: '●', label: 'Confermato' },
    plausibile: { color: '#b8870a', bg: '#fbf4e4', dot: '◐', label: 'Plausibile' },
    speculativo: { color: '#c2620a', bg: '#fbeee2', dot: '○', label: 'Speculativo' },
  });

export const DIM_COLOR = '#b6b3a9';

/**
 * Colore + descrizione breve per i titoli di sezione dei tag fonte (Stato C "Fattori di rischio
 * · per fonte", Stato B narrativa strutturata per fonte): il colore ricalca deliberatamente
 * quello di `CONF` per il livello di confidence analogo (ONTOLOGIA↔confermato, CONTESTO↔plausibile,
 * SPECULATIVO↔speculativo) — stessa palette, un solo posto dove cambiarla.
 */
export const SRC_TAG_META: Readonly<Record<SourceTag, { color: string; description: string }>> =
  Object.freeze({
    ONTOLOGIA: { color: CONF.confermato.color, description: 'da ontologia formale' },
    CONTESTO: { color: CONF.plausibile.color, description: 'da contesto ambientale' },
    SPECULATIVO: { color: CONF.speculativo.color, description: 'inferenza non verificata' },
  });

const UNKNOWN_TAG_META = { color: CONF.speculativo.color, description: '' };

/**
 * Variante di `SRC_TAG_META` sicura per tag generici (`string`, non ristretti a `SourceTag`):
 * usata dai componenti (`DetailPanelComponent`, `NarrativeSheetComponent`) che iterano i gruppi
 * di `orderGroupsByTag`/`buildNarrativeSections`, dove un tag fuori contratto è ammesso e deve
 * degradare allo stesso fallback difensivo di `pinColor` invece di lanciare.
 */
export function srcTagMeta(tag: string): { color: string; description: string } {
  return (
    (SRC_TAG_META as Record<string, { color: string; description: string }>)[tag] ??
    UNKNOWN_TAG_META
  );
}

export function pinColor(level: string): string {
  return (CONF as Record<string, ConfMeta>)[level]?.color ?? DIM_COLOR;
}

export function deriveCoverage(
  confidenceSummary: Partial<ConfidenceSummary> | null | undefined,
  riskModels: RiskModel[] | null | undefined,
): { total: number; anchored: number } {
  const total = Object.values(confidenceSummary ?? {}).reduce(
    (acc, n) => acc + (Number(n) || 0),
    0,
  );
  const anchored = (riskModels ?? []).reduce(
    (acc, model) => acc + (model.risks ?? []).filter((r) => r.tag === 'ONTOLOGIA').length,
    0,
  );
  return { total, anchored };
}

export function coverageBadgeText(total: number, anchored: number): string {
  return `Copertura ${total} rischi · ${anchored} ancorati a ontologia`;
}

/**
 * Conteggio dei POI per il proprio livello di confidence (campo `Poi.confidence`, non i rischi
 * di `confidence_summary`): fonte sia dei chip filtro di `PoiPanelComponent` sia di quelli in
 * `HeaderControlsComponent` — un solo posto per la stessa regola di conteggio (DRY).
 */
export function poiConfidenceCounts(pois: Poi[] | null | undefined): Record<Confidence, number> {
  const counts: Record<Confidence, number> = { confermato: 0, plausibile: 0, speculativo: 0 };
  for (const poi of pois ?? []) counts[poi.confidence]++;
  return counts;
}

export function pinHTML(
  n: number,
  conf: string,
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
