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

import { TestBed } from '@angular/core/testing';
import { App } from './app';
import { ApiService } from '@core/api/api.service';
import { StateStore } from '@core/state/state.store';
import type { AnalyzeResponse } from '@core/models/models';

const emptyResp: AnalyzeResponse = {
  citta: 'Roma',
  zona_normalizzata: 'Centro',
  poi: [],
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

describe('App shell', () => {
  let store: StateStore;
  let api: { cities: jest.Mock; analyze: jest.Mock; analyzeBaseline: jest.Mock };

  beforeEach(async () => {
    api = {
      cities: jest.fn().mockResolvedValue([]),
      analyze: jest.fn(),
      analyzeBaseline: jest.fn(),
    };
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [{ provide: ApiService, useValue: api }],
    }).compileComponents();
    store = TestBed.inject(StateStore);
  });

  it("Stato INPUT all'avvio: pannello input + cra-map presenti", async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();
    expect(f.nativeElement.querySelector('cra-input-panel')).toBeTruthy();
    expect(f.nativeElement.querySelector('cra-map')).toBeTruthy();
  });

  it('Stato LOADING: overlay presente con la zona in corso (cosmetico)', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    store.dispatch({ type: 'ANALYZE', citta: 'Roma', zona: 'Trastevere', pipeline: 'completo' });
    f.detectChanges();

    expect(f.nativeElement.querySelector('cra-loading-overlay')).toBeTruthy();
    expect(f.nativeElement.textContent).toContain('Trastevere');
  });

  it('Stato RESULTS dopo LOAD_SUCCESS: pannello POI presente', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    store.dispatch({ type: 'LOAD_SUCCESS', data: emptyResp, pipeline: 'completo' });
    f.detectChanges();

    expect(f.nativeElement.querySelector('cra-poi-panel')).toBeTruthy();
  });

  it("Stato ERROR: pannello input riappare con il messaggio d'errore del backend", async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    store.dispatch({
      type: 'LOAD_ERROR',
      message: '"Atlantide" non corrisponde ad alcuna area.',
      pipeline: 'completo',
    });
    f.detectChanges();

    expect(f.nativeElement.querySelector('cra-input-panel')).toBeTruthy();
    expect(f.nativeElement.textContent).toContain('non corrisponde ad alcuna area');
  });

  it('Stato FILTER dopo SET_FILTER: pannello POI presente', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    store.dispatch({ type: 'LOAD_SUCCESS', data: emptyResp, pipeline: 'completo' });
    store.dispatch({ type: 'SET_FILTER', level: 'confermato' });
    f.detectChanges();

    expect(f.nativeElement.querySelector('cra-poi-panel')).toBeTruthy();
  });

  it('click su una card POI (evento selectPoi del pannello) dispatcha SELECT_POI ed evidenzia la card', async () => {
    const respWithPoi: AnalyzeResponse = {
      ...emptyResp,
      poi: [
        {
          id: 'poi-1',
          name: 'Colosseo',
          terminus_class: 'Archaeological_site',
          lat: 41.89,
          lon: 12.49,
          confidence: 'confermato',
          sparql_path: null,
          terminus_label_it: 'Sito archeologico',
          terminus_label_en: 'Archaeological site',
        },
      ],
    };
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    store.dispatch({ type: 'LOAD_SUCCESS', data: respWithPoi, pipeline: 'completo' });
    f.detectChanges();

    const card: HTMLElement = f.nativeElement.querySelector('.cra-poi-card');
    card.click();

    expect(store.selectedPoiId()).toBe('poi-1');
    expect(store.screen()).toBe('DETAIL');
  });

  it('percorso reale: submit da InputPanel (Stato A) → LOAD_ERROR → i campi conservano i valori digitati (MAJOR fix)', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();

    const cittaInput: HTMLInputElement = f.nativeElement.querySelector('#cra-citta');
    cittaInput.value = 'Roma';
    cittaInput.dispatchEvent(new Event('input'));
    const zonaInput: HTMLInputElement = f.nativeElement.querySelector('#cra-zona');
    zonaInput.value = 'Atlantide';
    zonaInput.dispatchEvent(new Event('input'));
    f.detectChanges();

    api.analyze.mockRejectedValue(new Error('"Atlantide" non corrisponde ad alcuna area.'));
    // Cattura la Promise reale ritornata da startAnalysis (chiamata "void" dallo shell su
    // onAnalyze): la attendiamo direttamente, senza affidarci all'euristica di stabilità
    // della zone su un evento DOM sparato manualmente.
    const startAnalysisSpy = jest.spyOn(store, 'startAnalysis');

    const form: HTMLFormElement = f.nativeElement.querySelector('form');
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    expect(store.screen()).toBe('LOADING');

    await startAnalysisSpy.mock.results[0].value;
    f.detectChanges();

    expect(store.screen()).toBe('ERROR');
    expect(f.nativeElement.textContent).toContain('non corrisponde ad alcuna area');

    // cra-input-panel è stato smontato (Stato A) e RIMONTATO (Stato Errore, @case distinto):
    // i valori devono arrivare dai selettori pending dello store, non da segnali locali sopravvissuti.
    const cittaAfterError: HTMLInputElement = f.nativeElement.querySelector('#cra-citta');
    const zonaAfterError: HTMLInputElement = f.nativeElement.querySelector('#cra-zona');
    expect(cittaAfterError.value).toBe('Roma');
    expect(zonaAfterError.value).toBe('Atlantide');
  });

  it('toggle RESULTS↔FILTER non rimonta cra-poi-panel (stesso nodo DOM, niente reset scroll)', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    store.dispatch({ type: 'LOAD_SUCCESS', data: emptyResp, pipeline: 'completo' });
    f.detectChanges();
    const panelInResults = f.nativeElement.querySelector('cra-poi-panel');
    expect(panelInResults).toBeTruthy();

    store.dispatch({ type: 'SET_FILTER', level: 'confermato' });
    f.detectChanges();
    expect(store.screen()).toBe('FILTER');
    expect(f.nativeElement.querySelector('cra-poi-panel')).toBe(panelInResults);

    store.dispatch({ type: 'CLEAR_FILTER' });
    f.detectChanges();
    expect(store.screen()).toBe('RESULTS');
    expect(f.nativeElement.querySelector('cra-poi-panel')).toBe(panelInResults);
  });

  it('ACCEPTANCE: Stato DETAIL mostra cra-detail-panel coi gruppi ordinati ONTOLOGIA→CONTESTO→SPECULATIVO, senza rimontare cra-poi-panel/cra-narrative-sheet', async () => {
    const respWithPoi: AnalyzeResponse = {
      ...emptyResp,
      poi: [
        {
          id: 'poi-1',
          name: 'Colosseo',
          terminus_class: 'Archaeological_site',
          lat: 41.89,
          lon: 12.49,
          confidence: 'confermato',
          sparql_path: 'Archaeological_site → havingHazard → Mugging',
          terminus_label_it: 'Sito archeologico',
          terminus_label_en: 'Archaeological site',
        },
      ],
      risk_models: [
        {
          poi: 'Colosseo',
          risks: [
            {
              hazard: 'h-spec',
              confidence: 'speculativo',
              tag: 'SPECULATIVO',
              hazard_label_it: 'Ipotesi',
              hazard_label_en: 'Hypothesis',
            },
            {
              hazard: 'h-onto',
              confidence: 'confermato',
              tag: 'ONTOLOGIA',
              hazard_label_it: 'Borseggio',
              hazard_label_en: 'Pickpocketing',
            },
          ],
        },
      ],
    };
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    store.dispatch({ type: 'LOAD_SUCCESS', data: respWithPoi, pipeline: 'completo' });
    f.detectChanges();
    const poiPanelBeforeSelect = f.nativeElement.querySelector('cra-poi-panel');
    const narrSheetBeforeSelect = f.nativeElement.querySelector('cra-narrative-sheet');
    expect(poiPanelBeforeSelect).toBeTruthy();
    expect(narrSheetBeforeSelect).toBeTruthy();

    (f.nativeElement.querySelector('.cra-poi-card') as HTMLElement).click();
    f.detectChanges();

    expect(store.screen()).toBe('DETAIL');
    expect(f.nativeElement.querySelector('cra-poi-panel')).toBe(poiPanelBeforeSelect);
    expect(f.nativeElement.querySelector('cra-narrative-sheet')).toBe(narrSheetBeforeSelect);
    expect(f.nativeElement.textContent).toContain(
      'supporto decisionale · valuta con fonti primarie',
    );

    // scope al cra-detail-panel: cra-narrative-sheet mostra gli stessi tag fonte nel suo stesso markup
    const detailPanel = f.nativeElement.querySelector('cra-detail-panel');
    const tags = detailPanel.querySelectorAll('.cra-source-tag');
    expect(Array.from(tags).map((t) => (t as Element).textContent?.trim())).toEqual([
      '[ONTOLOGIA]',
      '[SPECULATIVO]',
    ]);
    expect(detailPanel.querySelector('.cra-citation-line').textContent).toContain('havingHazard');

    (f.nativeElement.querySelector('.cra-detail-close') as HTMLElement).click();
    f.detectChanges();

    expect(store.screen()).toBe('RESULTS');
    expect(f.nativeElement.querySelector('cra-detail-panel')).toBeNull();
    expect(f.nativeElement.querySelector('cra-poi-panel')).toBe(poiPanelBeforeSelect);
  });

  it('ACCEPTANCE: Rigenera re-invoca startAnalysis con lastQuery e SOSTITUISCE i risultati (non li duplica)', async () => {
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();

    api.analyze.mockResolvedValueOnce({
      ...emptyResp,
      poi: [
        {
          id: 'a',
          name: 'A',
          terminus_class: 'x',
          lat: 0,
          lon: 0,
          confidence: 'confermato',
          sparql_path: null,
          terminus_label_it: '',
          terminus_label_en: '',
        },
      ],
    });
    await store.startAnalysis('Roma', 'Colosseo', 'di sera?');
    f.detectChanges();
    expect(store.completoData()?.poi).toHaveLength(1);
    expect(store.lastQuery()).toEqual({ citta: 'Roma', zona: 'Colosseo', domanda: 'di sera?' });

    const startAnalysisSpy = jest.spyOn(store, 'startAnalysis');
    api.analyze.mockResolvedValueOnce({
      ...emptyResp,
      poi: [
        {
          id: 'a',
          name: 'A',
          terminus_class: 'x',
          lat: 0,
          lon: 0,
          confidence: 'confermato',
          sparql_path: null,
          terminus_label_it: '',
          terminus_label_en: '',
        },
        {
          id: 'b',
          name: 'B',
          terminus_class: 'x',
          lat: 0,
          lon: 0,
          confidence: 'plausibile',
          sparql_path: null,
          terminus_label_it: '',
          terminus_label_en: '',
        },
      ],
    });

    (f.nativeElement.querySelector('.cra-btn-regen') as HTMLElement).click();
    expect(startAnalysisSpy).toHaveBeenCalledWith('Roma', 'Colosseo', 'di sera?');

    await startAnalysisSpy.mock.results[0].value;
    f.detectChanges();

    expect(store.completoData()?.poi).toHaveLength(2);
  });

  it("ACCEPTANCE: toggle Base nell'header porta a Stato BASE; la ricerca chiama /analyze/baseline e resta su BASE con la tabella popolata", async () => {
    api.cities.mockResolvedValue(['Roma']);
    const f = TestBed.createComponent(App);
    f.detectChanges();
    await f.whenStable();
    f.detectChanges();

    const modeButtons: HTMLButtonElement[] = Array.from(
      f.nativeElement.querySelectorAll('.cra-mode-btn'),
    );
    modeButtons.find((b) => b.textContent?.trim() === 'Base')!.click();
    f.detectChanges();
    await f.whenStable();
    f.detectChanges();

    expect(store.screen()).toBe('BASE');
    expect(f.nativeElement.querySelector('cra-base-panel')).toBeTruthy();

    const cittaInput: HTMLInputElement = f.nativeElement.querySelector('#cra-base-citta');
    cittaInput.value = 'Roma';
    cittaInput.dispatchEvent(new Event('input'));
    const zonaInput: HTMLInputElement = f.nativeElement.querySelector('#cra-base-zona');
    zonaInput.value = 'Centro';
    zonaInput.dispatchEvent(new Event('input'));
    f.detectChanges();

    api.analyzeBaseline.mockResolvedValue({
      ...emptyResp,
      poi: [
        {
          id: '1',
          name: 'Stazione',
          terminus_class: 'Railway_station',
          lat: 0,
          lon: 0,
          confidence: 'confermato',
          sparql_path: null,
          terminus_label_it: '',
          terminus_label_en: '',
        },
      ],
      risk_models: [
        {
          poi: 'Stazione',
          risks: [
            {
              hazard: 'h',
              confidence: 'confermato',
              tag: 'ONTOLOGIA',
              hazard_label_it: 'Furto',
              hazard_label_en: 'Theft',
            },
          ],
        },
      ],
    });
    const startBaselineSpy = jest.spyOn(store, 'startBaselineAnalysis');

    const form: HTMLFormElement = f.nativeElement.querySelector('.cra-base-form-panel form');
    form.dispatchEvent(new Event('submit', { cancelable: true }));
    expect(startBaselineSpy).toHaveBeenCalledWith({ citta: 'Roma', zona: 'Centro' });

    await startBaselineSpy.mock.results[0].value;
    f.detectChanges();

    // resta in Stato BASE (non salta su RESULTS del sistema completo) e mostra la tabella spartana
    expect(store.screen()).toBe('BASE');
    expect(f.nativeElement.querySelector('cra-base-panel')).toBeTruthy();
    expect(f.nativeElement.textContent).toContain('Furto');
    expect(f.nativeElement.textContent).toContain(
      'nessuna narrativa — il sistema base restituisce solo dati strutturati',
    );
  });

  describe('BLOCCANTI review: isolamento dati Completo↔Base', () => {
    it('(a) analisi Completo riuscita → toggle a Base NON mostra i dati LLM nella tabella base (vuota/form finché non si esegue la ricerca Base)', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      const completoResp: AnalyzeResponse = {
        ...emptyResp,
        poi: [
          {
            id: 'c1',
            name: 'CompletoPOI',
            terminus_class: 'x',
            lat: 0,
            lon: 0,
            confidence: 'confermato',
            sparql_path: null,
            terminus_label_it: '',
            terminus_label_en: '',
          },
        ],
        risk_models: [
          {
            poi: 'CompletoPOI',
            risks: [
              {
                hazard: 'hz',
                confidence: 'confermato',
                tag: 'ONTOLOGIA',
                hazard_label_it: 'HazardCompleto',
                hazard_label_en: 'x',
              },
            ],
          },
        ],
      };
      store.dispatch({ type: 'LOAD_SUCCESS', data: completoResp, pipeline: 'completo' });
      f.detectChanges();
      expect(store.screen()).toBe('RESULTS');

      store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
      f.detectChanges();
      expect(store.screen()).toBe('BASE');

      const basePanel: HTMLElement = f.nativeElement.querySelector('cra-base-panel');
      expect(basePanel.querySelectorAll('.cra-base-table tbody tr').length).toBe(0);
      expect(basePanel.textContent).not.toContain('HazardCompleto');
      expect(basePanel.textContent).not.toContain('CompletoPOI');
      expect(basePanel.textContent).toContain('Inserisci i parametri');
    });

    it("(b) ricerca Base riuscita dopo un'analisi Completo → toggle a Completo mostra ANCORA i dati completo (RESULTS/mappa NON mostrano i dati baseline)", async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      const completoResp: AnalyzeResponse = {
        ...emptyResp,
        poi: [
          {
            id: 'c1',
            name: 'CompletoPOI',
            terminus_class: 'x',
            lat: 0,
            lon: 0,
            confidence: 'confermato',
            sparql_path: null,
            terminus_label_it: '',
            terminus_label_en: '',
          },
        ],
      };
      store.dispatch({ type: 'LOAD_SUCCESS', data: completoResp, pipeline: 'completo' });
      f.detectChanges();
      expect(store.screen()).toBe('RESULTS');

      store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
      f.detectChanges();
      const baselineResp: AnalyzeResponse = {
        ...emptyResp,
        poi: [
          {
            id: 'b1',
            name: 'BaselinePOI',
            terminus_class: 'x',
            lat: 0,
            lon: 0,
            confidence: 'confermato',
            sparql_path: null,
            terminus_label_it: '',
            terminus_label_en: '',
          },
        ],
      };
      api.analyzeBaseline.mockResolvedValue(baselineResp);
      await store.startBaselineAnalysis({ citta: 'Roma', zona: 'Duomo' });
      f.detectChanges();
      expect(store.screen()).toBe('BASE');

      store.dispatch({ type: 'TOGGLE_MODE', mode: 'completo' });
      f.detectChanges();

      expect(store.screen()).toBe('RESULTS');
      expect(f.nativeElement.querySelector('cra-poi-panel').textContent).toContain('CompletoPOI');
      expect(f.nativeElement.textContent).not.toContain('BaselinePOI');
    });

    it('(c) errore in modalità Base → resta in Stato BASE (niente cra-input-panel del sistema completo) e il retry invoca /analyze/baseline, non /analyze', async () => {
      api.cities.mockResolvedValue(['Roma']);
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();
      f.detectChanges();

      store.dispatch({ type: 'TOGGLE_MODE', mode: 'base' });
      f.detectChanges();
      await f.whenStable();
      f.detectChanges();

      const cittaInput: HTMLInputElement = f.nativeElement.querySelector('#cra-base-citta');
      cittaInput.value = 'Roma';
      cittaInput.dispatchEvent(new Event('input'));
      const zonaInput: HTMLInputElement = f.nativeElement.querySelector('#cra-base-zona');
      zonaInput.value = 'Atlantide';
      zonaInput.dispatchEvent(new Event('input'));
      f.detectChanges();

      api.analyzeBaseline.mockRejectedValueOnce(
        new Error('"Atlantide" non corrisponde ad alcuna area.'),
      );
      const startBaselineSpy = jest.spyOn(store, 'startBaselineAnalysis');

      const form: HTMLFormElement = f.nativeElement.querySelector('.cra-base-form-panel form');
      form.dispatchEvent(new Event('submit', { cancelable: true }));
      expect(store.screen()).toBe('LOADING');

      await startBaselineSpy.mock.results[0].value;
      f.detectChanges();

      expect(store.screen()).toBe('BASE');
      expect(f.nativeElement.querySelector('cra-input-panel')).toBeNull();
      expect(f.nativeElement.textContent).toContain('non corrisponde ad alcuna area');

      // retry: il form persiste nello stesso schermo BASE, reinvia → deve richiamare startBaselineAnalysis, MAI store.startAnalysis
      api.analyzeBaseline.mockResolvedValueOnce({ ...emptyResp, poi: [] });
      const formAfterError: HTMLFormElement = f.nativeElement.querySelector(
        '.cra-base-form-panel form',
      );
      formAfterError.dispatchEvent(new Event('submit', { cancelable: true }));

      expect(startBaselineSpy).toHaveBeenCalledTimes(2);
      expect(api.analyze).not.toHaveBeenCalled();
    });
  });

  describe('BLOCCANTI review #67-bis: race condition sul routing + lastQuery non isolato', () => {
    it('BLOCCANTE A: durante LOADING i bottoni del toggle Completo/Base sono disabilitati nel DOM reale (wiring end-to-end)', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      store.dispatch({ type: 'ANALYZE', citta: 'Roma', zona: 'Trastevere', pipeline: 'completo' });
      f.detectChanges();

      const modeButtons: HTMLButtonElement[] = Array.from(
        f.nativeElement.querySelectorAll('.cra-mode-btn'),
      );
      expect(modeButtons.length).toBeGreaterThan(0);
      expect(modeButtons.every((b) => b.disabled)).toBe(true);
    });

    it('BLOCCANTE A: la guardia in onToggleMode blocca il cambio di modalità durante LOADING anche bypassando il disabled del bottone', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      store.dispatch({ type: 'ANALYZE', citta: 'Roma', zona: 'Trastevere', pipeline: 'completo' });
      f.detectChanges();
      expect(store.mode()).toBe('completo');

      (
        f.componentInstance as unknown as { onToggleMode(mode: 'completo' | 'base'): void }
      ).onToggleMode('base');

      expect(store.mode()).toBe('completo');
      expect(store.screen()).toBe('LOADING');
    });

    it('BLOCCANTE B: una ricerca Base non sovrascrive lastQuery — "Rigenera" dopo un giro Completo→Base→Completo rilancia ancora la query Completo originale, non l\'ultima Base', async () => {
      const f = TestBed.createComponent(App);
      f.detectChanges();
      await f.whenStable();

      // 1) analisi Completo Roma/Colosseo
      api.analyze.mockResolvedValueOnce({
        ...emptyResp,
        citta: 'Roma',
        zona_normalizzata: 'Colosseo',
      });
      await store.startAnalysis('Roma', 'Colosseo', null);
      f.detectChanges();
      expect(store.screen()).toBe('RESULTS');

      // 2) toggle a Base + ricerca Base Milano/Duomo
      const modeButtons: HTMLButtonElement[] = Array.from(
        f.nativeElement.querySelectorAll('.cra-mode-btn'),
      );
      modeButtons.find((b) => b.textContent?.trim() === 'Base')!.click();
      f.detectChanges();
      api.analyzeBaseline.mockResolvedValueOnce({
        ...emptyResp,
        citta: 'Milano',
        zona_normalizzata: 'Duomo',
      });
      await store.startBaselineAnalysis({ citta: 'Milano', zona: 'Duomo' });
      f.detectChanges();
      expect(store.screen()).toBe('BASE');

      // 3) torna a Completo: RESULTS deve mostrare ancora Roma/Colosseo (completoData intatto)
      const modeButtonsAfter: HTMLButtonElement[] = Array.from(
        f.nativeElement.querySelectorAll('.cra-mode-btn'),
      );
      modeButtonsAfter.find((b) => b.textContent?.trim() === 'Completo')!.click();
      f.detectChanges();
      expect(store.screen()).toBe('RESULTS');
      expect(store.completoData()?.citta).toBe('Roma');

      // 4) Rigenera deve rilanciare /analyze per Roma/Colosseo, MAI per Milano/Duomo
      const startAnalysisSpy = jest.spyOn(store, 'startAnalysis');
      api.analyze.mockResolvedValueOnce({
        ...emptyResp,
        citta: 'Roma',
        zona_normalizzata: 'Colosseo',
      });
      (f.nativeElement.querySelector('.cra-btn-regen') as HTMLElement).click();

      expect(startAnalysisSpy).toHaveBeenCalledWith('Roma', 'Colosseo', null);
    });
  });
});
