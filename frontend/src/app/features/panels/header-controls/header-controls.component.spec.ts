import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HeaderControlsComponent } from './header-controls.component';
import type { AnalyzeResponse } from '@core/models/models';

const data: AnalyzeResponse = {
  citta: 'Roma',
  zona_normalizzata: 'Colosseo',
  poi: [
    {
      id: '1',
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
      id: '2',
      name: 'B',
      terminus_class: 'x',
      lat: 0,
      lon: 0,
      confidence: 'confermato',
      sparql_path: null,
      terminus_label_it: '',
      terminus_label_en: '',
    },
    {
      id: '3',
      name: 'C',
      terminus_class: 'x',
      lat: 0,
      lon: 0,
      confidence: 'plausibile',
      sparql_path: null,
      terminus_label_it: '',
      terminus_label_en: '',
    },
    {
      id: '4',
      name: 'D',
      terminus_class: 'x',
      lat: 0,
      lon: 0,
      confidence: 'speculativo',
      sparql_path: null,
      terminus_label_it: '',
      terminus_label_en: '',
    },
  ],
  risk_models: [
    {
      poi: 'A',
      risks: [
        {
          hazard: 'h1',
          confidence: 'confermato',
          tag: 'ONTOLOGIA',
          hazard_label_it: '',
          hazard_label_en: '',
        },
      ],
    },
  ],
  narrativa: '',
  narrativa_fonti: { overview: '', ontologia: '', contesto: '', speculativo: '' },
  confidence_summary: { confermato: 3, plausibile: 1, speculativo: 1 },
  llm_used: '',
  latenza_ms: 0,
  tokens_input: 0,
  tokens_output: 0,
  repro: { temperature: 0, seed: 0, prompt_hash: '' },
  cache_hit: false,
  fallback: false,
};

describe('HeaderControlsComponent', () => {
  let fixture: ComponentFixture<HeaderControlsComponent>;

  function setup(
    inputs: {
      data?: AnalyzeResponse | null;
      mode?: 'completo' | 'base';
      filter?: 'confermato' | 'plausibile' | 'speculativo' | null;
      loading?: boolean;
    } = {},
  ): void {
    fixture = TestBed.createComponent(HeaderControlsComponent);
    fixture.componentRef.setInput('data', inputs.data ?? null);
    fixture.componentRef.setInput('mode', inputs.mode ?? 'completo');
    fixture.componentRef.setInput('filter', inputs.filter ?? null);
    fixture.componentRef.setInput('loading', inputs.loading ?? false);
    fixture.detectChanges();
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [HeaderControlsComponent],
    }).compileComponents();
  });

  it('il toggle Completo/Base è sempre presente, anche senza dati (per poter entrare in Base da zero)', () => {
    setup({ data: null });
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Completo');
    expect(text).toContain('Base');
  });

  it('click su "Base" emette toggleMode(\'base\')', () => {
    setup();
    const spy = jest.fn();
    fixture.componentInstance.toggleMode.subscribe(spy);
    const buttons: HTMLButtonElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-mode-btn'),
    );
    const baseBtn = buttons.find((b) => b.textContent?.trim() === 'Base')!;
    baseBtn.click();
    expect(spy).toHaveBeenCalledWith('base');
  });

  it('click su "Completo" emette toggleMode(\'completo\')', () => {
    setup({ mode: 'base' });
    const spy = jest.fn();
    fixture.componentInstance.toggleMode.subscribe(spy);
    const buttons: HTMLButtonElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-mode-btn'),
    );
    const completoBtn = buttons.find((b) => b.textContent?.trim() === 'Completo')!;
    completoBtn.click();
    expect(spy).toHaveBeenCalledWith('completo');
  });

  it('la modalità attiva è marcata (aria-pressed)', () => {
    setup({ mode: 'completo' });
    const buttons: HTMLButtonElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-mode-btn'),
    );
    const completoBtn = buttons.find((b) => b.textContent?.trim() === 'Completo')!;
    const baseBtn = buttons.find((b) => b.textContent?.trim() === 'Base')!;
    expect(completoBtn.getAttribute('aria-pressed')).toBe('true');
    expect(baseBtn.getAttribute('aria-pressed')).toBe('false');
  });

  it('senza dati non mostra badge Copertura né chip confidence', () => {
    setup({ data: null });
    expect(fixture.nativeElement.textContent).not.toContain('Copertura');
    expect(fixture.nativeElement.querySelectorAll('.cra-chip').length).toBe(0);
  });

  it('in modalità base non mostra badge Copertura né chip confidence (anche con dati presenti)', () => {
    setup({ data, mode: 'base' });
    expect(fixture.nativeElement.textContent).not.toContain('Copertura');
    expect(fixture.nativeElement.querySelectorAll('.cra-chip').length).toBe(0);
  });

  it('con dati in modalità completo mostra il badge Copertura qualitativo (via deriveCoverage/coverageBadgeText, somma confidence_summary = 5, non il conteggio POI)', () => {
    setup({ data, mode: 'completo' });
    expect(fixture.nativeElement.textContent).toContain(
      'Copertura 5 rischi · 1 ancorati a ontologia',
    );
  });

  it('mostra i chip confidence con il conteggio dei POI (non dei rischi) per livello', () => {
    setup({ data, mode: 'completo' });
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Confermato');
    expect(text).toContain('2');
    expect(text).toContain('Plausibile');
    expect(text).toContain('Speculativo');
  });

  it('click su un chip emette setFilter; riclic sul chip attivo emette clearFilter', () => {
    setup({ data, mode: 'completo' });
    const setSpy = jest.fn();
    const clearSpy = jest.fn();
    fixture.componentInstance.setFilter.subscribe(setSpy);
    fixture.componentInstance.clearFilter.subscribe(clearSpy);

    const chips: HTMLButtonElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-chip'),
    );
    chips[0].click();
    expect(setSpy).toHaveBeenCalledWith('confermato');

    fixture.componentRef.setInput('filter', 'confermato');
    fixture.detectChanges();
    const chipsAfter: HTMLButtonElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-chip'),
    );
    chipsAfter[0].click();
    expect(clearSpy).toHaveBeenCalled();
  });

  it('aria-pressed sui chip riflette il filtro attivo', () => {
    setup({ data, mode: 'completo', filter: 'plausibile' });
    const chips: HTMLButtonElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-chip'),
    );
    expect(chips[0].getAttribute('aria-pressed')).toBe('false');
    expect(chips[1].getAttribute('aria-pressed')).toBe('true');
  });

  describe('BLOCCANTE A (review #67-bis): il toggle Completo/Base è disabilitato durante LOADING', () => {
    it('i bottoni del toggle sono disabilitati quando loading=true', () => {
      setup({ loading: true });
      const buttons: HTMLButtonElement[] = Array.from(
        fixture.nativeElement.querySelectorAll('.cra-mode-btn'),
      );
      expect(buttons.length).toBeGreaterThan(0);
      expect(buttons.every((b) => b.disabled)).toBe(true);
    });

    it('i bottoni del toggle sono abilitati quando loading=false (default)', () => {
      setup({ loading: false });
      const buttons: HTMLButtonElement[] = Array.from(
        fixture.nativeElement.querySelectorAll('.cra-mode-btn'),
      );
      expect(buttons.every((b) => !b.disabled)).toBe(true);
    });

    it('un click su un bottone disabilitato non emette toggleMode (il disabled nativo blocca il click)', () => {
      setup({ loading: true });
      const spy = jest.fn();
      fixture.componentInstance.toggleMode.subscribe(spy);
      const buttons: HTMLButtonElement[] = Array.from(
        fixture.nativeElement.querySelectorAll('.cra-mode-btn'),
      );
      buttons.forEach((b) => b.click());
      expect(spy).not.toHaveBeenCalled();
    });
  });
});
