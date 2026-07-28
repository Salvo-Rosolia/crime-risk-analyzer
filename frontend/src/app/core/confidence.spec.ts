import {
  CONF,
  DIM_COLOR,
  SPECULATIVE_TAG_COLOR,
  SRC_TAG_META,
  confMeta,
  coverageBadgeText,
  deriveCoverage,
  pinColor,
  pinHTML,
  poiConfidenceCounts,
  srcTagMeta,
} from '@core/confidence';
import { Poi, RiskModel } from '@core/models/models';

describe('confidence', () => {
  it('pinColor restituisce il colore del livello', () => {
    expect(pinColor('verificato')).toBe(CONF.verificato.color);
  });

  it('pinColor cade su DIM_COLOR per livelli ignoti', () => {
    expect(pinColor('boh')).toBe(DIM_COLOR);
  });

  it('confMeta: risolve i 2 livelli noti da CONF', () => {
    expect(confMeta('verificato')).toEqual(CONF.verificato);
    expect(confMeta('da_confermare')).toEqual(CONF.da_confermare);
  });

  it('confMeta: fallback difensivo per un livello fuori contratto (colore DIM_COLOR, dot/label placeholder)', () => {
    expect(confMeta('boh')).toEqual({
      color: DIM_COLOR,
      bg: DIM_COLOR,
      dot: '?',
      label: 'Sconosciuto',
    });
  });

  it('confMeta: un POI fuori ontologia (confidence null/undefined, #220) degrada allo stesso fallback — pin neutro', () => {
    expect(confMeta(null)).toEqual({
      color: DIM_COLOR,
      bg: DIM_COLOR,
      dot: '?',
      label: 'Sconosciuto',
    });
    expect(confMeta(undefined)).toEqual(confMeta(null));
  });

  it('deriveCoverage: total = somma summary, anchored = risk con tag ONTOLOGIA', () => {
    const riskModels: RiskModel[] = [
      {
        poi_id: '1',
        poi: 'A',
        risks: [
          {
            hazard: 'h1',
            confidence: 'verificato',
            tag: 'ONTOLOGIA',
            hazard_label_it: 'H1',
            hazard_label_en: 'H1',
          },
          {
            hazard: 'h2',
            confidence: 'da_confermare',
            tag: 'CONTESTO',
            hazard_label_it: 'H2',
            hazard_label_en: 'H2',
          },
        ],
      },
      {
        poi_id: '2',
        poi: 'B',
        risks: [
          {
            hazard: 'h3',
            confidence: 'verificato',
            tag: 'ONTOLOGIA',
            hazard_label_it: 'H3',
            hazard_label_en: 'H3',
          },
        ],
      },
    ];
    expect(deriveCoverage({ verificato: 2, da_confermare: 1 }, riskModels)).toEqual({
      total: 3,
      anchored: 2,
    });
  });

  it('deriveCoverage gestisce input null/undefined', () => {
    expect(deriveCoverage(undefined, undefined)).toEqual({ total: 0, anchored: 0 });
  });

  it('coverageBadgeText formatta il testo qualitativo', () => {
    expect(coverageBadgeText(4, 2)).toBe('Copertura 4 rischi · 2 ancorati a ontologia');
  });

  it('pinHTML in focus usa dimensione 34 e include il numero', () => {
    const html = pinHTML(3, 'verificato', { focus: true });
    expect(html).toContain('width:34px');
    expect(html).toContain('>3<');
  });

  it('pinHTML contiene il numero passato e il colore del livello di confidenza', () => {
    const html = pinHTML(7, 'da_confermare');
    expect(html).toContain('>7<');
    expect(html).toContain(CONF.da_confermare.color);
  });

  it('pinHTML in dim usa DIM_COLOR e opacità ridotta', () => {
    const html = pinHTML(1, 'verificato', { dim: true });
    expect(html).toContain(DIM_COLOR);
    expect(html).toContain('opacity:0.45');
  });

  it('pinHTML: un POI fuori ontologia (confidence null, #220) rende un pin neutro (DIM_COLOR), non dim di per sé', () => {
    const html = pinHTML(2, null);
    expect(html).toContain(DIM_COLOR);
    expect(html).toContain('opacity:1');
  });

  it('CONF è immutabile', () => {
    expect(Object.isFrozen(CONF)).toBe(true);
  });

  it('poiConfidenceCounts: conta i POI per il proprio livello di confidence (non i rischi)', () => {
    const poi = (id: string, confidence: Poi['confidence']): Poi => ({
      id,
      name: id,
      terminus_class: 'x',
      lat: 0,
      lon: 0,
      confidence,
      sparql_path: null,
      terminus_label_it: '',
      terminus_label_en: '',
    });
    const pois: Poi[] = [
      poi('1', 'verificato'),
      poi('2', 'verificato'),
      poi('3', 'da_confermare'),
      poi('4', null),
    ];
    expect(poiConfidenceCounts(pois)).toEqual({ verificato: 2, da_confermare: 1 });
  });

  it('poiConfidenceCounts: input null/undefined/vuoto → tutti i livelli a zero', () => {
    const zero = { verificato: 0, da_confermare: 0 };
    expect(poiConfidenceCounts(null)).toEqual(zero);
    expect(poiConfidenceCounts(undefined)).toEqual(zero);
    expect(poiConfidenceCounts([])).toEqual(zero);
  });

  it('SRC_TAG_META: colore allineato a CONF per il livello analogo, con breve descrizione; SPECULATIVO usa la costante dedicata', () => {
    expect(SRC_TAG_META.ONTOLOGIA.color).toBe(CONF.verificato.color);
    expect(SRC_TAG_META.CONTESTO.color).toBe(CONF.da_confermare.color);
    expect(SRC_TAG_META.SPECULATIVO.color).toBe(SPECULATIVE_TAG_COLOR);
    expect(SRC_TAG_META.ONTOLOGIA.description).toBe('da ontologia formale');
    expect(SRC_TAG_META.CONTESTO.description).toBe('da contesto ambientale');
    expect(SRC_TAG_META.SPECULATIVO.description).toBe('inferenza non verificata');
  });

  it('SRC_TAG_META è immutabile', () => {
    expect(Object.isFrozen(SRC_TAG_META)).toBe(true);
  });

  it('srcTagMeta: risolve i 3 tag noti da SRC_TAG_META', () => {
    expect(srcTagMeta('ONTOLOGIA')).toEqual(SRC_TAG_META.ONTOLOGIA);
    expect(srcTagMeta('CONTESTO')).toEqual(SRC_TAG_META.CONTESTO);
    expect(srcTagMeta('SPECULATIVO')).toEqual(SRC_TAG_META.SPECULATIVO);
  });

  it('srcTagMeta: fallback difensivo per tag fuori contratto (colore SPECULATIVE_TAG_COLOR, nessuna descrizione)', () => {
    expect(srcTagMeta('ALTRO')).toEqual({ color: SPECULATIVE_TAG_COLOR, description: '' });
  });
});
