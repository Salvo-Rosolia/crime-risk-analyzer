const mockLayerGroup = {
  addTo: jest.fn().mockReturnThis(),
  clearLayers: jest.fn(),
};

const mockMarker = {
  addTo: jest.fn().mockReturnThis(),
  bindPopup: jest.fn().mockReturnThis(),
  on: jest.fn(),
};

const mockCircle = {
  addTo: jest.fn().mockReturnThis(),
  setRadius: jest.fn(),
  setLatLng: jest.fn(),
  getRadius: jest.fn(() => 300),
  getLatLng: jest.fn(() => ({ lat: 41.9, lng: 12.5 })),
  remove: jest.fn(),
  on: jest.fn(),
};

const mapHandlers: Record<string, ((e: unknown) => void)[]> = {};
const mockMap = {
  setView: jest.fn().mockReturnThis(),
  flyToBounds: jest.fn(),
  flyTo: jest.fn(),
  remove: jest.fn(),
  addLayer: jest.fn(),
  distance: jest.fn(() => 500),
  on: jest.fn((event: string, handler: (e: unknown) => void) => {
    (mapHandlers[event] ??= []).push(handler);
  }),
};
function fireMap(event: string, payload: unknown): void {
  for (const h of mapHandlers[event] ?? []) h(payload);
}

jest.mock('leaflet', () => ({
  map: jest.fn(() => mockMap),
  tileLayer: jest.fn(() => ({ addTo: jest.fn() })),
  control: { zoom: jest.fn(() => ({ addTo: jest.fn() })) },
  latLngBounds: jest.fn((c: unknown) => ({ c })),
  layerGroup: jest.fn(() => mockLayerGroup),
  marker: jest.fn(() => mockMarker),
  circle: jest.fn(() => mockCircle),
  divIcon: jest.fn((opts: unknown) => ({ opts })),
}));

import { ComponentFixture, TestBed } from '@angular/core/testing';
import * as L from 'leaflet';
import { MapComponent } from './map.component';
import { CONF, DIM_COLOR } from '@core/confidence';
import type { AnalyzeResponse, Poi } from '@core/models/models';

function makePoi(overrides: Partial<Poi> = {}): Poi {
  return {
    id: '0',
    name: 'P0',
    terminus_class: 'Bank',
    lat: 41.9,
    lon: 12.5,
    confidence: 'verificato',
    sparql_path: null,
    terminus_label_it: 'Banca',
    terminus_label_en: 'Bank',
    ...overrides,
  };
}

function makeResp(pois: Poi[]): AnalyzeResponse {
  return {
    citta: 'Roma',
    zona_normalizzata: 'Centro',
    poi: pois,
    risk_models: [],
    narrativa: '',
    narrativa_fonti: { overview: '', ontologia: '', contesto: '', speculativo: '' },
    confidence_summary: { verificato: 0, da_confermare: 0 },
    llm_used: '',
    latenza_ms: 0,
    tokens_input: 0,
    tokens_output: 0,
    repro: { temperature: 0, seed: 0, prompt_hash: '' },
    cache_hit: false,
    fallback: false,
    contesto_hash: 'h-ctx',
  };
}

describe('MapComponent', () => {
  let fixture: ComponentFixture<MapComponent>;

  beforeEach(async () => {
    jest.clearAllMocks();
    for (const key of Object.keys(mapHandlers)) delete mapHandlers[key];
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
    fixture.componentRef.setInput('data', makeResp([makePoi()]));
    fixture.detectChanges();
    expect(mockMap.flyToBounds).toHaveBeenCalled();
  });

  it('no flyToBounds con data null', () => {
    fixture.componentRef.setInput('data', null);
    fixture.detectChanges();
    expect(mockMap.flyToBounds).not.toHaveBeenCalled();
  });

  describe('marker POI', () => {
    it('crea un marker numerato per ogni POI; ripulisce il layer a ogni redraw', () => {
      fixture.componentRef.setInput('data', makeResp([makePoi({ id: '0' }), makePoi({ id: '1' })]));
      fixture.detectChanges();
      expect(mockLayerGroup.clearLayers).toHaveBeenCalledTimes(1);
      expect(L.marker).toHaveBeenCalledTimes(2);
      expect(mockMarker.addTo).toHaveBeenCalledTimes(2);

      (L.marker as jest.Mock).mockClear();
      fixture.componentRef.setInput('data', makeResp([makePoi({ id: '0' })]));
      fixture.detectChanges();
      expect(mockLayerGroup.clearLayers).toHaveBeenCalledTimes(2);
      expect(L.marker).toHaveBeenCalledTimes(1);
    });

    it('posiziona il marker sulle coordinate lat/lon del POI', () => {
      fixture.componentRef.setInput('data', makeResp([makePoi({ lat: 41.89, lon: 12.49 })]));
      fixture.detectChanges();
      expect(L.marker).toHaveBeenCalledWith([41.89, 12.49], expect.anything());
    });

    it('colora il pin secondo la confidence del POI', () => {
      fixture.componentRef.setInput('data', makeResp([makePoi({ confidence: 'da_confermare' })]));
      fixture.detectChanges();
      const [opts] = (L.divIcon as jest.Mock).mock.calls.at(-1) as [{ html: string }];
      expect(opts.html).toContain(CONF.da_confermare.color);
    });

    it('#220: un POI fuori ontologia (confidence null) rende un pin neutro (DIM_COLOR), non un colore di confidence', () => {
      fixture.componentRef.setInput('data', makeResp([makePoi({ confidence: null })]));
      fixture.detectChanges();
      const [opts] = (L.divIcon as jest.Mock).mock.calls.at(-1) as [{ html: string }];
      expect(opts.html).toContain(DIM_COLOR);
    });

    it('applica lo stato dim (grigio, opacità ridotta) ai marker esclusi dal filtro attivo', () => {
      fixture.componentRef.setInput(
        'data',
        makeResp([
          makePoi({ id: '0', confidence: 'verificato' }),
          makePoi({ id: '1', confidence: 'da_confermare' }),
        ]),
      );
      fixture.componentRef.setInput('filter', 'verificato');
      fixture.detectChanges();
      const calls = (L.divIcon as jest.Mock).mock.calls as [{ html: string }][];
      expect(calls[0][0].html).not.toContain(DIM_COLOR);
      expect(calls[1][0].html).toContain(DIM_COLOR);
    });

    it('nessun dim quando il filtro è null (tutti i marker pieni)', () => {
      fixture.componentRef.setInput(
        'data',
        makeResp([
          makePoi({ id: '0', confidence: 'verificato' }),
          makePoi({ id: '1', confidence: 'da_confermare' }),
        ]),
      );
      fixture.detectChanges();
      const calls = (L.divIcon as jest.Mock).mock.calls as [{ html: string }][];
      expect(calls[0][0].html).not.toContain(DIM_COLOR);
      expect(calls[1][0].html).not.toContain(DIM_COLOR);
    });

    it('#220: un POI fuori ontologia (confidence null) è dim quando un filtro è attivo (non corrisponde ad alcuna categoria) e pieno senza filtro', () => {
      fixture.componentRef.setInput(
        'data',
        makeResp([
          makePoi({ id: '0', confidence: 'verificato' }),
          makePoi({ id: '1', confidence: null }),
        ]),
      );
      fixture.componentRef.setInput('filter', 'verificato');
      fixture.detectChanges();
      let calls = (L.divIcon as jest.Mock).mock.calls as [{ html: string }][];
      expect(calls[1][0].html).toContain('opacity:0.45');

      fixture.componentRef.setInput('filter', null);
      fixture.detectChanges();
      calls = (L.divIcon as jest.Mock).mock.calls as [{ html: string }][];
      expect(calls.at(-1)![0].html).toContain('opacity:1');
    });

    it('applica lo stato focus (34px, più grande) al marker selezionato', () => {
      const pois = [makePoi({ id: '0' }), makePoi({ id: '1' })];
      fixture.componentRef.setInput('data', makeResp(pois));
      fixture.componentRef.setInput('selectedId', '1');
      fixture.detectChanges();
      const calls = (L.divIcon as jest.Mock).mock.calls as [{ iconSize: [number, number] }][];
      expect(calls[0][0].iconSize).toEqual([26, 26]);
      expect(calls[1][0].iconSize).toEqual([34, 34]);
    });

    it('lega un popup a ogni marker con nome ed etichetta IT del POI', () => {
      fixture.componentRef.setInput(
        'data',
        makeResp([
          makePoi({ name: 'Stazione Termini', terminus_label_it: 'Stazione ferroviaria' }),
        ]),
      );
      fixture.detectChanges();
      expect(mockMarker.bindPopup).toHaveBeenCalledWith(
        expect.stringContaining('Stazione Termini'),
      );
      expect(mockMarker.bindPopup).toHaveBeenCalledWith(
        expect.stringContaining('Stazione ferroviaria'),
      );
    });

    it("click sul marker emette poiClick con l'id del POI", () => {
      fixture.componentRef.setInput('data', makeResp([makePoi({ id: 'poi-42' })]));
      fixture.detectChanges();

      const onClick = jest.fn();
      fixture.componentInstance.poiClick.subscribe(onClick);

      const [, handler] = (mockMarker.on as jest.Mock).mock.calls.at(-1) as [string, () => void];
      handler();

      expect(onClick).toHaveBeenCalledWith('poi-42');
    });
  });

  it('ngOnDestroy ripulisce i marker e rimuove la mappa (nessun leak di layer)', () => {
    fixture.componentRef.setInput('data', makeResp([makePoi()]));
    fixture.detectChanges();
    fixture.destroy();
    expect(mockLayerGroup.clearLayers).toHaveBeenCalled();
    expect(mockMap.remove).toHaveBeenCalled();
  });

  describe('disegno del cerchio', () => {
    it('un click in idle posiziona il centro ed entra in drawing-radius', () => {
      const spy = jest.fn();
      fixture.componentInstance.circleChange.subscribe(spy);
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      expect(L.circle).toHaveBeenCalledWith([41.9, 12.5], expect.objectContaining({ radius: 300 }));
    });

    it('un drag successivo al click aggiorna il raggio del cerchio live', () => {
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fireMap('mousemove', { latlng: { lat: 41.905, lng: 12.5 } });
      expect(mockCircle.setRadius).toHaveBeenCalled();
    });

    it('un secondo click conferma e emette circleChange con center+radiusM', () => {
      const spy = jest.fn();
      fixture.componentInstance.circleChange.subscribe(spy);
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fireMap('mousemove', { latlng: { lat: 41.905, lng: 12.5 } });
      fireMap('click', { latlng: { lat: 41.905, lng: 12.5 } });
      expect(spy).toHaveBeenCalledWith(
        expect.objectContaining({ lat: 41.9, lon: 12.5, radiusM: expect.any(Number) }),
      );
    });

    it('flyTo(lat, lon) chiama map.flyTo', () => {
      fixture.componentInstance.flyTo(41.8, 12.4);
      expect(mockMap.flyTo).toHaveBeenCalledWith([41.8, 12.4], expect.any(Number));
    });

    it('un click in ready riparte da un nuovo centro invece di riconfermare il vecchio', () => {
      const spy = jest.fn();
      fixture.componentInstance.circleChange.subscribe(spy);

      // idle -> drawing-radius -> ready: conferma il primo cerchio (centro A).
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fireMap('mousemove', { latlng: { lat: 41.905, lng: 12.5 } });
      fireMap('click', { latlng: { lat: 41.905, lng: 12.5 } });
      expect(spy).toHaveBeenCalledWith(expect.objectContaining({ lat: 41.9, lon: 12.5 }));
      spy.mockClear();

      // ready -> un ulteriore click NON riconferma il vecchio cerchio: resetta e invalida.
      fireMap('click', { latlng: { lat: 42.0, lng: 12.6 } });
      expect(spy).toHaveBeenCalledWith(null);
      spy.mockClear();

      // drawing-radius -> ready sul NUOVO centro (B), non il vecchio (A).
      fireMap('mousemove', { latlng: { lat: 42.005, lng: 12.6 } });
      fireMap('click', { latlng: { lat: 42.005, lng: 12.6 } });
      expect(spy).toHaveBeenCalledWith(expect.objectContaining({ lat: 42.0, lon: 12.6 }));
      expect(spy).not.toHaveBeenCalledWith(expect.objectContaining({ lat: 41.9, lon: 12.5 }));
    });

    it('il raggio è clampato al minimo (150m) quando il drag è più corto', () => {
      (mockMap.distance as jest.Mock).mockReturnValueOnce(50);
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fireMap('mousemove', { latlng: { lat: 41.9005, lng: 12.5 } });
      expect(mockCircle.setRadius).toHaveBeenCalledWith(150);
    });

    it('il raggio è clampato al massimo (3000m) quando il drag è più lungo', () => {
      (mockMap.distance as jest.Mock).mockReturnValueOnce(5000);
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fireMap('mousemove', { latlng: { lat: 41.95, lng: 12.5 } });
      expect(mockCircle.setRadius).toHaveBeenCalledWith(3000);
    });
  });
});
