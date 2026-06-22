import { ConfidenceSummary, RiskModel } from '@core/models/models';

export interface ConfMeta { color: string; bg: string; dot: string; label: string; }

export const CONF: Readonly<Record<'confermato' | 'plausibile' | 'speculativo', ConfMeta>> = Object.freeze({
  confermato: { color: '#1a7a40', bg: '#eef7f1', dot: '●', label: 'Confermato' },
  plausibile: { color: '#b8870a', bg: '#fbf4e4', dot: '◐', label: 'Plausibile' },
  speculativo: { color: '#c2620a', bg: '#fbeee2', dot: '○', label: 'Speculativo' },
});

export const DIM_COLOR = '#b6b3a9';

export function pinColor(level: string): string {
  return (CONF as Record<string, ConfMeta>)[level]?.color ?? DIM_COLOR;
}

export function deriveCoverage(
  confidenceSummary: Partial<ConfidenceSummary> | null | undefined,
  riskModels: RiskModel[] | null | undefined,
): { total: number; anchored: number } {
  const total = Object.values(confidenceSummary ?? {}).reduce((acc, n) => acc + (Number(n) || 0), 0);
  const anchored = (riskModels ?? []).reduce(
    (acc, model) => acc + (model.risks ?? []).filter(r => r.tag === 'ONTOLOGIA').length,
    0,
  );
  return { total, anchored };
}

export function coverageBadgeText(total: number, anchored: number): string {
  return `Copertura ${total} rischi · ${anchored} ancorati a ontologia`;
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
