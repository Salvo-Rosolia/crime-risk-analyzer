import { ComponentFixture, TestBed } from '@angular/core/testing';
import { PanelDockComponent } from './panel-dock.component';
import type { NumberedPoi, Poi, RiskModel } from '@core/models/models';

function makePoi(overrides: Partial<Poi> = {}): Poi {
  return {
    id: '1',
    name: 'Colosseo',
    terminus_class: 'Archaeological_site',
    lat: 41.89,
    lon: 12.49,
    confidence: 'confermato',
    sparql_path: null,
    terminus_label_it: 'Sito archeologico',
    terminus_label_en: 'Archaeological site',
    ...overrides,
  };
}

const pois: Poi[] = [makePoi(), makePoi({ id: '2', name: 'Duomo', confidence: 'plausibile' })];
const riskModels: RiskModel[] = [];

/**
 * Dock unico a sinistra (Approccio A, variante 1, #199): riusa `cra-poi-panel`/`cra-detail-panel`
 * come due VISTE mutuamente esclusive (Lista di default, Dettaglio quando `detail()` è impostato).
 * Nessuna logica di filtro/dettaglio è riscritta qui — solo forwarding + orchestrazione del
 * drill-down/collasso/reset (già coperti singolarmente dai rispettivi `.spec.ts`).
 */
describe('PanelDockComponent', () => {
  let fixture: ComponentFixture<PanelDockComponent>;

  function setup(
    overrides: Partial<{
      pois: Poi[];
      detail: NumberedPoi | null;
      open: boolean;
      narrOpen: boolean;
    }> = {},
  ): void {
    fixture = TestBed.createComponent(PanelDockComponent);
    fixture.componentRef.setInput('pois', overrides.pois ?? pois);
    fixture.componentRef.setInput('riskModels', riskModels);
    fixture.componentRef.setInput('detail', overrides.detail ?? null);
    fixture.componentRef.setInput('open', overrides.open ?? true);
    fixture.componentRef.setInput('narrOpen', overrides.narrOpen ?? true);
    fixture.detectChanges();
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [PanelDockComponent] }).compileComponents();
  });

  afterEach(() => {
    // alcuni test di focus management collegano `fixture.nativeElement` a `document.body` (jsdom
    // non aggiorna `document.activeElement` su elementi disconnessi, stesso motivo di
    // `detail-panel.component.spec.ts`): `.remove()` su un nodo già disconnesso è un no-op sicuro.
    fixture?.nativeElement.remove();
  });

  it('mostra la Vista Lista (cra-poi-panel) di default, senza Vista Dettaglio', () => {
    setup();
    expect(fixture.nativeElement.querySelector('cra-poi-panel')).toBeTruthy();
    expect(fixture.nativeElement.querySelector('cra-detail-panel')).toBeNull();
  });

  it('drill-down: con "detail" impostato mostra cra-detail-panel e nasconde (senza smontare) cra-poi-panel', () => {
    setup();
    const listPanel = fixture.nativeElement.querySelector('cra-poi-panel');
    const listWrapper: HTMLElement = fixture.nativeElement.querySelector('.cra-dock-list-view');
    expect(listWrapper.hidden).toBe(false);

    fixture.componentRef.setInput('detail', { poi: pois[0], number: 1 });
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('cra-detail-panel')).toBeTruthy();
    // stesso nodo: la Vista Lista NON si smonta, solo si nasconde (preserva scroll/stato, #199).
    expect(fixture.nativeElement.querySelector('cra-poi-panel')).toBe(listPanel);
    expect(listWrapper.hidden).toBe(true);
  });

  it('"‹ indietro" di cra-detail-panel emette closeDetail dal dock e torna alla Vista Lista visibile', () => {
    setup({ detail: { poi: pois[0], number: 1 } });
    const spy = jest.fn();
    fixture.componentInstance.closeDetail.subscribe(spy);
    (fixture.nativeElement.querySelector('.cra-detail-back') as HTMLElement).click();
    expect(spy).toHaveBeenCalled();

    // il dock non decide da sé di tornare alla lista (lo fa lo shell dispatchando DESELECT_POI):
    // qui verifichiamo solo che l'evento sia stato inoltrato correttamente.
  });

  it('inoltra selectPoi/setFilter/clearFilter dalla Vista Lista', () => {
    setup();
    const selectSpy = jest.fn();
    const filterSpy = jest.fn();
    fixture.componentInstance.selectPoi.subscribe(selectSpy);
    fixture.componentInstance.setFilter.subscribe(filterSpy);

    (fixture.nativeElement.querySelector('.cra-poi-card') as HTMLElement).click();
    expect(selectSpy).toHaveBeenCalledWith('1');

    (fixture.nativeElement.querySelector('.cra-chip') as HTMLElement).click();
    expect(filterSpy).toHaveBeenCalled();
  });

  it('collasso (#199 decisione 3): click sul controllo emette toggleOpen; con open=false il corpo è [hidden]', () => {
    setup({ open: false });
    const body: HTMLElement = fixture.nativeElement.querySelector('.cra-dock-body');
    expect(body.hidden).toBe(true);
    const toggle: HTMLElement = fixture.nativeElement.querySelector('.cra-dock-toggle');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');

    const spy = jest.fn();
    fixture.componentInstance.toggleOpen.subscribe(spy);
    toggle.click();
    expect(spy).toHaveBeenCalled();
  });

  it('con open=true il corpo NON è [hidden] e aria-expanded è true', () => {
    setup({ open: true });
    const body: HTMLElement = fixture.nativeElement.querySelector('.cra-dock-body');
    expect(body.hidden).toBe(false);
    const toggle: HTMLElement = fixture.nativeElement.querySelector('.cra-dock-toggle');
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
  });

  it("coordinamento altezza con narrOpen (#199 decisione 2): la classe cra-dock-narr-open sull'host riflette narrOpen()", () => {
    setup({ narrOpen: true });
    expect(fixture.nativeElement.classList.contains('cra-dock-narr-open')).toBe(true);

    fixture.componentRef.setInput('narrOpen', false);
    fixture.detectChanges();
    expect(fixture.nativeElement.classList.contains('cra-dock-narr-open')).toBe(false);
  });

  it('"+ Nuova richiesta": il clic mostra la conferma leggera IN-APP (non dispatcha subito reset)', () => {
    setup();
    const resetSpy = jest.fn();
    fixture.componentInstance.resetConfirmed.subscribe(resetSpy);

    (fixture.nativeElement.querySelector('.cra-btn-new-request') as HTMLElement).click();
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.cra-btn-new-request')).toBeNull();
    expect(fixture.nativeElement.textContent).toContain('Ricominciare?');
    expect(resetSpy).not.toHaveBeenCalled();
  });

  it('"+ Nuova richiesta" → conferma "Sì" emette reset', () => {
    setup();
    const resetSpy = jest.fn();
    fixture.componentInstance.resetConfirmed.subscribe(resetSpy);

    (fixture.nativeElement.querySelector('.cra-btn-new-request') as HTMLElement).click();
    fixture.detectChanges();
    (fixture.nativeElement.querySelector('.cra-btn-confirm-yes') as HTMLElement).click();

    expect(resetSpy).toHaveBeenCalled();
  });

  it('"+ Nuova richiesta" → "Annulla" torna al pulsante iniziale senza emettere reset', () => {
    setup();
    const resetSpy = jest.fn();
    fixture.componentInstance.resetConfirmed.subscribe(resetSpy);

    (fixture.nativeElement.querySelector('.cra-btn-new-request') as HTMLElement).click();
    fixture.detectChanges();
    (fixture.nativeElement.querySelector('.cra-btn-confirm-cancel') as HTMLElement).click();
    fixture.detectChanges();

    expect(resetSpy).not.toHaveBeenCalled();
    expect(fixture.nativeElement.querySelector('.cra-btn-new-request')).toBeTruthy();
    expect(fixture.nativeElement.textContent).not.toContain('Ricominciare?');
  });

  describe('a11y: focus management nel flusso di conferma "+ Nuova richiesta" (fix review #199)', () => {
    it('quando compare la conferma il focus si sposta sul pulsante "Sì"', () => {
      setup();
      document.body.appendChild(fixture.nativeElement);

      (fixture.nativeElement.querySelector('.cra-btn-new-request') as HTMLElement).click();
      fixture.detectChanges();

      expect(document.activeElement).toBe(
        fixture.nativeElement.querySelector('.cra-btn-confirm-yes'),
      );
    });

    it('"Annulla" richiude la conferma e riporta il focus su "+ Nuova richiesta"', () => {
      setup();
      document.body.appendChild(fixture.nativeElement);

      (fixture.nativeElement.querySelector('.cra-btn-new-request') as HTMLElement).click();
      fixture.detectChanges();
      (fixture.nativeElement.querySelector('.cra-btn-confirm-cancel') as HTMLElement).click();
      fixture.detectChanges();

      expect(document.activeElement).toBe(
        fixture.nativeElement.querySelector('.cra-btn-new-request'),
      );
    });

    it('al montaggio del dock il focus NON viene rubato su "+ Nuova richiesta" (nessun autofocus indesiderato)', () => {
      const dummy = document.createElement('input');
      document.body.appendChild(dummy);
      dummy.focus();
      expect(document.activeElement).toBe(dummy);

      setup();
      document.body.appendChild(fixture.nativeElement);
      fixture.detectChanges();

      expect(document.activeElement).toBe(dummy);
      dummy.remove();
    });
  });
});
