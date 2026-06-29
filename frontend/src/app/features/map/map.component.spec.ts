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
    })),
    risk_models: [],
    narrativa: '',
    confidence_summary: { confermato: 0, plausibile: 0, speculativo: 0 },
    llm_used: '',
    latenza_ms: 0,
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
