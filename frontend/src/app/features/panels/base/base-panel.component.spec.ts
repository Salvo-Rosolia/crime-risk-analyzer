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

describe('BasePanelComponent', () => {
  let fixture: ComponentFixture<BasePanelComponent>;
  let api: { cities: jest.Mock };

  function submitForm(): void {
    const form: HTMLFormElement = fixture.nativeElement.querySelector('form');
    form.dispatchEvent(new Event('submit', { cancelable: true }));
  }

  function setTipoPoi(value: string): void {
    const input: HTMLInputElement = fixture.nativeElement.querySelector('#cra-base-tipo-poi');
    input.value = value;
    input.dispatchEvent(new Event('input'));
  }

  function setFieldValue(selector: string, value: string): void {
    const input: HTMLInputElement = fixture.nativeElement.querySelector(selector);
    input.value = value;
    input.dispatchEvent(new Event('input'));
  }

  beforeEach(async () => {
    api = { cities: jest.fn().mockResolvedValue(['Roma', 'Milano']) };
    await TestBed.configureTestingModule({
      imports: [BasePanelComponent],
      providers: [{ provide: ApiService, useValue: api }],
    }).compileComponents();
    fixture = TestBed.createComponent(BasePanelComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  });

  it('mostra il form "Parametri ricerca" con il campo Tipo POI opzionale e i campi Città/Zona', () => {
    expect(fixture.nativeElement.querySelector('#cra-base-tipo-poi')).toBeTruthy();
    expect(fixture.nativeElement.querySelector('#cra-base-citta')).toBeTruthy();
    expect(fixture.nativeElement.querySelector('#cra-base-zona')).toBeTruthy();
  });

  it('carica le città da ApiService.cities() e le propone nella datalist', () => {
    expect(api.cities).toHaveBeenCalled();
    expect(fixture.nativeElement.querySelectorAll('#cra-base-citta-options option').length).toBe(2);
  });

  it('elenca cosa è assente nel sistema base', () => {
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Assente nel base');
    expect(text).toContain('linguaggio naturale');
    expect(text).toContain('narrativa');
    expect(text).toContain('confidence');
    expect(text).toContain('path SPARQL');
    expect(text).toContain('mappa');
  });

  it('il bottone Cerca è sempre abilitato (pre-#318, stessa UX di InputPanelComponent)', () => {
    fixture.componentRef.setInput('area', null);
    fixture.detectChanges();
    const btn: HTMLButtonElement = fixture.nativeElement.querySelector('button[type="submit"]');
    expect(btn.disabled).toBe(false);
  });

  it('submit con cerchio disegnato emette analyzeBaseline con BaselineParams (tipo_poi assente se vuoto)', () => {
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

  it('submit con città/zona compilate emette analyzeBaseline con area in modalità città/zona', () => {
    const spy = jest.fn();
    fixture.componentInstance.analyzeBaseline.subscribe(spy);
    fixture.componentRef.setInput('area', { kind: 'zone', citta: 'Roma', zona: 'Colosseo' });
    fixture.detectChanges();
    submitForm();
    expect(spy).toHaveBeenCalledWith({
      area: { kind: 'zone', citta: 'Roma', zona: 'Colosseo' },
    });
  });

  it('include tipo_poi (trimmato) quando valorizzato', () => {
    const spy = jest.fn();
    fixture.componentInstance.analyzeBaseline.subscribe(spy);
    fixture.componentRef.setInput('area', {
      kind: 'circle',
      center: { lat: 41.9, lon: 12.5 },
      radiusM: 500,
    });
    fixture.detectChanges();
    setTipoPoi('  Railway_station  ');
    fixture.detectChanges();
    submitForm();
    expect(spy).toHaveBeenCalledWith({
      area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 },
      tipo_poi: 'Railway_station',
    });
  });

  it('a11y: il campo in errore porta aria-invalid e aria-describedby verso l’id del messaggio', () => {
    fixture.componentRef.setInput('area', null);
    fixture.detectChanges();
    submitForm();
    fixture.detectChanges();

    const cittaField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-base-citta');
    const zonaField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-base-zona');
    const errorMsg: HTMLElement = fixture.nativeElement.querySelector('.cra-input-error');

    expect(errorMsg.id).toBeTruthy();
    expect(cittaField.getAttribute('aria-invalid')).toBe('true');
    expect(cittaField.getAttribute('aria-describedby')).toBe(errorMsg.id);
    expect(zonaField.getAttribute('aria-invalid')).toBeNull();
    expect(zonaField.getAttribute('aria-describedby')).toBeNull();
  });

  it('il bottone è collegato via aria-describedby al testo che spiega le due modalità di scelta dell’area', () => {
    const btn: HTMLButtonElement = fixture.nativeElement.querySelector('button[type="submit"]');
    const describedById = btn.getAttribute('aria-describedby');
    expect(describedById).toBeTruthy();
    const hint = fixture.nativeElement.querySelector(`#${describedById}`);
    expect(hint).toBeTruthy();
    expect(hint.classList).toContain('cra-hint');
  });

  it('senza area il submit non emette analyzeBaseline e mostra l’errore sul campo città', () => {
    const spy = jest.fn();
    fixture.componentInstance.analyzeBaseline.subscribe(spy);
    fixture.componentRef.setInput('area', null);
    fixture.detectChanges();
    submitForm();
    fixture.detectChanges();
    expect(spy).not.toHaveBeenCalled();
    expect(fixture.nativeElement.textContent).toContain('Inserisci una città.');
  });

  it('digitare in città/zona emette cittaChange/zonaChange verso lo shell', () => {
    const cittaSpy = jest.fn();
    const zonaSpy = jest.fn();
    fixture.componentInstance.cittaChange.subscribe(cittaSpy);
    fixture.componentInstance.zonaChange.subscribe(zonaSpy);

    setFieldValue('#cra-base-citta', 'Napoli');
    setFieldValue('#cra-base-zona', 'Centro');

    expect(cittaSpy).toHaveBeenCalledWith('Napoli');
    expect(zonaSpy).toHaveBeenCalledWith('Centro');
  });

  it('senza data mostra un placeholder onesto (non una tabella con righe inventate)', () => {
    expect(fixture.nativeElement.querySelector('.cra-base-table tbody tr')).toBeNull();
    expect(fixture.nativeElement.textContent).toContain('Inserisci i parametri');
  });

  it('con data mostra la tabella POI · Hazard · Categoria via buildBaseRows', () => {
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

  it('footer "nessuna narrativa" sempre presente, con o senza dati', () => {
    const FOOTER = 'nessuna narrativa — il sistema base restituisce solo dati strutturati';
    expect(fixture.nativeElement.textContent).toContain(FOOTER);
    fixture.componentRef.setInput('data', dataWithRows);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(FOOTER);
  });

  it('fedeltà ai vincoli di posizionamento: niente confidence/colori/pattuglia nella tabella', () => {
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

  describe('#318/#335 (reperto review C1): punto morto senza area scelta', () => {
    it("senza area mostra l'invito a compilare città/zona o tornare a Completo, e un bottone dedicato", () => {
      fixture.componentRef.setInput('area', null);
      fixture.detectChanges();

      const text = fixture.nativeElement.textContent;
      expect(text).toContain('Torna a Completo');
      expect(text).not.toContain('Disegna un cerchio sulla mappa');
    });

    it('il bottone "Torna a Completo" emette backToCompleto', () => {
      fixture.componentRef.setInput('area', null);
      fixture.detectChanges();

      const spy = jest.fn();
      fixture.componentInstance.backToCompleto.subscribe(spy);
      const buttons: HTMLButtonElement[] = Array.from(
        fixture.nativeElement.querySelectorAll('button'),
      );
      buttons.find((b) => b.textContent?.trim() === 'Torna a Completo')!.click();

      expect(spy).toHaveBeenCalledTimes(1);
    });

    it('con un cerchio disegnato torna al messaggio originale, niente bottone "Torna a Completo"', () => {
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

    it('con città/zona compilate stessa cosa: niente bottone "Torna a Completo"', () => {
      fixture.componentRef.setInput('area', { kind: 'zone', citta: 'Roma', zona: 'Colosseo' });
      fixture.detectChanges();

      const text = fixture.nativeElement.textContent;
      expect(text).toContain('città e zona inserite qui sotto');
      expect(text).not.toContain('Torna a Completo');
    });
  });

  describe('gestione errore/retry (bloccante 2 review #67: il retry resta dentro questo pannello)', () => {
    it("mostra il messaggio d'errore server (serverError) quando presente", () => {
      fixture.componentRef.setInput('serverError', '"Atlantide" non corrisponde ad alcuna area.');
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('non corrisponde ad alcuna area');
    });

    it('errore server con area in modalità città/zona: il bordo d’errore va sul campo zona', () => {
      fixture.componentRef.setInput('area', { kind: 'zone', citta: 'Roma', zona: 'Atlantide' });
      fixture.componentRef.setInput('serverError', '"Atlantide" non trovata.');
      fixture.detectChanges();
      const zonaField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-base-zona');
      expect(zonaField.classList).toContain('cra-field-error');
    });

    it('il form resta invariato e riutilizzabile dopo un errore server: un nuovo submit richiama ancora analyzeBaseline', () => {
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

    it('BLOCCANTE (reperto review): un submit vuoto mostra "Inserisci una città.", ma disegnare un cerchio subito dopo azzera l’errore', () => {
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

    it('BLOCCANTE (reperto review): un 503 in modalità cerchio non resta agganciato al campo zona dopo aver digitato una NUOVA città/zona', () => {
      fixture.componentRef.setInput('area', {
        kind: 'circle',
        center: { lat: 41.9, lon: 12.5 },
        radiusM: 500,
      });
      fixture.componentRef.setInput('serverError', 'Servizio di geocoding non raggiungibile.');
      fixture.detectChanges();

      fixture.componentRef.setInput('area', { kind: 'zone', citta: 'Roma', zona: 'Colosseo' });
      fixture.detectChanges();

      const zonaField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-base-zona');
      expect(zonaField.classList).not.toContain('cra-field-error');
    });

    it('un errore server sulla STESSA area città/zona (retry senza modificare i campi) resta agganciato al campo zona', () => {
      const zoneArea = { kind: 'zone' as const, citta: 'Roma', zona: 'Atlantide' };
      fixture.componentRef.setInput('area', zoneArea);
      fixture.componentRef.setInput('serverError', '"Atlantide" non trovata.');
      fixture.detectChanges();

      fixture.componentRef.setInput('serverError', '"Atlantide" non trovata.');
      fixture.detectChanges();

      const zonaField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-base-zona');
      expect(zonaField.classList).toContain('cra-field-error');
    });
  });
});
