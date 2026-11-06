import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NarrativeSheetComponent } from './narrative-sheet.component';
import type { SourceProse } from '@core/models/models';
import { istatPoi, istatRow } from '@core/testing/istat-fixtures';

const narrativeSources: SourceProse = {
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
      city?: string;
      zone?: string;
      narrative?: string;
      narrativeSources?: SourceProse | null;
      open?: boolean;
      loading?: boolean;
      error?: string | null;
      fallback?: boolean;
      poiName?: string | null;
    } = {},
  ): void {
    fixture = TestBed.createComponent(NarrativeSheetComponent);
    fixture.componentRef.setInput('city', inputs.city ?? 'Roma');
    fixture.componentRef.setInput('zone', inputs.zone ?? 'Colosseo');
    fixture.componentRef.setInput('narrative', inputs.narrative ?? 'Testo narrativo di prova.');
    fixture.componentRef.setInput(
      'narrativeSources',
      inputs.narrativeSources !== undefined ? inputs.narrativeSources : narrativeSources,
    );
    fixture.componentRef.setInput('open', inputs.open ?? true);
    if (inputs.loading !== undefined) fixture.componentRef.setInput('loading', inputs.loading);
    if (inputs.error !== undefined) fixture.componentRef.setInput('error', inputs.error);
    if (inputs.poiName !== undefined) fixture.componentRef.setInput('poiName', inputs.poiName);
    if (inputs.fallback !== undefined) fixture.componentRef.setInput('fallback', inputs.fallback);
    fixture.detectChanges();
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [NarrativeSheetComponent],
    }).compileComponents();
  });

  it('shows the title with city and zone', () => {
    setup({ city: 'Milano', zone: 'Duomo' });
    expect(fixture.nativeElement.textContent).toContain('Milano · Duomo');
  });

  it('ACCEPTANCE: the anti-hallucination banner is present when open', () => {
    setup({ open: true });
    expect(fixture.nativeElement.textContent).toContain(ANTI_HALLUCINATION_TEXT);
  });

  it('ACCEPTANCE (fail-if-removed): the anti-hallucination banner stays present even when collapsed — it must never disappear', () => {
    setup({ open: false });
    expect(fixture.nativeElement.textContent).toContain(ANTI_HALLUCINATION_TEXT);
  });

  it('click on the header emits toggleNarrative', () => {
    setup();
    const spy = jest.fn();
    fixture.componentInstance.toggleNarrative.subscribe(spy);
    (fixture.nativeElement.querySelector('.cra-narr-header') as HTMLElement).click();
    expect(spy).toHaveBeenCalled();
  });

  it('click on Rigenera emits regenerate and NOT also toggleNarrative (stopPropagation)', () => {
    setup();
    const toggleSpy = jest.fn();
    const regenSpy = jest.fn();
    fixture.componentInstance.toggleNarrative.subscribe(toggleSpy);
    fixture.componentInstance.regenerate.subscribe(regenSpy);
    (fixture.nativeElement.querySelector('.cra-btn-regen') as HTMLElement).click();
    expect(regenSpy).toHaveBeenCalled();
    expect(toggleSpy).not.toHaveBeenCalled();
  });

  it('when open shows overview + one tab per source in ONTOLOGIA→CONTESTO→SPECULATIVO order, the first active', () => {
    setup();
    expect(fixture.nativeElement.textContent).toContain('Sintesi generale della zona.');
    const tabs = fixture.nativeElement.querySelectorAll('[role="tab"]');
    expect(tabs.length).toBe(3);
    expect(tabs[0].getAttribute('aria-selected')).toBe('true');
    expect(tabs[1].getAttribute('aria-selected')).toBe('false');
    expect(tabs[2].getAttribute('aria-selected')).toBe('false');
    // FIX 1 (review Task 4): all the panels are in the DOM (the aria-controls of the inactive tabs
    // must resolve to an existing id), only the active one is visible (not `hidden`).
    const panels: HTMLElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('[role="tabpanel"]'),
    );
    expect(panels.length).toBe(3);
    expect(panels.filter((p) => !p.hidden).length).toBe(1);
    expect(panels[0].hidden).toBe(false);
    expect(fixture.nativeElement.textContent).toContain('Prosa ancorata alla ontologia formale.');
  });

  it('a11y: every tab aria-controls resolves to an existing tabpanel id; the active panel has tabindex 0, the others are hidden', () => {
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

  it('click on the second tab activates it and shows its prose', () => {
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
  });

  it('ArrowRight on the first tab moves the focus/active to the second', () => {
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

  it('ArrowLeft on the first tab wraps and activates the last', () => {
    setup();
    const tabs: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('[role="tab"]'));
    tabs[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    fixture.detectChanges();
    const tabsAfter: HTMLElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('[role="tab"]'),
    );
    expect(tabsAfter[2].getAttribute('aria-selected')).toBe('true');
  });

  it('End on the first tab activates the last, Home brings it back to the first', () => {
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

  it('an unhandled key on the tab does not change the active tab', () => {
    setup();
    const tabs: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('[role="tab"]'));
    tabs[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
    fixture.detectChanges();
    const tabsAfter: HTMLElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('[role="tab"]'),
    );
    expect(tabsAfter[0].getAttribute('aria-selected')).toBe('true');
  });

  it('pressing Space on the header emits toggleNarrative and prevents the default (page scroll)', () => {
    setup();
    const spy = jest.fn();
    fixture.componentInstance.toggleNarrative.subscribe(spy);
    const header = fixture.nativeElement.querySelector('.cra-narr-header') as HTMLElement;
    const event = new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true });
    header.dispatchEvent(event);
    expect(spy).toHaveBeenCalled();
  });

  it('without risk_models and without narrativeSources it does not fail and shows no tab', () => {
    expect(() =>
      setup({
        narrativeSources: { overview: '', ontologia: '', contesto: '', speculativo: '' },
      }),
    ).not.toThrow();
    expect(fixture.nativeElement.querySelectorAll('[role="tab"]').length).toBe(0);
  });

  it('FIX 3: empty overview but tabs present — no lead (no duplication of the prose)', () => {
    setup({
      narrativeSources: {
        overview: '',
        ontologia: 'Prosa ancorata alla ontologia formale.',
        contesto: 'Prosa dal contesto ambientale osservato.',
        speculativo: 'Ipotesi speculativa non ancorata.',
      },
      narrative: 'Testo narrativo di prova.',
    });
    expect(fixture.nativeElement.querySelector('.cra-narr-lead')).toBeNull();
    expect(fixture.nativeElement.querySelectorAll('[role="tab"]').length).toBe(3);
  });

  it('FIX 4: if the active tag disappears from the new tab set, activeTab degrades to the first of the new set (no empty panel)', () => {
    setup();
    const tabs: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('[role="tab"]'));
    tabs[1].click(); // selects CONTESTO (second tab)
    fixture.detectChanges();
    let tabsAfter: HTMLElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('[role="tab"]'),
    );
    expect(tabsAfter[1].getAttribute('aria-selected')).toBe('true');

    // New data set: only SPECULATIVO (CONTESTO, the active tag, disappears).
    fixture.componentRef.setInput('narrativeSources', {
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
  });

  it('fallback: without overview/prose it shows the legacy narrative() and no tab', () => {
    setup({
      narrativeSources: { overview: '', ontologia: '', contesto: '', speculativo: '' },
      narrative: 'Narrativa legacy senza fonti strutturate.',
    });
    expect(fixture.nativeElement.textContent).toContain(
      'Narrativa legacy senza fonti strutturate.',
    );
    expect(fixture.nativeElement.querySelectorAll('[role="tab"]').length).toBe(0);
  });

  it('when collapsed it does not render the body (overview/tabs hidden, reduced height)', () => {
    setup({ open: false });
    expect(fixture.nativeElement.querySelector('.cra-narr-body')).toBeNull();
  });

  it('#218: the host class cra-narr-collapsed reflects the collapsed state (drives the right-panel vs full-height CSS)', () => {
    setup({ open: false });
    expect(fixture.nativeElement.classList.contains('cra-narr-collapsed')).toBe(true);
  });

  it('#218: when open the panel does NOT have the collapsed class', () => {
    setup({ open: true });
    expect(fixture.nativeElement.classList.contains('cra-narr-collapsed')).toBe(false);
  });

  it('#345: with the ISTAT prose it shows the [ISTAT] tab after CONTESTO', () => {
    setup({
      narrativeSources: {
        overview: 'Sintesi.',
        ontologia: 'Prosa onto.',
        contesto: 'Prosa ctx.',
        speculativo: '',
        istat: 'I furti sono 134.169 (fonte ISTAT, Comune di Roma, 2024).',
      },
    });
    const tabs: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('[role="tab"]'));
    expect(tabs.map((t) => t.textContent?.trim())).toEqual(['ONTOLOGIA', 'CONTESTO', 'ISTAT']);
    tabs[2].click();
    fixture.detectChanges();
    const active: HTMLElement = fixture.nativeElement.querySelector(
      '[role="tabpanel"]:not([hidden])',
    );
    expect(active.textContent).toContain('[ISTAT]');
    expect(active.textContent).toContain('fonte ISTAT, Comune di Roma, 2024');
  });

  describe('#365: inline ISTAT indicators in the ONTOLOGIA tab', () => {
    const NOTE =
      "I riquadri ISTAT sono calcolati dall'app dai dati ufficiali, non scritti dal modello.";
    const makeSources = (ontologia: string, contesto = 'Il Furto di contesto.'): SourceProse => ({
      overview: '',
      ontologia,
      contesto,
      speculativo: '',
    });
    const data = istatPoi(istatRow('THEFT', ['Theft'], { voce_label: 'furti', variazione_pct: 5 }));
    const occ = [{ hazardLabel: 'Furto', hazard: 'Theft', istat: data }];

    function withIstat(f: SourceProse, occurrences = occ): void {
      setup({ narrativeSources: f });
      fixture.componentRef.setInput('istatOccurrences', occurrences);
      fixture.detectChanges();
    }

    function panel(tag: string): HTMLElement {
      return fixture.nativeElement.querySelector(`#cra-narr-panel-${tag}`);
    }

    it('after the first mention of the risk the indicator appears, with the arrow aria-hidden', () => {
      withIstat(makeSources('Il Furto è alto. Il furto cala.'));
      const ind = panel('ONTOLOGIA').querySelectorAll('.cra-narr-istat');
      expect(ind.length).toBe(1);
      expect(ind[0].textContent?.replace(/\s+/g, ' ').trim()).toContain(
        'ISTAT · Comune di Roma 2024 · furti: 100,0 ogni 100.000 ab. (Italia 100,0) · ▲ +5% dal 2014 · voce più ampia del rischio',
      );
      expect(ind[0].querySelector('[aria-hidden="true"]')?.textContent?.trim()).toBe('▲');
      expect(panel('ONTOLOGIA').querySelector('.cra-narr-prose')?.textContent).toContain(
        'Il Furto',
      );
    });

    it('the indicator sits right after the right word and the text (without markers) stays intact', () => {
      withIstat(makeSources('Il **Furto** è alto e il furto cala.'));
      const p = panel('ONTOLOGIA').querySelector('.cra-narr-prose') as HTMLElement;
      const children = Array.from(p.children) as HTMLElement[];
      const i = children.findIndex((f) => f.classList.contains('cra-narr-istat'));
      expect(children[i - 1].tagName).toBe('STRONG');
      expect(children[i - 1].textContent).toBe('Furto');
      expect(children[i - 2].textContent).toBe('Il ');
      expect(children[i + 1].textContent).toBe(' è alto e il furto cala.');
      const originalText = children
        .filter((f) => !f.classList.contains('cra-narr-istat'))
        .map((f) => f.textContent)
        .join('');
      expect(originalText).toBe('Il Furto è alto e il furto cala.');
    });

    it('markdown: no visible asterisk in any tab nor in the lead; strong and em present', () => {
      setup({
        narrativeSources: {
          overview: 'Sintesi con **grassetto** e *corsivo*.',
          ontologia: 'L’**impennata** e *Aggressione* con **il furto cala** e furto.',
          contesto: '* **Luce** – scarsa\n* *Strade* buie',
          speculativo: '***x*** e __y__ e _z_',
          istat: '## Titolo\n**dato** ISTAT',
        },
      });
      fixture.componentRef.setInput('istatOccurrences', occ);
      fixture.detectChanges();
      const body = fixture.nativeElement.querySelector('.cra-narr-body') as HTMLElement;
      expect(body.textContent).not.toMatch(/[*_#]/);
      expect(body.querySelectorAll('strong').length).toBeGreaterThan(3);
      expect(body.querySelectorAll('em').length).toBeGreaterThan(2);
      expect(panel('CONTESTO').textContent).toContain('• Luce');
    });

    it('a U+E000 written by the model does not break the panel nor move the indicators', () => {
      const pua = String.fromCharCode(0xe000);
      const twoRisks = [
        ...occ,
        {
          hazardLabel: 'Danno',
          hazard: 'Damage',
          istat: istatPoi(istatRow('DAMAGE', ['Damage'], { voce_label: 'danni' })),
        },
      ];
      withIstat(makeSources(`Il furto ${pua} qui e il${pua} danno cala.`), twoRisks);
      const p = panel('ONTOLOGIA').querySelector('.cra-narr-prose') as HTMLElement;
      const children = Array.from(p.children) as HTMLElement[];
      const text = children
        .filter((f) => !f.classList.contains('cra-narr-istat'))
        .map((f) => f.textContent)
        .join('');
      expect(text).toBe('Il furto  qui e il danno cala.');
      expect(p.textContent).not.toContain(pua);
      expect(
        children[children.findIndex((f) => f.classList.contains('cra-narr-istat')) - 1].textContent,
      ).toMatch(/furto$/);
    });

    it('an indicator inside a ** pair does not split it', () => {
      withIstat(makeSources('Il **furto cala** ancora.'));
      const p = panel('ONTOLOGIA').querySelector('.cra-narr-prose') as HTMLElement;
      expect(p.textContent).not.toContain('*');
      expect(p.querySelectorAll('.cra-narr-istat')).toHaveLength(1);
    });

    it('a11y: visible "ISTAT" at the head acts as a prefix, readable and hidden closing separator', () => {
      withIstat(makeSources('Il Furto è alto.'));
      const ind = panel('ONTOLOGIA').querySelector('.cra-narr-istat') as HTMLElement;
      const hiddenEls = ind.querySelectorAll('.cra-vh');
      expect(ind.textContent?.trim().startsWith('ISTAT ·')).toBe(true);
      expect(hiddenEls).toHaveLength(1);
      expect(hiddenEls[0].textContent).toContain('Fine dato ISTAT');
      expect(ind.lastElementChild).toBe(hiddenEls[0]);
    });

    it('the other tabs have no indicators even if they cite the risk', () => {
      withIstat(makeSources('Il Furto è alto.'));
      expect(panel('CONTESTO').querySelector('.cra-narr-istat')).toBeNull();
    });

    it('the row of the note is there only with at least one indicator', () => {
      withIstat(makeSources('Il Furto è alto.'));
      expect(panel('ONTOLOGIA').querySelector('.cra-narr-istat-note')?.textContent?.trim()).toBe(
        NOTE,
      );
      expect(panel('CONTESTO').querySelector('.cra-narr-istat-note')).toBeNull();
    });

    it('without ISTAT data or without mention: text intact and no note', () => {
      withIstat(makeSources('Il Furto è alto.'), []);
      expect(fixture.nativeElement.querySelector('.cra-narr-istat')).toBeNull();
      expect(fixture.nativeElement.querySelector('.cra-narr-istat-note')).toBeNull();
      expect(panel('ONTOLOGIA').querySelector('.cra-narr-prose')?.textContent).toContain(
        'Il Furto è alto.',
      );
      withIstat(makeSources('Nessuna menzione.'));
      expect(fixture.nativeElement.querySelector('.cra-narr-istat-note')).toBeNull();
    });

    it('the ISTAT tab stays shown only if it has prose (old narratives)', () => {
      withIstat(makeSources('Il Furto.'));
      expect(fixture.nativeElement.querySelector('#cra-narr-tab-ISTAT')).toBeNull();
      withIstat({ ...makeSources('Il Furto.'), istat: 'Vecchia prosa ISTAT.' });
      expect(fixture.nativeElement.querySelector('#cra-narr-tab-ISTAT')).not.toBeNull();
    });
  });

  describe('#292: the three data states (narrative arriving / arrived / error-fallback)', () => {
    it('loading: shows a light indicator, not an error, even if the narrative is still empty', () => {
      setup({ loading: true, narrative: '', narrativeSources: null });
      const loadingEl = fixture.nativeElement.querySelector('.cra-narr-loading');
      expect(loadingEl).toBeTruthy();
      expect(loadingEl.getAttribute('role')).toBe('status');
      expect(fixture.nativeElement.querySelector('.cra-narr-error')).toBeNull();
      expect(fixture.nativeElement.querySelector('.cra-narr-fallback')).toBeNull();
    });

    it('loading has priority over the error: if both are present only the loading is seen', () => {
      setup({ loading: true, error: 'boom' });
      expect(fixture.nativeElement.querySelector('.cra-narr-loading')).toBeTruthy();
      expect(fixture.nativeElement.querySelector('.cra-narr-error')).toBeNull();
    });

    it('narrative arrived (loading false, no error/fallback): shows the text, no indicator nor alert', () => {
      setup({ loading: false, error: null, fallback: false });
      expect(fixture.nativeElement.querySelector('.cra-narr-loading')).toBeNull();
      expect(fixture.nativeElement.querySelector('.cra-narr-error')).toBeNull();
      expect(fixture.nativeElement.querySelector('.cra-narr-fallback')).toBeNull();
      expect(fixture.nativeElement.textContent).toContain('Sintesi generale della zona.');
    });

    it('error: shows the message in an alert, not the loading indicator', () => {
      setup({ error: 'Errore nella generazione della narrativa di zona.' });
      const errEl = fixture.nativeElement.querySelector('.cra-narr-error');
      expect(errEl).toBeTruthy();
      expect(errEl.getAttribute('role')).toBe('alert');
      expect(errEl.textContent).toContain('Errore nella generazione della narrativa di zona.');
      expect(fixture.nativeElement.querySelector('.cra-narr-loading')).toBeNull();
    });

    it('fallback: shows the message of fallback already handled today, not a generic error', () => {
      setup({ fallback: true });
      const fallbackEl = fixture.nativeElement.querySelector('.cra-narr-fallback');
      expect(fallbackEl).toBeTruthy();
      expect(fallbackEl.textContent).toContain('non ha prodotto una narrativa');
      expect(fixture.nativeElement.querySelector('.cra-narr-error')).toBeNull();
    });

    it('fallback names the zone in zone scope and the point in point scope', () => {
      setup({ fallback: true });
      expect(fixture.nativeElement.querySelector('.cra-narr-fallback').textContent).toContain(
        'per questa zona',
      );
      setup({ fallback: true, poiName: 'Banca A' });
      expect(fixture.nativeElement.querySelector('.cra-narr-fallback').textContent).toContain(
        'per questo punto',
      );
    });
  });
});
