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
import type { SourcesStatus } from '@core/models/models';
import { App } from './app';

const EXAMPLE: SourcesStatus = {
  stato: 'attivo',
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

describe('App shell - fonti (#419)', () => {
  let api: Record<string, jest.Mock>;

  beforeEach(async () => {
    api = {
      cities: jest.fn().mockResolvedValue([]),
      poiTypes: jest.fn().mockResolvedValue([]),
      invalidatePoiTypes: jest.fn(),
      sourcesStatus: jest.fn().mockResolvedValue(EXAMPLE),
      useExampleSources: jest.fn().mockResolvedValue(EXAMPLE),
      resetSources: jest
        .fn()
        .mockResolvedValue({ stato: 'default', scade_tra_secondi: null, set: null }),
      templateUrl: jest.fn((n: string) => `/sources/templates/${n}`),
    };
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [{ provide: ApiService, useValue: api }],
    }).compileComponents();
  });

  it("l'indicatore e' nell'header, sempre, e riflette lo stato letto all'avvio", async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();
    f.detectChanges();
    const ind = f.nativeElement.querySelector('header cra-sources-indicator button');
    expect(ind.textContent).toContain('Fonti: Esempio');
  });

  it("cambiando il set attivo l'elenco dei tipi POI viene invalidato, non a ogni lettura", async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();
    expect(api['invalidatePoiTypes']).not.toHaveBeenCalled();
    await TestBed.inject(SourcesStore).reset();
    f.detectChanges();
    expect(api['invalidatePoiTypes']).toHaveBeenCalledTimes(1);
  });

  it("senza backend l'indicatore dice Predefinite", async () => {
    api['sourcesStatus'].mockRejectedValue(new Error('down'));
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();
    f.detectChanges();
    expect(f.nativeElement.querySelector('cra-sources-indicator').textContent).toContain(
      'Predefinite',
    );
  });

  it("il clic sull'indicatore apre la pagina, Chiudi la chiude", async () => {
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

  const DEFAULT: SourcesStatus = { stato: 'default', scade_tra_secondi: null, set: null };
  const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

  async function startLoading(f: ReturnType<typeof TestBed.createComponent<App>>) {
    const state = TestBed.inject(StateStore);
    f.detectChanges();
    await f.whenStable();
    state.dispatch({
      type: 'ANALYZE',
      area: { kind: 'zone', citta: 'Roma', zona: 'Centro' },
      pipeline: 'completo',
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

  // Niente `whenStable` dopo ANALYZE: in LOADING l'overlay cosmetico tiene dei timer pendenti.

  it('cambiare davvero le fonti (esempio -> default) azzera i risultati', async () => {
    const f = TestBed.createComponent(App);
    const state = await startLoading(f);
    clickInPage(f, 'Torna al default');
    await tick();
    f.detectChanges();
    expect(api['resetSources']).toHaveBeenCalled();
    expect(state.screen()).toBe('INPUT');
  });

  it('Torna al default a fonti gia default NON azzera nulla', async () => {
    api['sourcesStatus'].mockResolvedValue(DEFAULT);
    const f = TestBed.createComponent(App);
    const state = await startLoading(f);
    clickInPage(f, 'Torna al default');
    await tick();
    expect(api['resetSources']).toHaveBeenCalled();
    expect(state.screen()).toBe('LOADING');
  });

  it("Usa l'esempio a esempio gia attivo NON azzera nulla", async () => {
    const f = TestBed.createComponent(App);
    const state = await startLoading(f);
    clickInPage(f, "Usa l'esempio");
    await tick();
    expect(api['useExampleSources']).toHaveBeenCalled();
    expect(state.screen()).toBe('LOADING');
  });

  it('chiudere la pagina durante un caricamento lento non perde il cambio del set', async () => {
    api['sourcesStatus'].mockResolvedValue(DEFAULT);
    let done!: (s: SourcesStatus) => void;
    api['useExampleSources'].mockReturnValue(new Promise<SourcesStatus>((r) => (done = r)));
    const f = TestBed.createComponent(App);
    const state = await startLoading(f);
    clickInPage(f, "Usa l'esempio");
    // Esc durante l'operazione e' ignorato: il dialog resta.
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    f.detectChanges();
    expect(f.nativeElement.querySelector('cra-sources-page')).not.toBeNull();
    // Anche chiudendo la pagina dall'esterno, la notifica vive nello store/shell.
    TestBed.inject(SourcesStore).closePage();
    f.detectChanges();
    expect(f.nativeElement.querySelector('cra-sources-page')).toBeNull();
    done(EXAMPLE);
    await tick();
    f.detectChanges();
    expect(state.screen()).toBe('INPUT');
  });
});

describe('App shell - 410 fonti_scadute (#419)', () => {
  it("un'analisi che risponde 410 porta l'indicatore su Scadute", async () => {
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
    ctrl
      .match('/sources')
      .forEach((r) => r.flush({ stato: 'default', scade_tra_secondi: null, set: null }));
    ctrl.match('/cities').forEach((r) => r.flush([]));
    ctrl.match('/poi-types').forEach((r) => r.flush([]));
    await tick2(); // lascia chiudere la lettura iniziale dello stato fonti
    const state = TestBed.inject(StateStore);
    void state.startAnalysis({ kind: 'zone', citta: 'Roma', zona: 'Centro' });
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
