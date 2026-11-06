import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HeaderControlsComponent } from './header-controls.component';
import type { AnalyzeResponse, Confidence } from '@core/models/models';

const data: AnalyzeResponse = {
  citta: 'Roma',
  zona_normalizzata: 'Colosseo',
  poi: [
    {
      id: '1',
      name: 'A',
      ontology_class: 'x',
      lat: 0,
      lon: 0,
      confidence: 'verificato',
      sparql_path: null,
      ontology_label_it: '',
      ontology_label_en: '',
    },
    {
      id: '2',
      name: 'B',
      ontology_class: 'x',
      lat: 0,
      lon: 0,
      confidence: 'verificato',
      sparql_path: null,
      ontology_label_it: '',
      ontology_label_en: '',
    },
    {
      id: '3',
      name: 'C',
      ontology_class: 'x',
      lat: 0,
      lon: 0,
      confidence: 'da_confermare',
      sparql_path: null,
      ontology_label_it: '',
      ontology_label_en: '',
    },
    {
      id: '4',
      name: 'D',
      ontology_class: 'x',
      lat: 0,
      lon: 0,
      confidence: null,
      sparql_path: null,
      ontology_label_it: '',
      ontology_label_en: '',
    },
  ],
  risk_models: [
    {
      poi_id: '1',
      poi: 'A',
      risks: [
        {
          hazard: 'h1',
          confidence: 'verificato',
          tag: 'ONTOLOGIA',
          hazard_label_it: '',
          hazard_label_en: '',
        },
      ],
    },
  ],
  narrativa: '',
  narrativa_fonti: { overview: '', ontologia: '', contesto: '', speculativo: '' },
  confidence_summary: { verificato: 4, da_confermare: 1 },
  llm_used: '',
  latenza_ms: 0,
  tokens_input: 0,
  tokens_output: 0,
  repro: { temperature: 0, seed: 0, prompt_hash: '' },
  cache_hit: false,
  fallback: false,
  contesto_hash: 'h-ctx',
};

describe('HeaderControlsComponent', () => {
  let fixture: ComponentFixture<HeaderControlsComponent>;

  function setup(
    inputs: {
      data?: AnalyzeResponse | null;
      mode?: 'full' | 'base';
      filter?: Confidence | null;
      loading?: boolean;
    } = {},
  ): void {
    fixture = TestBed.createComponent(HeaderControlsComponent);
    fixture.componentRef.setInput('data', inputs.data ?? null);
    fixture.componentRef.setInput('mode', inputs.mode ?? 'full');
    fixture.componentRef.setInput('filter', inputs.filter ?? null);
    fixture.componentRef.setInput('loading', inputs.loading ?? false);
    fixture.detectChanges();
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [HeaderControlsComponent],
    }).compileComponents();
  });

  it('the Full/Base toggle is always present, even without data (to be able to enter Base from scratch)', () => {
    setup({ data: null });
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Completo');
    expect(text).toContain('Base');
  });

  it('click on "Base" emits toggleMode(\'base\')', () => {
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

  it('click on "Completo" emits toggleMode(\'full\')', () => {
    setup({ mode: 'base' });
    const spy = jest.fn();
    fixture.componentInstance.toggleMode.subscribe(spy);
    const buttons: HTMLButtonElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-mode-btn'),
    );
    const fullBtn = buttons.find((b) => b.textContent?.trim() === 'Completo')!;
    fullBtn.click();
    expect(spy).toHaveBeenCalledWith('full');
  });

  it('the active mode is marked (aria-pressed)', () => {
    setup({ mode: 'full' });
    const buttons: HTMLButtonElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-mode-btn'),
    );
    const fullBtn = buttons.find((b) => b.textContent?.trim() === 'Completo')!;
    const baseBtn = buttons.find((b) => b.textContent?.trim() === 'Base')!;
    expect(fullBtn.getAttribute('aria-pressed')).toBe('true');
    expect(baseBtn.getAttribute('aria-pressed')).toBe('false');
  });

  it('without data it shows neither the Copertura badge nor the confidence chips', () => {
    setup({ data: null });
    expect(fixture.nativeElement.textContent).not.toContain('Copertura');
    expect(fixture.nativeElement.querySelectorAll('.cra-chip').length).toBe(0);
  });

  it('in base mode it shows neither the Copertura badge nor the confidence chips (even with data present)', () => {
    setup({ data, mode: 'base' });
    expect(fixture.nativeElement.textContent).not.toContain('Copertura');
    expect(fixture.nativeElement.querySelectorAll('.cra-chip').length).toBe(0);
  });

  it('with data in full mode it shows the qualitative Copertura badge (via deriveCoverage/coverageBadgeText, of the 4 fixture POIs 3 have non-null confidence)', () => {
    setup({ data, mode: 'full' });
    expect(fixture.nativeElement.textContent).toContain(
      'Copertura: 3 POI su 4 coperti da ontologia',
    );
  });

  it('shows the confidence chips with the POI count (not the risk count) per level; #220: only 2 levels, POI D outside the ontology (confidence null) has no category of its own', () => {
    setup({ data, mode: 'full' });
    const chips: HTMLButtonElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-chip'),
    );
    expect(chips.length).toBe(2);
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Identificato');
    expect(text).toContain('2');
    expect(text).toContain('Anonimo');
  });

  it('click on a chip emits setFilter; clicking the active chip again emits clearFilter', () => {
    setup({ data, mode: 'full' });
    const setSpy = jest.fn();
    const clearSpy = jest.fn();
    fixture.componentInstance.setFilter.subscribe(setSpy);
    fixture.componentInstance.clearFilter.subscribe(clearSpy);

    const chips: HTMLButtonElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-chip'),
    );
    chips[0].click();
    expect(setSpy).toHaveBeenCalledWith('verificato');

    fixture.componentRef.setInput('filter', 'verificato');
    fixture.detectChanges();
    const chipsAfter: HTMLButtonElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-chip'),
    );
    chipsAfter[0].click();
    expect(clearSpy).toHaveBeenCalled();
  });

  it('aria-pressed on the chips reflects the active filter', () => {
    setup({ data, mode: 'full', filter: 'da_confermare' });
    const chips: HTMLButtonElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-chip'),
    );
    expect(chips[0].getAttribute('aria-pressed')).toBe('false');
    expect(chips[1].getAttribute('aria-pressed')).toBe('true');
  });

  describe('BLOCKER A (review #67-bis): the Full/Base toggle is disabled during LOADING', () => {
    it('the toggle buttons are disabled when loading=true', () => {
      setup({ loading: true });
      const buttons: HTMLButtonElement[] = Array.from(
        fixture.nativeElement.querySelectorAll('.cra-mode-btn'),
      );
      expect(buttons.length).toBeGreaterThan(0);
      expect(buttons.every((b) => b.disabled)).toBe(true);
    });

    it('the toggle buttons are enabled when loading=false (default)', () => {
      setup({ loading: false });
      const buttons: HTMLButtonElement[] = Array.from(
        fixture.nativeElement.querySelectorAll('.cra-mode-btn'),
      );
      expect(buttons.every((b) => !b.disabled)).toBe(true);
    });

    it('a click on a disabled button does not emit toggleMode (the native disabled blocks the click)', () => {
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

  describe('confidence chips during LOADING (#491)', () => {
    it('are disabled while loading and enabled otherwise', () => {
      setup({ data, loading: true });
      const chips: HTMLButtonElement[] = Array.from(
        fixture.nativeElement.querySelectorAll('.cra-chip'),
      );
      expect(chips.length).toBeGreaterThan(0);
      expect(chips.every((c) => c.disabled)).toBe(true);
    });

    it('are enabled when not loading', () => {
      setup({ data, loading: false });
      const chips: HTMLButtonElement[] = Array.from(
        fixture.nativeElement.querySelectorAll('.cra-chip'),
      );
      expect(chips.every((c) => !c.disabled)).toBe(true);
    });
  });
});
