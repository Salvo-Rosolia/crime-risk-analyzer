import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ApiService } from '@core/api/api.service';
import { BasePanelComponent } from './base-panel.component';
import type { AnalyzeResponse } from '@core/models/models';

const dataWithRows: AnalyzeResponse = {
  citta: 'Roma',
  zona_normalizzata: 'Colosseo',
  poi: [
    {
      id: '1',
      name: 'Colosseo',
      terminus_class: 'Archaeological_site',
      lat: 0,
      lon: 0,
      confidence: 'verificato',
      sparql_path: null,
      terminus_label_it: 'Sito archeologico',
      terminus_label_en: 'Archaeological site',
    },
  ],
  risk_models: [
    {
      poi_id: '1',
      poi: 'Colosseo',
      risks: [
        {
          hazard: 'h1',
          confidence: 'verificato',
          tag: 'ONTOLOGIA',
          hazard_label_it: 'Borseggio',
          hazard_label_en: 'Pickpocketing',
        },
        {
          hazard: 'h2',
          confidence: 'da_confermare',
          tag: 'SPECULATIVO',
          hazard_label_it: 'Accattonaggio',
          hazard_label_en: 'Begging',
        },
      ],
    },
  ],
  narrativa: '',
  narrativa_fonti: { overview: '', ontologia: '', contesto: '', speculativo: '' },
  confidence_summary: { verificato: 1, da_confermare: 0 },
  llm_used: '',
  latenza_ms: 0,
  tokens_input: 0,
  tokens_output: 0,
  repro: { temperature: 0, seed: 0, prompt_hash: '' },
  cache_hit: false,
  fallback: false,
  contesto_hash: 'h-ctx',
};

const poiTypesFixture = [
  { terminus_class: 'Bank', label_it: 'Banca' },
  { terminus_class: 'Railway_station', label_it: 'Stazione ferroviaria' },
];

describe('BasePanelComponent', () => {
  let fixture: ComponentFixture<BasePanelComponent>;
  let api: { cities: jest.Mock; poiTypes: jest.Mock };

  function submitForm(): void {
    const form: HTMLFormElement = fixture.nativeElement.querySelector('form');
    form.dispatchEvent(new Event('submit', { cancelable: true }));
  }

  function selectPoiType(value: string): void {
    const select: HTMLSelectElement = fixture.nativeElement.querySelector('#cra-base-poi-type');
    select.value = value;
    select.dispatchEvent(new Event('change'));
  }

  function setFieldValue(selector: string, value: string): void {
    const input: HTMLInputElement = fixture.nativeElement.querySelector(selector);
    input.value = value;
    input.dispatchEvent(new Event('input'));
  }

  beforeEach(async () => {
    api = {
      cities: jest.fn().mockResolvedValue(['Roma', 'Milano']),
      poiTypes: jest.fn().mockResolvedValue(poiTypesFixture),
    };
    await TestBed.configureTestingModule({
      imports: [BasePanelComponent],
      providers: [{ provide: ApiService, useValue: api }],
    }).compileComponents();
    fixture = TestBed.createComponent(BasePanelComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  });

  it('shows the "Parametri ricerca" form with the optional Tipo POI field (select) and the Città/Zona fields', () => {
    const select = fixture.nativeElement.querySelector('#cra-base-poi-type');
    expect(select).toBeTruthy();
    expect(select.tagName).toBe('SELECT');
    expect(fixture.nativeElement.querySelector('#cra-base-city')).toBeTruthy();
    expect(fixture.nativeElement.querySelector('#cra-base-zone')).toBeTruthy();
  });

  it('loads the cities from ApiService.cities() and offers them in the datalist', () => {
    expect(api.cities).toHaveBeenCalled();
    expect(fixture.nativeElement.querySelectorAll('#cra-base-city-options option').length).toBe(2);
  });

  describe('Tipo POI select (#143: replaces the free text, compared exactly by the backend)', () => {
    it('loads the types from ApiService.poiTypes() and populates the select with "Tutti i tipi" as the first option', () => {
      expect(api.poiTypes).toHaveBeenCalled();
      const options: HTMLOptionElement[] = Array.from(
        fixture.nativeElement.querySelectorAll('#cra-base-poi-type option'),
      );
      expect(options.length).toBe(1 + poiTypesFixture.length);
      expect(options[0].value).toBe('');
      expect(options[0].textContent?.trim()).toBe('Tutti i tipi');
      expect(options[1].value).toBe('Bank');
      expect(options[1].textContent?.trim()).toBe('Banca');
      expect(options[2].value).toBe('Railway_station');
      expect(options[2].textContent?.trim()).toBe('Stazione ferroviaria');
    });

    it('calls ApiService.poiTypes() only once (memoized service-side, here only a prompt for ngOnInit)', () => {
      expect(api.poiTypes).toHaveBeenCalledTimes(1);
    });

    it('if ApiService.poiTypes() fails the select shows only "Tutti i tipi", with no blocking error', async () => {
      api.poiTypes.mockRejectedValueOnce(new Error('503'));
      const f = TestBed.createComponent(BasePanelComponent);
      f.detectChanges();
      await f.whenStable();
      f.detectChanges();

      const options: HTMLOptionElement[] = Array.from(
        f.nativeElement.querySelectorAll('#cra-base-poi-type option'),
      );
      expect(options.length).toBe(1);
      expect(options[0].value).toBe('');
      // The form stays usable: no alert generated by this failure.
      expect(f.nativeElement.querySelector('.cra-input-error')).toBeNull();
    });

    it('with "Tutti i tipi" selected (default, no poiType input from the shell) the submit does not include poiType', () => {
      const spy = jest.fn();
      fixture.componentInstance.analyzeBaseline.subscribe(spy);
      fixture.componentRef.setInput('area', {
        kind: 'circle',
        center: { lat: 41.9, lon: 12.5 },
        radiusM: 500,
      });
      fixture.detectChanges();
      submitForm();
      expect(spy).toHaveBeenCalledWith({
        area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 },
      });
    });

    it('the select reflects the `poiType` input received from the shell (same pattern as city/zone, #143 review finding)', () => {
      fixture.componentRef.setInput('poiType', 'Bank');
      fixture.detectChanges();
      const select: HTMLSelectElement = fixture.nativeElement.querySelector('#cra-base-poi-type');
      expect(select.value).toBe('Bank');
    });

    it('selecting an option emits poiTypeChange towards the shell with the canonical terminus_class (not the Italian label)', () => {
      const spy = jest.fn();
      fixture.componentInstance.poiTypeChange.subscribe(spy);
      selectPoiType('Railway_station');
      expect(spy).toHaveBeenCalledWith('Railway_station');
    });

    it('submit includes poiType when the `poiType` input (shell state) is set', () => {
      const spy = jest.fn();
      fixture.componentInstance.analyzeBaseline.subscribe(spy);
      fixture.componentRef.setInput('area', {
        kind: 'circle',
        center: { lat: 41.9, lon: 12.5 },
        radiusM: 500,
      });
      fixture.componentRef.setInput('poiType', 'Railway_station');
      fixture.detectChanges();
      submitForm();
      expect(spy).toHaveBeenCalledWith({
        area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 },
        poiType: 'Railway_station',
      });
    });
  });

  it('lists what is absent in the base system', () => {
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Assente nel base');
    expect(text).toContain('linguaggio naturale');
    expect(text).toContain('narrativa');
    expect(text).toContain('confidence');
    expect(text).toContain('path SPARQL');
    expect(text).toContain('mappa');
  });

  it('the Cerca button is always enabled (pre-#318, same UX as InputPanelComponent)', () => {
    fixture.componentRef.setInput('area', null);
    fixture.detectChanges();
    const btn: HTMLButtonElement = fixture.nativeElement.querySelector('button[type="submit"]');
    expect(btn.disabled).toBe(false);
  });

  it('submit with a drawn circle emits analyzeBaseline with BaselineParams (poiType absent if empty)', () => {
    const spy = jest.fn();
    fixture.componentInstance.analyzeBaseline.subscribe(spy);
    fixture.componentRef.setInput('area', {
      kind: 'circle',
      center: { lat: 41.9, lon: 12.5 },
      radiusM: 500,
    });
    fixture.detectChanges();
    submitForm();
    expect(spy).toHaveBeenCalledWith({
      area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 },
    });
  });

  it('submit with city/zone filled emits analyzeBaseline with an area in city/zone mode', () => {
    const spy = jest.fn();
    fixture.componentInstance.analyzeBaseline.subscribe(spy);
    fixture.componentRef.setInput('area', { kind: 'zone', city: 'Roma', zone: 'Colosseo' });
    fixture.detectChanges();
    submitForm();
    expect(spy).toHaveBeenCalledWith({
      area: { kind: 'zone', city: 'Roma', zone: 'Colosseo' },
    });
  });

  it('a11y: the field in error carries aria-invalid and aria-describedby pointing to the message id', () => {
    fixture.componentRef.setInput('area', null);
    fixture.detectChanges();
    submitForm();
    fixture.detectChanges();

    const cityField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-base-city');
    const zoneField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-base-zone');
    const errorMsg: HTMLElement = fixture.nativeElement.querySelector('.cra-input-error');

    expect(errorMsg.id).toBeTruthy();
    expect(cityField.getAttribute('aria-invalid')).toBe('true');
    expect(cityField.getAttribute('aria-describedby')).toBe(errorMsg.id);
    expect(zoneField.getAttribute('aria-invalid')).toBeNull();
    expect(zoneField.getAttribute('aria-describedby')).toBeNull();
  });

  it('the button is linked via aria-describedby to the text explaining the two area-selection modes', () => {
    const btn: HTMLButtonElement = fixture.nativeElement.querySelector('button[type="submit"]');
    const describedById = btn.getAttribute('aria-describedby');
    expect(describedById).toBeTruthy();
    const hint = fixture.nativeElement.querySelector(`#${describedById}`);
    expect(hint).toBeTruthy();
    expect(hint.classList).toContain('cra-hint');
  });

  it('without an area the submit does not emit analyzeBaseline and shows the error on the city field', () => {
    const spy = jest.fn();
    fixture.componentInstance.analyzeBaseline.subscribe(spy);
    fixture.componentRef.setInput('area', null);
    fixture.detectChanges();
    submitForm();
    fixture.detectChanges();
    expect(spy).not.toHaveBeenCalled();
    expect(fixture.nativeElement.textContent).toContain('Inserisci una città.');
  });

  it('typing in city/zone emits cityChange/zoneChange towards the shell', () => {
    const citySpy = jest.fn();
    const zoneSpy = jest.fn();
    fixture.componentInstance.cityChange.subscribe(citySpy);
    fixture.componentInstance.zoneChange.subscribe(zoneSpy);

    setFieldValue('#cra-base-city', 'Napoli');
    setFieldValue('#cra-base-zone', 'Centro');

    expect(citySpy).toHaveBeenCalledWith('Napoli');
    expect(zoneSpy).toHaveBeenCalledWith('Centro');
  });

  it('without data it shows an honest placeholder (not a table with invented rows)', () => {
    expect(fixture.nativeElement.querySelector('.cra-base-table tbody tr')).toBeNull();
    expect(fixture.nativeElement.textContent).toContain('Inserisci i parametri');
  });

  it('with data it shows the POI · Hazard · Categoria table via buildBaseRows', () => {
    fixture.componentRef.setInput('data', dataWithRows);
    fixture.detectChanges();
    const rows = fixture.nativeElement.querySelectorAll('.cra-base-table tbody tr');
    expect(rows.length).toBe(2);
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Colosseo');
    expect(text).toContain('Borseggio');
    expect(text).toContain('tc:Archaeological_site');
    expect(text).toContain('2');
  });

  it('"nessuna narrativa" footer always present, with or without data', () => {
    const FOOTER = 'nessuna narrativa — il sistema base restituisce solo dati strutturati';
    expect(fixture.nativeElement.textContent).toContain(FOOTER);
    fixture.componentRef.setInput('data', dataWithRows);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(FOOTER);
  });

  it('fidelity to the positioning constraints: no confidence/colors/pattuglia in the table', () => {
    fixture.componentRef.setInput('data', dataWithRows);
    fixture.detectChanges();
    const text = fixture.nativeElement.textContent;
    expect(text).not.toContain('Identificato');
    expect(text).not.toContain('Ipotesi');
    expect(text).not.toContain('Assegna pattuglia');
    expect(fixture.nativeElement.querySelectorAll('.cra-base-table [style*="color"]').length).toBe(
      0,
    );
  });

  describe('#318/#335 (review finding C1): dead end without a chosen area', () => {
    it('without an area it shows the invitation to fill in city/zone or go back to Completo, and a dedicated button', () => {
      fixture.componentRef.setInput('area', null);
      fixture.detectChanges();

      const text = fixture.nativeElement.textContent;
      expect(text).toContain('Torna a Completo');
      expect(text).not.toContain('Disegna un cerchio sulla mappa');
    });

    it('the "Torna a Completo" button emits backToFull', () => {
      fixture.componentRef.setInput('area', null);
      fixture.detectChanges();

      const spy = jest.fn();
      fixture.componentInstance.backToFull.subscribe(spy);
      const buttons: HTMLButtonElement[] = Array.from(
        fixture.nativeElement.querySelectorAll('button'),
      );
      buttons.find((b) => b.textContent?.trim() === 'Torna a Completo')!.click();

      expect(spy).toHaveBeenCalledTimes(1);
    });

    it('with a drawn circle it goes back to the original message, no "Torna a Completo" button', () => {
      fixture.componentRef.setInput('area', {
        kind: 'circle',
        center: { lat: 41.9, lon: 12.5 },
        radiusM: 500,
      });
      fixture.detectChanges();

      const text = fixture.nativeElement.textContent;
      expect(text).toContain('il cerchio disegnato sulla mappa');
      expect(text).not.toContain('Torna a Completo');
    });

    it('with city/zone filled the same: no "Torna a Completo" button', () => {
      fixture.componentRef.setInput('area', { kind: 'zone', city: 'Roma', zone: 'Colosseo' });
      fixture.detectChanges();

      const text = fixture.nativeElement.textContent;
      expect(text).toContain('città e zona inserite qui sotto');
      expect(text).not.toContain('Torna a Completo');
    });
  });

  describe('error/retry handling (blocker 2 review #67: the retry stays inside this panel)', () => {
    it('shows the server error message (serverError) when present', () => {
      fixture.componentRef.setInput('serverError', '"Atlantide" non corrisponde ad alcuna area.');
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('non corrisponde ad alcuna area');
    });

    it('422 unrecognized POI type (#143): the backend message is shown like any other error of the panel', () => {
      fixture.componentRef.setInput('serverError', "Tipo POI non riconosciuto: 'banca'");
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('Tipo POI non riconosciuto');
    });

    it('the error message is rendered as TEXT, not interpreted as HTML (Angular interpolation, never innerHTML)', () => {
      fixture.componentRef.setInput('serverError', '<b>Tipo POI</b> non riconosciuto');
      fixture.detectChanges();
      const errorEl: HTMLElement = fixture.nativeElement.querySelector('.cra-input-error');
      expect(errorEl.querySelector('b')).toBeNull();
      expect(errorEl.textContent).toContain('<b>Tipo POI</b> non riconosciuto');
    });

    it('server error with area in city/zone mode: the error border goes on the zone field', () => {
      fixture.componentRef.setInput('area', { kind: 'zone', city: 'Roma', zone: 'Atlantide' });
      fixture.componentRef.setInput('serverError', '"Atlantide" non trovata.');
      fixture.detectChanges();
      const zoneField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-base-zone');
      expect(zoneField.classList).toContain('cra-field-error');
    });

    it('the form stays unchanged and reusable after a server error: a new submit calls analyzeBaseline again', () => {
      fixture.componentRef.setInput('serverError', '"Atlantide" non trovata.');
      fixture.detectChanges();
      const spy = jest.fn();
      fixture.componentInstance.analyzeBaseline.subscribe(spy);

      fixture.componentRef.setInput('area', {
        kind: 'circle',
        center: { lat: 41.9, lon: 12.5 },
        radiusM: 500,
      });
      fixture.detectChanges();
      submitForm();

      expect(spy).toHaveBeenCalledWith({
        area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 },
      });
    });

    it('BLOCKER (review finding): an empty submit shows "Inserisci una città.", but drawing a circle right after clears the error', () => {
      fixture.componentRef.setInput('area', null);
      fixture.detectChanges();
      submitForm();
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('Inserisci una città.');

      fixture.componentRef.setInput('area', {
        kind: 'circle',
        center: { lat: 41.9, lon: 12.5 },
        radiusM: 500,
      });
      fixture.detectChanges();

      expect(fixture.nativeElement.textContent).not.toContain('Inserisci una città.');
    });

    it('BLOCKER (review finding): a 503 in circle mode does not stay attached to the zone field after typing a NEW city/zone', () => {
      fixture.componentRef.setInput('area', {
        kind: 'circle',
        center: { lat: 41.9, lon: 12.5 },
        radiusM: 500,
      });
      fixture.componentRef.setInput('serverError', 'Servizio di geocoding non raggiungibile.');
      fixture.detectChanges();

      fixture.componentRef.setInput('area', { kind: 'zone', city: 'Roma', zone: 'Colosseo' });
      fixture.detectChanges();

      const zoneField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-base-zone');
      expect(zoneField.classList).not.toContain('cra-field-error');
    });

    it('a server error on the SAME city/zone area (retry without modifying the fields) stays attached to the zone field', () => {
      const zoneArea = { kind: 'zone' as const, city: 'Roma', zone: 'Atlantide' };
      fixture.componentRef.setInput('area', zoneArea);
      fixture.componentRef.setInput('serverError', '"Atlantide" non trovata.');
      fixture.detectChanges();

      fixture.componentRef.setInput('serverError', '"Atlantide" non trovata.');
      fixture.detectChanges();

      const zoneField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-base-zone');
      expect(zoneField.classList).toContain('cra-field-error');
    });
  });
});
