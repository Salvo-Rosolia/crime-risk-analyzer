import {
  CONF,
  DIM_COLOR,
  ISTAT_TAG_COLOR,
  NARRATIVE_TAG_META,
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
import { Poi } from '@core/models/models';

describe('confidence', () => {
  it('pinColor returns the color of the level', () => {
    expect(pinColor('verificato')).toBe(CONF.verificato.color);
  });

  it('pinColor falls back to DIM_COLOR for unknown levels', () => {
    expect(pinColor('boh')).toBe(DIM_COLOR);
  });

  it('confMeta: resolves the 2 known levels from CONF', () => {
    expect(confMeta('verificato')).toEqual(CONF.verificato);
    expect(confMeta('da_confermare')).toEqual(CONF.da_confermare);
  });

  it('confMeta: defensive fallback for an out-of-contract level (DIM_COLOR color, placeholder dot/label)', () => {
    expect(confMeta('boh')).toEqual({
      color: DIM_COLOR,
      bg: DIM_COLOR,
      dot: '?',
      label: 'Sconosciuto',
    });
  });

  it('confMeta: a POI outside the ontology (confidence null/undefined, #220) degrades to the same fallback — neutral pin', () => {
    expect(confMeta(null)).toEqual({
      color: DIM_COLOR,
      bg: DIM_COLOR,
      dot: '?',
      label: 'Sconosciuto',
    });
    expect(confMeta(undefined)).toEqual(confMeta(null));
  });

  describe('deriveCoverage', () => {
    const basePoiFixture: Poi = {
      id: '1',
      name: 'Test POI',
      ontology_class: 'x',
      lat: 0,
      lon: 0,
      confidence: 'verificato',
      sparql_path: null,
      ontology_label_it: '',
      ontology_label_en: '',
    };

    it('counts as anchored only the POIs with non-null confidence', () => {
      const poi: Poi[] = [
        { ...basePoiFixture, confidence: 'verificato' },
        { ...basePoiFixture, confidence: 'da_confermare' },
        { ...basePoiFixture, confidence: null },
      ];
      expect(deriveCoverage(poi)).toEqual({ total: 3, anchored: 2 });
    });

    it('handles an empty or missing list', () => {
      expect(deriveCoverage(null)).toEqual({ total: 0, anchored: 0 });
      expect(deriveCoverage([])).toEqual({ total: 0, anchored: 0 });
    });
  });

  describe('coverageBadgeText', () => {
    it('formats "Copertura: X POI su Y coperti da ontologia"', () => {
      expect(coverageBadgeText(3, 2)).toBe('Copertura: 2 POI su 3 coperti da ontologia');
    });
  });

  it('pinHTML in focus uses size 34 and includes the number', () => {
    const html = pinHTML(3, 'verificato', { focus: true });
    expect(html).toContain('width:34px');
    expect(html).toContain('>3<');
  });

  it('pinHTML contains the passed number and the color of the confidence level', () => {
    const html = pinHTML(7, 'da_confermare');
    expect(html).toContain('>7<');
    expect(html).toContain(CONF.da_confermare.color);
  });

  it('pinHTML in dim uses DIM_COLOR and reduced opacity', () => {
    const html = pinHTML(1, 'verificato', { dim: true });
    expect(html).toContain(DIM_COLOR);
    expect(html).toContain('opacity:0.45');
  });

  it('pinHTML: a POI outside the ontology (confidence null, #220) renders a neutral pin (DIM_COLOR), not dim by itself', () => {
    const html = pinHTML(2, null);
    expect(html).toContain(DIM_COLOR);
    expect(html).toContain('opacity:1');
  });

  it('CONF is immutable', () => {
    expect(Object.isFrozen(CONF)).toBe(true);
  });

  it('poiConfidenceCounts: counts the POIs by their own confidence level (not the risks)', () => {
    const poi = (id: string, confidence: Poi['confidence']): Poi => ({
      id,
      name: id,
      ontology_class: 'x',
      lat: 0,
      lon: 0,
      confidence,
      sparql_path: null,
      ontology_label_it: '',
      ontology_label_en: '',
    });
    const pois: Poi[] = [
      poi('1', 'verificato'),
      poi('2', 'verificato'),
      poi('3', 'da_confermare'),
      poi('4', null),
    ];
    expect(poiConfidenceCounts(pois)).toEqual({ verificato: 2, da_confermare: 1 });
  });

  it('poiConfidenceCounts: null/undefined/empty input → all levels at zero', () => {
    const zero = { verificato: 0, da_confermare: 0 };
    expect(poiConfidenceCounts(null)).toEqual(zero);
    expect(poiConfidenceCounts(undefined)).toEqual(zero);
    expect(poiConfidenceCounts([])).toEqual(zero);
  });

  it('SRC_TAG_META: color aligned with CONF for the analogous level, with short description; SPECULATIVO uses the dedicated constant', () => {
    expect(SRC_TAG_META.ONTOLOGIA.color).toBe(CONF.verificato.color);
    expect(SRC_TAG_META.CONTESTO.color).toBe(CONF.da_confermare.color);
    expect(SRC_TAG_META.SPECULATIVO.color).toBe(SPECULATIVE_TAG_COLOR);
    expect(SRC_TAG_META.ONTOLOGIA.description).toBe('da ontologia formale');
    expect(SRC_TAG_META.CONTESTO.description).toBe('da contesto ambientale');
    expect(SRC_TAG_META.SPECULATIVO.description).toBe('inferenza non verificata');
  });

  it('SRC_TAG_META is immutable', () => {
    expect(Object.isFrozen(SRC_TAG_META)).toBe(true);
  });

  it('srcTagMeta: resolves the 3 known tags from SRC_TAG_META', () => {
    expect(srcTagMeta('ONTOLOGIA')).toEqual(SRC_TAG_META.ONTOLOGIA);
    expect(srcTagMeta('CONTESTO')).toEqual(SRC_TAG_META.CONTESTO);
    expect(srcTagMeta('SPECULATIVO')).toEqual(SRC_TAG_META.SPECULATIVO);
  });

  it('srcTagMeta: defensive fallback for an out-of-contract tag (SPECULATIVE_TAG_COLOR color, no description)', () => {
    expect(srcTagMeta('ALTRO')).toEqual({ color: SPECULATIVE_TAG_COLOR, description: '' });
  });

  it('#345: the ISTAT source has its own color and description, only among the narrative sources', () => {
    expect(srcTagMeta('ISTAT')).toEqual(NARRATIVE_TAG_META.ISTAT);
    expect(NARRATIVE_TAG_META.ISTAT.color).toBe(ISTAT_TAG_COLOR);
    expect(NARRATIVE_TAG_META.ISTAT.description).toBe('dati ISTAT del comune o della provincia');
    expect(Object.keys(SRC_TAG_META)).toEqual(['ONTOLOGIA', 'CONTESTO', 'SPECULATIVO']);
    expect(Object.isFrozen(NARRATIVE_TAG_META)).toBe(true);
  });
});
