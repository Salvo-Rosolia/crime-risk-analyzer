jest.mock('leaflet', () => ({
  map: jest.fn(() => ({
    setView: jest.fn().mockReturnThis(),
    flyToBounds: jest.fn(),
    remove: jest.fn(),
  })),
  tileLayer: jest.fn(() => ({ addTo: jest.fn() })),
  control: { zoom: jest.fn(() => ({ addTo: jest.fn() })) },
  latLngBounds: jest.fn(() => ({})),
  layerGroup: jest.fn(() => ({ addTo: jest.fn().mockReturnThis(), clearLayers: jest.fn() })),
  marker: jest.fn(() => ({
    addTo: jest.fn().mockReturnThis(),
    bindPopup: jest.fn().mockReturnThis(),
    on: jest.fn(),
  })),
  divIcon: jest.fn(() => ({})),
}));

import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { sessionInterceptor } from '@core/api/session.interceptor';
import { ApiService } from '@core/api/api.service';
import { SourcesStore } from '@core/state/sources.store';
import { StateStore } from '@core/state/state.store';
import type { AnalyzeResponse, SourcesStatus } from '@core/models/models';
import { App } from './app';

const EXAMPLE: SourcesStatus = {
  stato: 'attivo',
  source_set_id: 'example',
  scade_tra_secondi: 900,
  set: {
    kind: 'example',
    classi: 3,
    selettori_osm: 5,
    versione_dati: null,
    luoghi: [],
    avvisi: [],
  },
};

describe('App shell - sources (#419)', () => {
  let api: Record<string, jest.Mock>;

  beforeEach(async () => {
    api = {
      cities: jest.fn().mockResolvedValue([]),
      poiTypes: jest.fn().mockResolvedValue([]),
      sourcesStatus: jest.fn().mockResolvedValue(EXAMPLE),
      useExampleSources: jest.fn().mockResolvedValue(EXAMPLE),
      resetSources: jest.fn().mockResolvedValue({
        stato: 'default',
        scade_tra_secondi: null,
        set: null,
        source_set_id: 'default',
      }),
      templateUrl: jest.fn((n: string) => `/sources/templates/${n}`),
    };
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [{ provide: ApiService, useValue: api }],
    }).compileComponents();
  });

  it('the indicator is in the header, always, and reflects the state read at startup', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();
    f.detectChanges();
    const ind = f.nativeElement.querySelector('header cra-sources-indicator button');
    expect(ind.textContent).toContain('Fonti: Esempio');
  });

  it('without a backend the indicator says Predefinite', async () => {
    api['sourcesStatus'].mockRejectedValue(new Error('down'));
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();
    f.detectChanges();
    expect(f.nativeElement.querySelector('cra-sources-indicator').textContent).toContain(
      'Predefinite',
    );
  });

  it('the click on the indicator opens the page, Chiudi closes it', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();
    expect(f.nativeElement.querySelector('cra-sources-page')).toBeNull();
    f.nativeElement.querySelector('cra-sources-indicator button').click();
    f.detectChanges();
    expect(f.nativeElement.querySelector('cra-sources-page')).not.toBeNull();
    f.nativeElement.querySelector('button[aria-label="Chiudi"]').click();
    f.detectChanges();
    expect(f.nativeElement.querySelector('cra-sources-page')).toBeNull();
  });

  const DEFAULT: SourcesStatus = {
    stato: 'default',
    scade_tra_secondi: null,
    set: null,
    source_set_id: 'default',
  };
  const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

  async function startLoading(f: ReturnType<typeof TestBed.createComponent<App>>) {
    const state = TestBed.inject(StateStore);
    f.detectChanges();
    await f.whenStable();
    state.dispatch({
      type: 'ANALYZE',
      area: { kind: 'zone', city: 'Roma', zone: 'Centro' },
      pipeline: 'full',
    });
    expect(state.screen()).toBe('LOADING');
    return state;
  }

  function clickInPage(f: ReturnType<typeof TestBed.createComponent<App>>, text: string): void {
    TestBed.inject(SourcesStore).openPage();
    f.detectChanges();
    Array.from<HTMLButtonElement>(f.nativeElement.querySelectorAll('cra-sources-page button'))
      .find((b) => b.textContent?.includes(text))!
      .click();
  }

  // No `whenStable` after ANALYZE: in LOADING the cosmetic overlay keeps pending timers.

  it('really changing the sources (example -> default) clears the results', async () => {
    const f = TestBed.createComponent(App);
    const state = await startLoading(f);
    clickInPage(f, 'Torna al default');
    await tick();
    f.detectChanges();
    expect(api['resetSources']).toHaveBeenCalled();
    expect(state.screen()).toBe('INPUT');
  });

  it('Torna al default with sources already at default clears NOTHING', async () => {
    api['sourcesStatus'].mockResolvedValue(DEFAULT);
    const f = TestBed.createComponent(App);
    const state = await startLoading(f);
    clickInPage(f, 'Torna al default');
    await tick();
    expect(api['resetSources']).toHaveBeenCalled();
    expect(state.screen()).toBe('LOADING');
  });

  it("Usa l'esempio with the example already active clears NOTHING", async () => {
    const f = TestBed.createComponent(App);
    const state = await startLoading(f);
    clickInPage(f, "Usa l'esempio");
    await tick();
    expect(api['useExampleSources']).toHaveBeenCalled();
    expect(state.screen()).toBe('LOADING');
  });

  it('closing the page during a slow upload does not lose the set change', async () => {
    api['sourcesStatus'].mockResolvedValue(DEFAULT);
    let done!: (s: SourcesStatus) => void;
    api['useExampleSources'].mockReturnValue(new Promise<SourcesStatus>((r) => (done = r)));
    const f = TestBed.createComponent(App);
    const state = await startLoading(f);
    clickInPage(f, "Usa l'esempio");
    // Esc during the operation is ignored: the dialog stays.
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    f.detectChanges();
    expect(f.nativeElement.querySelector('cra-sources-page')).not.toBeNull();
    // Even when closing the page from the outside, the notification lives in the store/shell.
    TestBed.inject(SourcesStore).closePage();
    f.detectChanges();
    expect(f.nativeElement.querySelector('cra-sources-page')).toBeNull();
    done(EXAMPLE);
    await tick();
    f.detectChanges();
    expect(state.screen()).toBe('INPUT');
  });
});

describe('App shell - set identity changed by the server (#473)', () => {
  const CUSTOM: SourcesStatus = {
    ...EXAMPLE,
    source_set_id: 'custom-aaaaaaaaaaaaaaaa',
    set: { ...EXAMPLE.set!, kind: 'custom' },
  };
  const LOST: SourcesStatus = {
    stato: 'default',
    scade_tra_secondi: null,
    set: null,
    source_set_id: 'default',
  };
  const results = {
    citta: 'Roma',
    zona_normalizzata: 'Centro',
    poi: [],
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
    contesto_hash: 'h',
  } as AnalyzeResponse;
  const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));
  let api: Record<string, jest.Mock>;

  beforeEach(async () => {
    api = {
      cities: jest.fn().mockResolvedValue([]),
      poiTypes: jest.fn().mockResolvedValue([]),
      sourcesStatus: jest.fn().mockResolvedValue(CUSTOM),
    };
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [{ provide: ApiService, useValue: api }],
    }).compileComponents();
  });

  async function start() {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();
    return {
      f,
      state: TestBed.inject(StateStore),
      sources: TestBed.inject(SourcesStore),
      form: f.componentInstance as unknown as {
        city: { set(v: string): void; (): string };
        zone: { set(v: string): void; (): string };
        poiType: { set(v: string): void; (): string };
      },
    };
  }

  it('another id on a re-read: results and indicator cleared, form kept', async () => {
    const { f, state, sources, form } = await start();
    expect(sources.indicator().kind).toBe('custom');
    form.city.set('Roma');
    form.zone.set('Centro');
    state.dispatch({ type: 'LOAD_SUCCESS', data: results, pipeline: 'full' });
    expect(state.screen()).toBe('RESULTS');

    api['sourcesStatus'].mockResolvedValue(LOST);
    await sources.refresh();
    await tick();
    f.detectChanges();

    expect(state.screen()).toBe('INPUT');
    expect(state.fullData()).toBeNull();
    expect(sources.indicator()).toEqual({ label: 'Predefinite', kind: 'default' });
    expect(form.city()).toBe('Roma');
    expect(form.zone()).toBe('Centro');
  });

  it('the same id on a re-read: nothing is cleared', async () => {
    const { f, state, sources } = await start();
    state.dispatch({ type: 'LOAD_SUCCESS', data: results, pipeline: 'full' });
    await sources.refresh();
    await tick();
    f.detectChanges();
    expect(state.screen()).toBe('RESULTS');
    expect(state.fullData()).not.toBeNull();
    expect(sources.indicator().kind).toBe('custom');
  });

  it('the error message survives the reset', async () => {
    const { f, state, sources } = await start();
    state.dispatch({
      type: 'ANALYZE',
      area: { kind: 'zone', city: 'Roma', zone: 'X' },
      pipeline: 'full',
    });
    state.dispatch({ type: 'LOAD_ERROR', message: 'Zona non trovata', pipeline: 'full' });
    api['sourcesStatus'].mockResolvedValue(LOST);
    await sources.refresh();
    await tick();
    f.detectChanges();
    expect(state.screen()).toBe('ERROR');
    expect(state.error()).toBe('Zona non trovata');
  });

  it('a change the user made (Torna al default) clears the results but keeps form and mode (#490)', async () => {
    api['resetSources'] = jest.fn().mockResolvedValue(LOST);
    const { f, state, sources, form } = await start();
    form.city.set('Roma');
    form.zone.set('Centro');
    state.dispatch({ type: 'LOAD_SUCCESS', data: results, pipeline: 'full' });
    await sources.reset();
    await tick();
    f.detectChanges();
    expect(state.screen()).toBe('INPUT');
    expect(form.city()).toBe('Roma');
    expect(sources.serverChanges()).toBe(0);
  });

  it('a change the user made while in Base stays in Base (#490)', async () => {
    api['resetSources'] = jest.fn().mockResolvedValue(LOST);
    const { f, state, sources } = await start();
    state.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
    state.dispatch({ type: 'LOAD_SUCCESS', data: results, pipeline: 'base' });
    await sources.reset();
    await tick();
    f.detectChanges();
    expect(state.mode()).toBe('base');
    expect(state.screen()).toBe('BASE');
    expect(state.baselineData()).toBeNull();
  });
});

describe('App shell - 410 fonti_scadute (#419)', () => {
  it('a 410 that answers an analysis brings the indicator to Scadute', async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [
        provideHttpClient(withInterceptors([sessionInterceptor])),
        provideHttpClientTesting(),
      ],
    }).compileComponents();
    const ctrl = TestBed.inject(HttpTestingController);
    const f = TestBed.createComponent(App);
    f.detectChanges();
    ctrl.match('/sources').forEach((r) =>
      r.flush({
        stato: 'default',
        scade_tra_secondi: null,
        set: null,
        source_set_id: 'default',
      }),
    );
    ctrl.match('/cities').forEach((r) => r.flush([]));
    ctrl.match('/poi-types').forEach((r) => r.flush([]));
    await tick2(); // lets the initial read of the sources state finish
    const state = TestBed.inject(StateStore);
    void state.startAnalysis({ kind: 'zone', city: 'Roma', zone: 'Centro' });
    ctrl
      .expectOne('/analyze')
      .flush(
        { detail: { errore: 'fonti_scadute', messaggio: 'Le fonti sono scadute.' } },
        { status: 410, statusText: 'Gone' },
      );
    await tick2();
    f.detectChanges();
    expect(f.nativeElement.querySelector('cra-sources-indicator button').textContent).toContain(
      'Fonti: Scadute',
    );
    expect(state.error()).toBe('Le fonti sono scadute.');
  });
});

const tick2 = () => new Promise<void>((resolve) => setTimeout(resolve, 0));
