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

  it('Leaflet init + standard OpenStreetMap tiles', () => {
    expect(L.map).toHaveBeenCalled();
    expect(L.tileLayer).toHaveBeenCalledWith(
      expect.stringContaining('tile.openstreetmap.org'),
      expect.anything(),
    );
  });

  /*
   * The basemap no longer goes through CARTO: `basemaps.cartocdn.com` started requiring an API
   * key and serves an "API KEY REQUIRED" placeholder PNG with HTTP 200 (~2 KB instead of ~14 KB), so
   * neither Leaflet nor the console reported an error — the map simply came out empty.
   * This test guards against going back by distraction: a URL with a key would fail
   * the same way, silently.
   */
  it('no residual dependency on CARTO (neither URL nor attribution)', () => {
    const [url, options] = (L.tileLayer as jest.Mock).mock.calls[0];
    const attribution = (options as { attribution: string }).attribution;
    expect(url).not.toEqual(expect.stringContaining('carto'));
    expect(attribution).not.toEqual(expect.stringContaining('CARTO'));
  });

  it('attribution covers POI data and tiles (OSM/ODbL) and geocoding (Nominatim)', () => {
    const [, options] = (L.tileLayer as jest.Mock).mock.calls[0];
    const attribution = (options as { attribution: string }).attribution;
    expect(attribution).toEqual(expect.stringContaining('OpenStreetMap'));
    expect(attribution).toEqual(expect.stringContaining('ODbL'));
    expect(attribution).toEqual(expect.stringContaining('Nominatim'));
  });

  it('attribution: the 3 terms are clickable links to the respective sources', () => {
    const [, options] = (L.tileLayer as jest.Mock).mock.calls[0];
    const attribution = (options as { attribution: string }).attribution;
    expect(attribution).toEqual(expect.stringContaining('openstreetmap.org/copyright'));
    expect(attribution).toEqual(expect.stringContaining('opendatacommons.org'));
    expect(attribution).toEqual(expect.stringContaining('nominatim.org'));
  });

  it('flyToBounds with POIs', () => {
    fixture.componentRef.setInput('data', makeResp([makePoi()]));
    fixture.detectChanges();
    expect(mockMap.flyToBounds).toHaveBeenCalled();
  });

  it('no flyToBounds with null data', () => {
    fixture.componentRef.setInput('data', null);
    fixture.detectChanges();
    expect(mockMap.flyToBounds).not.toHaveBeenCalled();
  });

  describe('marker POI', () => {
    it('creates a numbered marker for each POI; cleans the layer at every redraw', () => {
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

    it('places the marker on the lat/lon coordinates of the POI', () => {
      fixture.componentRef.setInput('data', makeResp([makePoi({ lat: 41.89, lon: 12.49 })]));
      fixture.detectChanges();
      expect(L.marker).toHaveBeenCalledWith([41.89, 12.49], expect.anything());
    });

    it('colors the pin according to the POI confidence', () => {
      fixture.componentRef.setInput('data', makeResp([makePoi({ confidence: 'da_confermare' })]));
      fixture.detectChanges();
      const [opts] = (L.divIcon as jest.Mock).mock.calls.at(-1) as [{ html: string }];
      expect(opts.html).toContain(CONF.da_confermare.color);
    });

    it('#220: a POI outside the ontology (confidence null) renders a neutral pin (DIM_COLOR), not a confidence color', () => {
      fixture.componentRef.setInput('data', makeResp([makePoi({ confidence: null })]));
      fixture.detectChanges();
      const [opts] = (L.divIcon as jest.Mock).mock.calls.at(-1) as [{ html: string }];
      expect(opts.html).toContain(DIM_COLOR);
    });

    it('applies the dim state (gray, reduced opacity) to the markers excluded by the active filter', () => {
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

    it('no dim when the filter is null (all markers full)', () => {
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

    it('#220: a POI outside the ontology (confidence null) is dim when a filter is active (it matches no category) and full without a filter', () => {
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

    it('applies the focus state (34px, larger) to the selected marker', () => {
      const pois = [makePoi({ id: '0' }), makePoi({ id: '1' })];
      fixture.componentRef.setInput('data', makeResp(pois));
      fixture.componentRef.setInput('selectedId', '1');
      fixture.detectChanges();
      const calls = (L.divIcon as jest.Mock).mock.calls as [{ iconSize: [number, number] }][];
      expect(calls[0][0].iconSize).toEqual([26, 26]);
      expect(calls[1][0].iconSize).toEqual([34, 34]);
    });

    it('binds a popup to each marker with the POI name and IT label', () => {
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

    it('click on the marker emits poiClick with the POI id', () => {
      fixture.componentRef.setInput('data', makeResp([makePoi({ id: 'poi-42' })]));
      fixture.detectChanges();

      const onClick = jest.fn();
      fixture.componentInstance.poiClick.subscribe(onClick);

      const [, handler] = (mockMarker.on as jest.Mock).mock.calls.at(-1) as [string, () => void];
      handler();

      expect(onClick).toHaveBeenCalledWith('poi-42');
    });
  });

  it('ngOnDestroy cleans the markers and removes the map (no layer leak)', () => {
    fixture.componentRef.setInput('data', makeResp([makePoi()]));
    fixture.detectChanges();
    fixture.destroy();
    expect(mockLayerGroup.clearLayers).toHaveBeenCalled();
    expect(mockMap.remove).toHaveBeenCalled();
  });

  describe('circle drawing', () => {
    it('a click in idle places the center and enters drawing-radius', () => {
      const spy = jest.fn();
      fixture.componentInstance.circleChange.subscribe(spy);
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      expect(L.circle).toHaveBeenCalledWith([41.9, 12.5], expect.objectContaining({ radius: 300 }));
    });

    it('a drag after the click updates the live circle radius', () => {
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fireMap('mousemove', { latlng: { lat: 41.905, lng: 12.5 } });
      expect(mockCircle.setRadius).toHaveBeenCalled();
    });

    it('a second click confirms and emits circleChange with center+radiusM', () => {
      const spy = jest.fn();
      fixture.componentInstance.circleChange.subscribe(spy);
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fireMap('mousemove', { latlng: { lat: 41.905, lng: 12.5 } });
      fireMap('click', { latlng: { lat: 41.905, lng: 12.5 } });
      expect(spy).toHaveBeenCalledWith(
        expect.objectContaining({ lat: 41.9, lon: 12.5, radiusM: expect.any(Number) }),
      );
    });

    it('flyTo(lat, lon) calls map.flyTo', () => {
      fixture.componentInstance.flyTo(41.8, 12.4);
      expect(mockMap.flyTo).toHaveBeenCalledWith([41.8, 12.4], expect.any(Number));
    });

    it('a click in ready restarts from a new center instead of reconfirming the old one', () => {
      const spy = jest.fn();
      fixture.componentInstance.circleChange.subscribe(spy);

      // idle -> drawing-radius -> ready: confirms the first circle (center A).
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fireMap('mousemove', { latlng: { lat: 41.905, lng: 12.5 } });
      fireMap('click', { latlng: { lat: 41.905, lng: 12.5 } });
      expect(spy).toHaveBeenCalledWith(expect.objectContaining({ lat: 41.9, lon: 12.5 }));
      spy.mockClear();

      // ready -> a further click does NOT reconfirm the old circle: it resets and invalidates.
      fireMap('click', { latlng: { lat: 42.0, lng: 12.6 } });
      expect(spy).toHaveBeenCalledWith(null);
      spy.mockClear();

      // drawing-radius -> ready on the NEW center (B), not the old one (A).
      fireMap('mousemove', { latlng: { lat: 42.005, lng: 12.6 } });
      fireMap('click', { latlng: { lat: 42.005, lng: 12.6 } });
      expect(spy).toHaveBeenCalledWith(expect.objectContaining({ lat: 42.0, lon: 12.6 }));
      expect(spy).not.toHaveBeenCalledWith(expect.objectContaining({ lat: 41.9, lon: 12.5 }));
    });

    it('the radius is clamped to the minimum (150m) when the drag is shorter', () => {
      (mockMap.distance as jest.Mock).mockReturnValueOnce(50);
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fireMap('mousemove', { latlng: { lat: 41.9005, lng: 12.5 } });
      expect(mockCircle.setRadius).toHaveBeenCalledWith(150);
    });

    it('the radius is clamped to the maximum (3000m) when the drag is longer', () => {
      (mockMap.distance as jest.Mock).mockReturnValueOnce(5000);
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fireMap('mousemove', { latlng: { lat: 41.95, lng: 12.5 } });
      expect(mockCircle.setRadius).toHaveBeenCalledWith(3000);
    });
  });

  describe('numeric radius input (#318 D2: via keyboard/screen reader, not only the drag)', () => {
    function radiusInput(): HTMLInputElement | null {
      return fixture.nativeElement.querySelector('#cra-radius-input');
    }

    it('absent in idle (no circle drawn yet)', () => {
      expect(radiusInput()).toBeNull();
    });

    it('appears in drawing-radius (after the first click) with the default radius', () => {
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fixture.detectChanges();
      const input = radiusInput();
      expect(input).toBeTruthy();
      expect(input!.value).toBe('300');
    });

    it('stays visible in ready (after the confirmation)', () => {
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fireMap('mousemove', { latlng: { lat: 41.905, lng: 12.5 } });
      fireMap('click', { latlng: { lat: 41.905, lng: 12.5 } });
      fixture.detectChanges();
      expect(radiusInput()).toBeTruthy();
    });

    it('a drag updates the value shown by the input (map -> input synchronization)', () => {
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fixture.detectChanges();
      (mockMap.distance as jest.Mock).mockReturnValueOnce(900);
      fireMap('mousemove', { latlng: { lat: 41.905, lng: 12.5 } });
      fixture.detectChanges();
      expect(radiusInput()!.value).toBe('900');
    });

    it('typing a value immediately updates the radius of the drawn circle (input -> map synchronization)', () => {
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fixture.detectChanges();
      const input = radiusInput()!;
      input.value = '900';
      input.dispatchEvent(new Event('input'));
      expect(mockCircle.setRadius).toHaveBeenCalledWith(900);
    });

    it('typing a value while the circle is "ready" re-emits circleChange with the new radius (the shell stays in sync)', () => {
      const spy = jest.fn();
      fixture.componentInstance.circleChange.subscribe(spy);
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fireMap('mousemove', { latlng: { lat: 41.905, lng: 12.5 } });
      fireMap('click', { latlng: { lat: 41.905, lng: 12.5 } });
      fixture.detectChanges();
      spy.mockClear();

      const input = radiusInput()!;
      input.value = '900';
      input.dispatchEvent(new Event('input'));

      expect(spy).toHaveBeenCalledWith({ lat: 41.9, lon: 12.5, radiusM: 900 });
    });

    it('typing a value while the circle is still "drawing-radius" (not confirmed) does NOT emit circleChange', () => {
      const spy = jest.fn();
      fixture.componentInstance.circleChange.subscribe(spy);
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fixture.detectChanges();

      const input = radiusInput()!;
      input.value = '900';
      input.dispatchEvent(new Event('input'));

      expect(spy).not.toHaveBeenCalled();
    });

    it('typing "800" character by character really reaches it: the field shows "800" and the circle is at radius 800 (no clamp-and-rewrite at every key)', () => {
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fixture.detectChanges();
      const input = radiusInput()!;

      input.value = '8';
      input.dispatchEvent(new Event('input'));
      fixture.detectChanges();
      expect(input.value).toBe('8');

      input.value = '80';
      input.dispatchEvent(new Event('input'));
      fixture.detectChanges();
      expect(input.value).toBe('80');

      input.value = '800';
      input.dispatchEvent(new Event('input'));
      fixture.detectChanges();
      expect(input.value).toBe('800');
      expect(mockCircle.setRadius).toHaveBeenLastCalledWith(800);
    });

    it('a value typed below the minimum stays visible as-is while typing (input): only the map already sees the clamp as a preview', () => {
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fixture.detectChanges();
      const input = radiusInput()!;
      input.value = '10';
      input.dispatchEvent(new Event('input'));
      fixture.detectChanges();

      expect(mockCircle.setRadius).toHaveBeenCalledWith(150);
      expect(input.value).toBe('10');
    });

    it('a value typed below the minimum (150m) is clamped AND rewritten in the field only on confirmation (change event: blur/enter)', () => {
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fixture.detectChanges();
      const input = radiusInput()!;
      input.value = '10';
      input.dispatchEvent(new Event('input'));
      fixture.detectChanges();

      input.dispatchEvent(new Event('change'));
      fixture.detectChanges();

      expect(mockCircle.setRadius).toHaveBeenLastCalledWith(150);
      expect(input.value).toBe('150');
    });

    it('a value typed above the maximum stays visible as-is while typing (input): only the map already sees the clamp as a preview', () => {
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fixture.detectChanges();
      const input = radiusInput()!;
      input.value = '9999';
      input.dispatchEvent(new Event('input'));
      fixture.detectChanges();

      expect(mockCircle.setRadius).toHaveBeenCalledWith(3000);
      expect(input.value).toBe('9999');
    });

    it('a value typed above the maximum (3000m) is clamped AND rewritten in the field only on confirmation (change event: blur/enter)', () => {
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fixture.detectChanges();
      const input = radiusInput()!;
      input.value = '9999';
      input.dispatchEvent(new Event('input'));
      fixture.detectChanges();

      input.dispatchEvent(new Event('change'));
      fixture.detectChanges();

      expect(mockCircle.setRadius).toHaveBeenLastCalledWith(3000);
      expect(input.value).toBe('3000');
    });

    it('emptying the field to rewrite it from scratch does not make it jump to 150 mid-edit (no clamp until confirmed)', () => {
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fireMap('mousemove', { latlng: { lat: 41.905, lng: 12.5 } });
      fixture.detectChanges();
      const input = radiusInput()!;

      input.value = '';
      input.dispatchEvent(new Event('input'));
      fixture.detectChanges();

      expect(input.value).toBe('');
    });

    it("emptying the field completely and confirming (change) restores the last valid radius, does not jump to the minimum 150 (review finding fix: Number('')===0 is finite, not NaN)", () => {
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fixture.detectChanges();
      const input = radiusInput()!;

      // First confirm a radius that is valid and different from both the default (300) and the minimum (150),
      // so an accidental restore to one of those two values would make the assert below fail.
      input.value = '800';
      input.dispatchEvent(new Event('input'));
      fixture.detectChanges();
      input.dispatchEvent(new Event('change'));
      fixture.detectChanges();
      expect(input.value).toBe('800');

      input.value = '';
      input.dispatchEvent(new Event('input'));
      fixture.detectChanges();
      input.dispatchEvent(new Event('change'));
      fixture.detectChanges();

      expect(mockCircle.setRadius).toHaveBeenLastCalledWith(800);
      expect(input.value).toBe('800');
    });

    it('the change (confirmation) re-emits circleChange with the clamped value when the circle is "ready"', () => {
      const spy = jest.fn();
      fixture.componentInstance.circleChange.subscribe(spy);
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fireMap('mousemove', { latlng: { lat: 41.905, lng: 12.5 } });
      fireMap('click', { latlng: { lat: 41.905, lng: 12.5 } });
      fixture.detectChanges();
      spy.mockClear();

      const input = radiusInput()!;
      input.value = '9999';
      input.dispatchEvent(new Event('input'));
      spy.mockClear();
      input.dispatchEvent(new Event('change'));

      expect(spy).toHaveBeenCalledWith({ lat: 41.9, lon: 12.5, radiusM: 3000 });
    });
  });

  describe('clearCircle() (#318, review finding I5: RESET must also clear the drawing on the map)', () => {
    it('removes the drawn circle from the map and does not emit any circleChange', () => {
      const spy = jest.fn();
      fixture.componentInstance.circleChange.subscribe(spy);
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fireMap('mousemove', { latlng: { lat: 41.905, lng: 12.5 } });
      fireMap('click', { latlng: { lat: 41.905, lng: 12.5 } });
      spy.mockClear();

      fixture.componentInstance.clearCircle();

      expect(mockCircle.remove).toHaveBeenCalled();
      expect(spy).not.toHaveBeenCalled();
    });

    it('hides the numeric radius input again', () => {
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('#cra-radius-input')).toBeTruthy();

      fixture.componentInstance.clearCircle();
      fixture.detectChanges();

      expect(fixture.nativeElement.querySelector('#cra-radius-input')).toBeNull();
    });

    it('brings the state back to a genuine IDLE: a later click opens a new drawing without the "ready" reset (no null emitted before)', () => {
      const spy = jest.fn();
      fixture.componentInstance.circleChange.subscribe(spy);
      fireMap('click', { latlng: { lat: 41.9, lng: 12.5 } });
      fireMap('mousemove', { latlng: { lat: 41.905, lng: 12.5 } });
      fireMap('click', { latlng: { lat: 41.905, lng: 12.5 } }); // -> ready
      spy.mockClear();

      fixture.componentInstance.clearCircle();
      (L.circle as jest.Mock).mockClear();

      // If the state had stayed "ready" instead of "idle", this click would first emit a
      // circleChange(null) reset (behavior of the ready->new center transition, see
      // "a click in ready restarts from a new center" above) — here it must NOT happen.
      fireMap('click', { latlng: { lat: 42.0, lng: 12.6 } });

      expect(spy).not.toHaveBeenCalledWith(null);
      expect(L.circle).toHaveBeenCalledWith([42.0, 12.6], expect.objectContaining({ radius: 300 }));
    });
  });
});
