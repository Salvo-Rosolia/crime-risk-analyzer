import { ComponentFixture, TestBed } from '@angular/core/testing';
import { BasePanelComponent } from './base-panel.component';
import { ApiService } from '@core/api/api.service';
import type { AnalyzeResponse } from '@core/models/models';

const dataWithRows: AnalyzeResponse = {
  citta: 'Roma',
  zona_normalizzata: 'Colosseo',
  poi: [
    { id: '1', name: 'Colosseo', terminus_class: 'Archaeological_site', lat: 0, lon: 0, confidence: 'confermato', sparql_path: null, terminus_label_it: 'Sito archeologico', terminus_label_en: 'Archaeological site' },
  ],
  risk_models: [
    { poi: 'Colosseo', risks: [
      { hazard: 'h1', confidence: 'confermato', tag: 'ONTOLOGIA', hazard_label_it: 'Borseggio', hazard_label_en: 'Pickpocketing' },
      { hazard: 'h2', confidence: 'speculativo', tag: 'SPECULATIVO', hazard_label_it: 'Ipotesi', hazard_label_en: 'Hypothesis' },
    ] },
  ],
  narrativa: '',
  confidence_summary: { confermato: 1, plausibile: 0, speculativo: 1 },
  llm_used: '', latenza_ms: 0, tokens_input: 0, tokens_output: 0,
  repro: { temperature: 0, seed: 0, prompt_hash: '' },
  cache_hit: false, fallback: false,
};

describe('BasePanelComponent', () => {
  let fixture: ComponentFixture<BasePanelComponent>;
  let api: { cities: jest.Mock };

  function setZona(value: string): void {
    const input: HTMLInputElement = fixture.nativeElement.querySelector('#cra-base-zona');
    input.value = value;
    input.dispatchEvent(new Event('input'));
  }

  function setCitta(value: string): void {
    const select: HTMLSelectElement = fixture.nativeElement.querySelector('#cra-base-citta');
    select.value = value;
    select.dispatchEvent(new Event('change'));
  }

  function submitForm(): void {
    const form: HTMLFormElement = fixture.nativeElement.querySelector('form');
    form.dispatchEvent(new Event('submit', { cancelable: true }));
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

  it('mostra il form "Parametri ricerca" con Tipo POI, Città (dropdown da cities()) e Zona', () => {
    expect(api.cities).toHaveBeenCalled();
    const options = fixture.nativeElement.querySelectorAll('#cra-base-citta option:not([value=""])');
    expect(Array.from(options).map(o => (o as HTMLOptionElement).value)).toEqual(['Roma', 'Milano']);
    expect(fixture.nativeElement.querySelector('#cra-base-tipo-poi')).toBeTruthy();
    expect(fixture.nativeElement.querySelector('#cra-base-zona')).toBeTruthy();
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

  it('submit senza città/zona non emette search e mostra l\'errore di validazione', () => {
    const spy = jest.fn();
    fixture.componentInstance.analyzeBaseline.subscribe(spy);
    submitForm();
    fixture.detectChanges();
    expect(spy).not.toHaveBeenCalled();
    expect(fixture.nativeElement.textContent).toContain('Seleziona una città');
  });

  it('submit con città+zona valide emette search con BaselineParams (tipo_poi assente se vuoto)', () => {
    const spy = jest.fn();
    fixture.componentInstance.analyzeBaseline.subscribe(spy);
    setCitta('Roma');
    setZona('Colosseo');
    fixture.detectChanges();
    submitForm();
    expect(spy).toHaveBeenCalledWith({ citta: 'Roma', zona: 'Colosseo' });
  });

  it('include tipo_poi (trimmato) quando valorizzato', () => {
    const spy = jest.fn();
    fixture.componentInstance.analyzeBaseline.subscribe(spy);
    setCitta('Roma');
    setZona('Colosseo');
    const tipoPoi: HTMLInputElement = fixture.nativeElement.querySelector('#cra-base-tipo-poi');
    tipoPoi.value = '  Railway_station  ';
    tipoPoi.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    submitForm();
    expect(spy).toHaveBeenCalledWith({ citta: 'Roma', zona: 'Colosseo', tipo_poi: 'Railway_station' });
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
    expect(text).not.toContain('Confermato');
    expect(text).not.toContain('Speculativo');
    expect(text).not.toContain('Assegna pattuglia');
    expect(fixture.nativeElement.querySelectorAll('.cra-base-table [style*="color"]').length).toBe(0);
  });

  describe('gestione errore/retry (bloccante 2 review #67: il retry resta dentro questo pannello)', () => {
    it('mostra il messaggio d\'errore server (serverError) quando presente', () => {
      fixture.componentRef.setInput('serverError', '"Atlantide" non corrisponde ad alcuna area.');
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('non corrisponde ad alcuna area');
    });

    it('la validazione client ha priorità sul messaggio server quando entrambi sono presenti (stessa convenzione di InputPanelComponent)', () => {
      fixture.componentRef.setInput('serverError', 'errore server');
      fixture.detectChanges();
      submitForm();
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('Seleziona una città');
      expect(fixture.nativeElement.textContent).not.toContain('errore server');
    });

    it('il form resta invariato e riutilizzabile dopo un errore server: un nuovo submit richiama ancora analyzeBaseline', () => {
      fixture.componentRef.setInput('serverError', '"Atlantide" non trovata.');
      fixture.detectChanges();
      const spy = jest.fn();
      fixture.componentInstance.analyzeBaseline.subscribe(spy);

      setCitta('Roma');
      setZona('Atlantide');
      fixture.detectChanges();
      submitForm();

      expect(spy).toHaveBeenCalledWith({ citta: 'Roma', zona: 'Atlantide' });
    });
  });
});

describe('BasePanelComponent — pre-fill da initialCitta/initialZona (retry dopo remount)', () => {
  let fixture: ComponentFixture<BasePanelComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [BasePanelComponent],
      providers: [{ provide: ApiService, useValue: { cities: jest.fn().mockResolvedValue(['Roma']) } }],
    }).compileComponents();
    fixture = TestBed.createComponent(BasePanelComponent);
  });

  it('ripopola citta/zona dagli input initial* al mount', () => {
    fixture.componentRef.setInput('initialCitta', 'Roma');
    fixture.componentRef.setInput('initialZona', 'Trastevere');
    fixture.detectChanges();

    const citta: HTMLSelectElement = fixture.nativeElement.querySelector('#cra-base-citta');
    const zona: HTMLInputElement = fixture.nativeElement.querySelector('#cra-base-zona');
    expect(citta.value).toBe('Roma');
    expect(zona.value).toBe('Trastevere');
  });
});
