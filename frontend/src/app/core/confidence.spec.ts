import { CONF, DIM_COLOR, coverageBadgeText, deriveCoverage, pinColor, pinHTML } from '@core/confidence';
import { RiskModel } from '@core/models/models';

describe('confidence', () => {
  it('pinColor restituisce il colore del livello', () => {
    expect(pinColor('confermato')).toBe(CONF.confermato.color);
  });

  it('pinColor cade su DIM_COLOR per livelli ignoti', () => {
    expect(pinColor('boh')).toBe(DIM_COLOR);
  });

  it('deriveCoverage: total = somma summary, anchored = risk con tag ONTOLOGIA', () => {
    const riskModels: RiskModel[] = [
      { poi: 'A', risks: [{ hazard: 'h1', confidence: 'confermato', tag: 'ONTOLOGIA' }, { hazard: 'h2', confidence: 'plausibile', tag: 'CONTESTO' }] },
      { poi: 'B', risks: [{ hazard: 'h3', confidence: 'confermato', tag: 'ONTOLOGIA' }] },
    ];
    expect(deriveCoverage({ confermato: 2, plausibile: 1, speculativo: 1 }, riskModels)).toEqual({ total: 4, anchored: 2 });
  });

  it('deriveCoverage gestisce input null/undefined', () => {
    expect(deriveCoverage(undefined, undefined)).toEqual({ total: 0, anchored: 0 });
  });

  it('coverageBadgeText formatta il testo qualitativo', () => {
    expect(coverageBadgeText(4, 2)).toBe('Copertura 4 rischi · 2 ancorati a ontologia');
  });

  it('pinHTML in focus usa dimensione 34 e include il numero', () => {
    const html = pinHTML(3, 'confermato', { focus: true });
    expect(html).toContain('width:34px');
    expect(html).toContain('>3<');
  });

  it('pinHTML contiene il numero passato e il colore del livello di confidenza', () => {
    const html = pinHTML(7, 'plausibile');
    expect(html).toContain('>7<');
    expect(html).toContain(CONF.plausibile.color);
  });

  it('pinHTML in dim usa DIM_COLOR e opacità ridotta', () => {
    const html = pinHTML(1, 'confermato', { dim: true });
    expect(html).toContain(DIM_COLOR);
    expect(html).toContain('opacity:0.45');
  });

  it('CONF è immutabile', () => {
    expect(Object.isFrozen(CONF)).toBe(true);
  });
});
