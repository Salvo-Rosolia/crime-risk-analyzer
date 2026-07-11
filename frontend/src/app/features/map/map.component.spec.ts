const mockMap = {
  setView: jest.fn().mockReturnThis(),
  flyToBounds: jest.fn(),
  remove: jest.fn(),
  addLayer: jest.fn(),
};

jest.mock('leaflet', () => ({
  map: jest.fn(() => mockMap),
  tileLayer: jest.fn(() => ({ addTo: jest.fn() })),
  control: { zoom: jest.fn(() => ({ addTo: jest.fn() })) },
  latLngBounds: jest.fn((c: unknown) => ({ c })),
}));

import { ComponentFixture, TestBed } from '@angular/core/testing';
import * as L from 'leaflet';
import { MapComponent } from './map.component';
import type { AnalyzeResponse } from '@core/models/models';

function makeResp(pts: { lat: number; lon: number }[]): AnalyzeResponse {
  return {
    citta: 'Roma',
    zona_normalizzata: 'Centro',
    poi: pts.map((p, i) => ({
      id: String(i),
      name: 'P' + i,
      terminus_class: 'Bank',
      lat: p.lat,
      lon: p.lon,
      confidence: 'confermato',
      sparql_path: null,
      terminus_label_it: 'Banca',
      terminus_label_en: 'Bank',
    })),
    risk_models: [],
    narrativa: '',
    confidence_summary: { confermato: 0, plausibile: 0, speculativo: 0 },
    llm_used: '',
    latenza_ms: 0,
    tokens_input: 0,
    tokens_output: 0,
    repro: { temperature: 0, seed: 0, prompt_hash: '' },
    cache_hit: false,
    fallback: false,
  };
}

describe('MapComponent', () => {
  let fixture: ComponentFixture<MapComponent>;

  beforeEach(async () => {
    jest.clearAllMocks();
    await TestBed.configureTestingModule({ imports: [MapComponent] }).compileComponents();
    fixture = TestBed.createComponent(MapComponent);
    fixture.detectChanges();
    await fixture.whenStable();
  });

  it('init Leaflet + tile CARTO', () => {
    expect(L.map).toHaveBeenCalled();
    expect(L.tileLayer).toHaveBeenCalledWith(
      expect.stringContaining('basemaps.cartocdn.com'),
      expect.anything(),
    );
  });

  it('attribution copre dati POI (OSM/ODbL), geocoding (Nominatim) e tile (CARTO)', () => {
    const [, options] = (L.tileLayer as jest.Mock).mock.calls[0];
    const attribution = (options as { attribution: string }).attribution;
    expect(attribution).toEqual(expect.stringContaining('OpenStreetMap'));
    expect(attribution).toEqual(expect.stringContaining('ODbL'));
    expect(attribution).toEqual(expect.stringContaining('CARTO'));
    expect(attribution).toEqual(expect.stringContaining('Nominatim'));
  });

  it('attribution: i 4 termini sono link cliccabili verso le rispettive fonti', () => {
    const [, options] = (L.tileLayer as jest.Mock).mock.calls[0];
    const attribution = (options as { attribution: string }).attribution;
    expect(attribution).toEqual(expect.stringContaining('openstreetmap.org/copyright'));
    expect(attribution).toEqual(expect.stringContaining('opendatacommons.org'));
    expect(attribution).toEqual(expect.stringContaining('carto.com/attributions'));
    expect(attribution).toEqual(expect.stringContaining('nominatim.org'));
  });

  it('flyToBounds con POI', () => {
    fixture.componentRef.setInput('data', makeResp([{ lat: 41.9, lon: 12.5 }]));
    fixture.detectChanges();
    expect(mockMap.flyToBounds).toHaveBeenCalled();
  });

  it('no flyToBounds con data null', () => {
    fixture.componentRef.setInput('data', null);
    fixture.detectChanges();
    expect(mockMap.flyToBounds).not.toHaveBeenCalled();
  });
});
