import { ComponentFixture, TestBed } from '@angular/core/testing';
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

  function submitForm(): void {
    const form: HTMLFormElement = fixture.nativeElement.querySelector('form');
    form.dispatchEvent(new Event('submit', { cancelable: true }));
  }

  function setTipoPoi(value: string): void {
    const input: HTMLInputElement = fixture.nativeElement.querySelector('#cra-base-tipo-poi');
    input.value = value;
    input.dispatchEvent(new Event('input'));
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [BasePanelComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(BasePanelComponent);
    fixture.detectChanges();
  });

  it('mostra il form "Parametri ricerca" con il campo Tipo POI opzionale', () => {
    expect(fixture.nativeElement.querySelector('#cra-base-tipo-poi')).toBeTruthy();
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

  it('il bottone Cerca è disabilitato senza un cerchio disegnato', () => {
    fixture.componentRef.setInput('circle', null);
    fixture.detectChanges();
    const btn: HTMLButtonElement = fixture.nativeElement.querySelector('button[type="submit"]');
    expect(btn.disabled).toBe(true);
  });

  it('il bottone Cerca è abilitato quando un cerchio è stato disegnato', () => {
    fixture.componentRef.setInput('circle', { lat: 41.9, lon: 12.5, radiusM: 500 });
    fixture.detectChanges();
    const btn: HTMLButtonElement = fixture.nativeElement.querySelector('button[type="submit"]');
    expect(btn.disabled).toBe(false);
  });

  it('submit con cerchio disegnato emette analyzeBaseline con BaselineParams (tipo_poi assente se vuoto)', () => {
    const spy = jest.fn();
    fixture.componentInstance.analyzeBaseline.subscribe(spy);
    fixture.componentRef.setInput('circle', { lat: 41.9, lon: 12.5, radiusM: 500 });
    fixture.detectChanges();
    submitForm();
    expect(spy).toHaveBeenCalledWith({
      center: { lat: 41.9, lon: 12.5 },
      radiusM: 500,
    });
  });

  it('include tipo_poi (trimmato) quando valorizzato', () => {
    const spy = jest.fn();
    fixture.componentInstance.analyzeBaseline.subscribe(spy);
    fixture.componentRef.setInput('circle', { lat: 41.9, lon: 12.5, radiusM: 500 });
    fixture.detectChanges();
    setTipoPoi('  Railway_station  ');
    fixture.detectChanges();
    submitForm();
    expect(spy).toHaveBeenCalledWith({
      center: { lat: 41.9, lon: 12.5 },
      radiusM: 500,
      tipo_poi: 'Railway_station',
    });
  });

  it('senza cerchio il submit non emette analyzeBaseline (guardia difensiva anche a bottone disabilitato)', () => {
    const spy = jest.fn();
    fixture.componentInstance.analyzeBaseline.subscribe(spy);
    fixture.componentRef.setInput('circle', null);
    fixture.detectChanges();
    submitForm();
    expect(spy).not.toHaveBeenCalled();
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

  describe('gestione errore/retry (bloccante 2 review #67: il retry resta dentro questo pannello)', () => {
    it("mostra il messaggio d'errore server (serverError) quando presente", () => {
      fixture.componentRef.setInput('serverError', '"Atlantide" non corrisponde ad alcuna area.');
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('non corrisponde ad alcuna area');
    });

    it('il form resta invariato e riutilizzabile dopo un errore server: un nuovo submit richiama ancora analyzeBaseline', () => {
      fixture.componentRef.setInput('serverError', '"Atlantide" non trovata.');
      fixture.detectChanges();
      const spy = jest.fn();
      fixture.componentInstance.analyzeBaseline.subscribe(spy);

      fixture.componentRef.setInput('circle', { lat: 41.9, lon: 12.5, radiusM: 500 });
      fixture.detectChanges();
      submitForm();

      expect(spy).toHaveBeenCalledWith({ center: { lat: 41.9, lon: 12.5 }, radiusM: 500 });
    });
  });
});
