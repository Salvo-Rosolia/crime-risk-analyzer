const mockLayerGroup = {
  addTo: jest.fn().mockReturnThis(),
  clearLayers: jest.fn(),
};

const mockMarker = {
  addTo: jest.fn().mockReturnThis(),
  bindPopup: jest.fn().mockReturnThis(),
  on: jest.fn(),
};

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
  layerGroup: jest.fn(() => mockLayerGroup),
  marker: jest.fn(() => mockMarker),
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
    confidence: 'confermato',
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
      fixture.componentRef.setInput('data', makeResp([makePoi({ confidence: 'speculativo' })]));
      fixture.detectChanges();
      const [opts] = (L.divIcon as jest.Mock).mock.calls.at(-1) as [{ html: string }];
      expect(opts.html).toContain(CONF.speculativo.color);
    });

    it('applica lo stato dim (grigio, opacità ridotta) ai marker esclusi dal filtro attivo', () => {
      fixture.componentRef.setInput(
        'data',
        makeResp([
          makePoi({ id: '0', confidence: 'confermato' }),
          makePoi({ id: '1', confidence: 'speculativo' }),
        ]),
      );
      fixture.componentRef.setInput('filter', 'confermato');
      fixture.detectChanges();
      const calls = (L.divIcon as jest.Mock).mock.calls as [{ html: string }][];
      expect(calls[0][0].html).not.toContain(DIM_COLOR);
      expect(calls[1][0].html).toContain(DIM_COLOR);
    });

    it('nessun dim quando il filtro è null (tutti i marker pieni)', () => {
      fixture.componentRef.setInput(
        'data',
        makeResp([
          makePoi({ id: '0', confidence: 'confermato' }),
          makePoi({ id: '1', confidence: 'speculativo' }),
        ]),
      );
      fixture.detectChanges();
      const calls = (L.divIcon as jest.Mock).mock.calls as [{ html: string }][];
      expect(calls[0][0].html).not.toContain(DIM_COLOR);
      expect(calls[1][0].html).not.toContain(DIM_COLOR);
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
});
