import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NarrativeSheetComponent } from './narrative-sheet.component';
import type { RiskModel, SourceProse } from '@core/models/models';

const riskModels: RiskModel[] = [
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
      {
        hazard: 'h-ctx',
        confidence: 'plausibile',
        tag: 'CONTESTO',
        hazard_label_it: 'Contesto',
        hazard_label_en: 'Context',
      },
    ],
  },
];

const narrativaFonti: SourceProse = {
  overview: 'Sintesi generale della zona.',
  ontologia: 'Prosa ancorata alla ontologia formale.',
  contesto: 'Prosa dal contesto ambientale osservato.',
  speculativo: 'Ipotesi speculativa non ancorata.',
};

const ANTI_HALLUCINATION_TEXT = 'supporto decisionale · valuta con fonti primarie';

describe('NarrativeSheetComponent', () => {
  let fixture: ComponentFixture<NarrativeSheetComponent>;

  function setup(
    inputs: {
      citta?: string;
      zona?: string;
      narrativa?: string;
      narrativaFonti?: SourceProse | null;
      riskModels?: RiskModel[];
      open?: boolean;
    } = {},
  ): void {
    fixture = TestBed.createComponent(NarrativeSheetComponent);
    fixture.componentRef.setInput('citta', inputs.citta ?? 'Roma');
    fixture.componentRef.setInput('zona', inputs.zona ?? 'Colosseo');
    fixture.componentRef.setInput('narrativa', inputs.narrativa ?? 'Testo narrativo di prova.');
    fixture.componentRef.setInput(
      'narrativaFonti',
      inputs.narrativaFonti !== undefined ? inputs.narrativaFonti : narrativaFonti,
    );
    fixture.componentRef.setInput('riskModels', inputs.riskModels ?? riskModels);
    fixture.componentRef.setInput('open', inputs.open ?? true);
    fixture.detectChanges();
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [NarrativeSheetComponent],
    }).compileComponents();
  });

  it('mostra il titolo con città e zona', () => {
    setup({ citta: 'Milano', zona: 'Duomo' });
    expect(fixture.nativeElement.textContent).toContain('Milano · Duomo');
  });

  it('ACCEPTANCE: il banner anti-hallucination è presente quando aperto', () => {
    setup({ open: true });
    expect(fixture.nativeElement.textContent).toContain(ANTI_HALLUCINATION_TEXT);
  });

  it('ACCEPTANCE (fail-if-removed): il banner anti-hallucination resta presente anche da collassato — non deve mai sparire', () => {
    setup({ open: false });
    expect(fixture.nativeElement.textContent).toContain(ANTI_HALLUCINATION_TEXT);
  });

  it("click sull'header emette toggleNarrative", () => {
    setup();
    const spy = jest.fn();
    fixture.componentInstance.toggleNarrative.subscribe(spy);
    (fixture.nativeElement.querySelector('.cra-narr-header') as HTMLElement).click();
    expect(spy).toHaveBeenCalled();
  });

  it('click su Rigenera emette regenerate e NON anche toggleNarrative (stopPropagation)', () => {
    setup();
    const toggleSpy = jest.fn();
    const regenSpy = jest.fn();
    fixture.componentInstance.toggleNarrative.subscribe(toggleSpy);
    fixture.componentInstance.regenerate.subscribe(regenSpy);
    (fixture.nativeElement.querySelector('.cra-btn-regen') as HTMLElement).click();
    expect(regenSpy).toHaveBeenCalled();
    expect(toggleSpy).not.toHaveBeenCalled();
  });

  it('da aperto mostra overview + tab per fonte in ordine ONTOLOGIA→CONTESTO→SPECULATIVO, il primo attivo', () => {
    setup();
    expect(fixture.nativeElement.textContent).toContain('Sintesi generale della zona.');
    const tabs = fixture.nativeElement.querySelectorAll('[role="tab"]');
    expect(tabs.length).toBe(3);
    expect(tabs[0].getAttribute('aria-selected')).toBe('true');
    expect(tabs[1].getAttribute('aria-selected')).toBe('false');
    expect(tabs[2].getAttribute('aria-selected')).toBe('false');
    // FIX 1 (review Task 4): tutti i pannelli sono nel DOM (aria-controls dei tab non attivi
    // deve risolvere a un id esistente), solo quello attivo è visibile (non `hidden`).
    const panels: HTMLElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('[role="tabpanel"]'),
    );
    expect(panels.length).toBe(3);
    expect(panels.filter((p) => !p.hidden).length).toBe(1);
    expect(panels[0].hidden).toBe(false);
    expect(fixture.nativeElement.textContent).toContain('Prosa ancorata alla ontologia formale.');
    expect(fixture.nativeElement.textContent).toContain('Borseggio');
  });

  it('a11y: ogni aria-controls dei tab risolve a un id di tabpanel esistente; il pannello attivo ha tabindex 0, gli altri sono hidden', () => {
    setup();
    const tabs: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('[role="tab"]'));
    for (const tab of tabs) {
      const controlsId = tab.getAttribute('aria-controls');
      const panel = fixture.nativeElement.querySelector(`#${controlsId}`) as HTMLElement | null;
      expect(panel).not.toBeNull();
    }
    const panels: HTMLElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('[role="tabpanel"]'),
    );
    const active = panels.find((p) => !p.hidden);
    expect(active?.getAttribute('tabindex')).toBe('0');
    for (const p of panels) {
      if (p !== active) {
        expect(p.hidden).toBe(true);
        expect(p.hasAttribute('tabindex')).toBe(false);
      }
    }
  });

  it('click sul secondo tab lo attiva e mostra la sua prosa/hazard', () => {
    setup();
    const tabs: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('[role="tab"]'));
    tabs[1].click();
    fixture.detectChanges();
    const tabsAfter: HTMLElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('[role="tab"]'),
    );
    expect(tabsAfter[1].getAttribute('aria-selected')).toBe('true');
    expect(tabsAfter[0].getAttribute('aria-selected')).toBe('false');
    expect(fixture.nativeElement.textContent).toContain('Prosa dal contesto ambientale osservato.');
    expect(fixture.nativeElement.textContent).toContain('Contesto');
  });

  it('ArrowRight sul primo tab sposta il focus/attivo al secondo', () => {
    setup();
    const tabs: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('[role="tab"]'));
    tabs[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    fixture.detectChanges();
    const tabsAfter: HTMLElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('[role="tab"]'),
    );
    expect(tabsAfter[1].getAttribute('aria-selected')).toBe('true');
    expect(tabsAfter[0].getAttribute('aria-selected')).toBe('false');
  });

  it("ArrowLeft sul primo tab avvolge (wrap) e attiva l'ultimo", () => {
    setup();
    const tabs: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('[role="tab"]'));
    tabs[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    fixture.detectChanges();
    const tabsAfter: HTMLElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('[role="tab"]'),
    );
    expect(tabsAfter[2].getAttribute('aria-selected')).toBe('true');
  });

  it("End sul primo tab attiva l'ultimo, Home lo riporta al primo", () => {
    setup();
    const tabs: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('[role="tab"]'));
    tabs[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true }));
    fixture.detectChanges();
    let tabsAfter: HTMLElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('[role="tab"]'),
    );
    expect(tabsAfter[2].getAttribute('aria-selected')).toBe('true');

    tabsAfter[2].dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true }));
    fixture.detectChanges();
    tabsAfter = Array.from(fixture.nativeElement.querySelectorAll('[role="tab"]'));
    expect(tabsAfter[0].getAttribute('aria-selected')).toBe('true');
  });

  it('un tasto non gestito sul tab non cambia il tab attivo', () => {
    setup();
    const tabs: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('[role="tab"]'));
    tabs[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
    fixture.detectChanges();
    const tabsAfter: HTMLElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('[role="tab"]'),
    );
    expect(tabsAfter[0].getAttribute('aria-selected')).toBe('true');
  });

  it("premere Spazio sull'header emette toggleNarrative e previene il default (scroll pagina)", () => {
    setup();
    const spy = jest.fn();
    fixture.componentInstance.toggleNarrative.subscribe(spy);
    const header = fixture.nativeElement.querySelector('.cra-narr-header') as HTMLElement;
    const event = new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true });
    header.dispatchEvent(event);
    expect(spy).toHaveBeenCalled();
  });

  it('senza risk_models e senza narrativaFonti non fallisce e non mostra tab', () => {
    expect(() =>
      setup({
        riskModels: [],
        narrativaFonti: { overview: '', ontologia: '', contesto: '', speculativo: '' },
      }),
    ).not.toThrow();
    expect(fixture.nativeElement.querySelectorAll('[role="tab"]').length).toBe(0);
  });

  it('FIX 3: overview vuoto ma tab presenti — nessun lead (niente duplicazione della prosa)', () => {
    setup({
      narrativaFonti: {
        overview: '',
        ontologia: 'Prosa ancorata alla ontologia formale.',
        contesto: 'Prosa dal contesto ambientale osservato.',
        speculativo: 'Ipotesi speculativa non ancorata.',
      },
      narrativa: 'Testo narrativo di prova.',
    });
    expect(fixture.nativeElement.querySelector('.cra-narr-lead')).toBeNull();
    expect(fixture.nativeElement.querySelectorAll('[role="tab"]').length).toBe(3);
  });

  it('FIX 4: se il tag attivo scompare dal nuovo set di tab, activeTab degrada al primo del nuovo set (nessun pannello vuoto)', () => {
    setup();
    const tabs: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('[role="tab"]'));
    tabs[1].click(); // seleziona CONTESTO (secondo tab)
    fixture.detectChanges();
    let tabsAfter: HTMLElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('[role="tab"]'),
    );
    expect(tabsAfter[1].getAttribute('aria-selected')).toBe('true');

    // Nuovo set di dati: solo SPECULATIVO (CONTESTO, il tag attivo, sparisce).
    fixture.componentRef.setInput('riskModels', [
      {
        poi: 'Duomo',
        risks: [
          {
            hazard: 'h-spec-2',
            confidence: 'speculativo' as const,
            tag: 'SPECULATIVO' as const,
            hazard_label_it: 'Nuova ipotesi',
            hazard_label_en: 'New hypothesis',
          },
        ],
      },
    ]);
    fixture.componentRef.setInput('narrativaFonti', {
      overview: '',
      ontologia: '',
      contesto: '',
      speculativo: 'Nuova prosa speculativa.',
    });
    fixture.detectChanges();

    tabsAfter = Array.from(fixture.nativeElement.querySelectorAll('[role="tab"]'));
    expect(tabsAfter.length).toBe(1);
    expect(tabsAfter[0].getAttribute('aria-selected')).toBe('true');
    const panels: HTMLElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('[role="tabpanel"]'),
    );
    expect(panels.length).toBe(1);
    expect(panels[0].hidden).toBe(false);
    expect(fixture.nativeElement.textContent).toContain('Nuova prosa speculativa.');
    expect(fixture.nativeElement.textContent).toContain('Nuova ipotesi');
  });

  it('fallback: senza overview/prosa/riskModels mostra narrativa() legacy e nessun tab', () => {
    setup({
      riskModels: [],
      narrativaFonti: { overview: '', ontologia: '', contesto: '', speculativo: '' },
      narrativa: 'Narrativa legacy senza fonti strutturate.',
    });
    expect(fixture.nativeElement.textContent).toContain(
      'Narrativa legacy senza fonti strutturate.',
    );
    expect(fixture.nativeElement.querySelectorAll('[role="tab"]').length).toBe(0);
  });

  it('da collassato non rende il corpo (overview/tab nascosti, altezza ridotta)', () => {
    setup({ open: false });
    expect(fixture.nativeElement.querySelector('.cra-narr-body')).toBeNull();
  });
});
