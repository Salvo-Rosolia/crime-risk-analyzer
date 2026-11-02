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
    confidence: 'verificato',
    sparql_path: null,
    terminus_label_it: 'Sito archeologico',
    terminus_label_en: 'Archaeological site',
    ...overrides,
  };
}

const pois: Poi[] = [makePoi(), makePoi({ id: '2', name: 'Duomo', confidence: 'da_confermare' })];
const riskModels: RiskModel[] = [];

/**
 * Single dock on the left (Approach A, variant 1, #199): reuses `cra-poi-panel`/`cra-detail-panel`
 * as two mutually exclusive VIEWS (List by default, Detail when `detail()` is set).
 * No filter/detail logic is rewritten here — only forwarding + orchestration of the
 * drill-down/collapse/reset (already covered individually by the respective `.spec.ts`).
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
    // some focus management tests attach `fixture.nativeElement` to `document.body` (jsdom
    // does not update `document.activeElement` on disconnected elements, same reason as
    // `detail-panel.component.spec.ts`): `.remove()` on an already disconnected node is a safe no-op.
    fixture?.nativeElement.remove();
  });

  it('shows the List view (cra-poi-panel) by default, without the Detail view', () => {
    setup();
    expect(fixture.nativeElement.querySelector('cra-poi-panel')).toBeTruthy();
    expect(fixture.nativeElement.querySelector('cra-detail-panel')).toBeNull();
  });

  it('drill-down: with "detail" set it shows cra-detail-panel and hides (without unmounting) cra-poi-panel', () => {
    setup();
    const listPanel = fixture.nativeElement.querySelector('cra-poi-panel');
    const listWrapper: HTMLElement = fixture.nativeElement.querySelector('.cra-dock-list-view');
    expect(listWrapper.hidden).toBe(false);

    fixture.componentRef.setInput('detail', { poi: pois[0], number: 1 });
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('cra-detail-panel')).toBeTruthy();
    // same node: the List view is NOT unmounted, only hidden (preserves scroll/state, #199).
    expect(fixture.nativeElement.querySelector('cra-poi-panel')).toBe(listPanel);
    expect(listWrapper.hidden).toBe(true);
  });

  it('"‹ indietro" of cra-detail-panel emits closeDetail from the dock and goes back to the visible List view', () => {
    setup({ detail: { poi: pois[0], number: 1 } });
    const spy = jest.fn();
    fixture.componentInstance.closeDetail.subscribe(spy);
    (fixture.nativeElement.querySelector('.cra-detail-back') as HTMLElement).click();
    expect(spy).toHaveBeenCalled();

    // the dock does not decide on its own to go back to the list (the shell does it by dispatching DESELECT_POI):
    // here we only verify that the event was forwarded correctly.
  });

  it('forwards selectPoi/setFilter/clearFilter from the List view', () => {
    setup();
    const selectSpy = jest.fn();
    const filterSpy = jest.fn();
    fixture.componentInstance.selectPoi.subscribe(selectSpy);
    fixture.componentInstance.setFilter.subscribe(filterSpy);

    (fixture.nativeElement.querySelector('.cra-poi-card') as HTMLElement).click();
    expect(selectSpy).toHaveBeenCalledWith('1');

    (fixture.nativeElement.querySelector('.cra-confidence-row') as HTMLElement).click();
    expect(filterSpy).toHaveBeenCalled();
  });

  it('collapse (#199 decision 3): click on the control emits toggleOpen; with open=false the body is [hidden]', () => {
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

  it('with open=true the body is NOT [hidden] and aria-expanded is true', () => {
    setup({ open: true });
    const body: HTMLElement = fixture.nativeElement.querySelector('.cra-dock-body');
    expect(body.hidden).toBe(false);
    const toggle: HTMLElement = fixture.nativeElement.querySelector('.cra-dock-toggle');
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
  });

  it('height coordination with narrOpen (#199 decision 2): the cra-dock-narr-open class on the host reflects narrOpen()', () => {
    setup({ narrOpen: true });
    expect(fixture.nativeElement.classList.contains('cra-dock-narr-open')).toBe(true);

    fixture.componentRef.setInput('narrOpen', false);
    fixture.detectChanges();
    expect(fixture.nativeElement.classList.contains('cra-dock-narr-open')).toBe(false);
  });

  it('"+ Nuova richiesta": the click shows the light IN-APP confirmation (does not dispatch reset right away)', () => {
    setup();
    const resetSpy = jest.fn();
    fixture.componentInstance.resetConfirmed.subscribe(resetSpy);

    (fixture.nativeElement.querySelector('.cra-btn-new-request') as HTMLElement).click();
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.cra-btn-new-request')).toBeNull();
    expect(fixture.nativeElement.textContent).toContain('Ricominciare?');
    expect(resetSpy).not.toHaveBeenCalled();
  });

  it('"+ Nuova richiesta" → confirm "Sì" emits reset', () => {
    setup();
    const resetSpy = jest.fn();
    fixture.componentInstance.resetConfirmed.subscribe(resetSpy);

    (fixture.nativeElement.querySelector('.cra-btn-new-request') as HTMLElement).click();
    fixture.detectChanges();
    (fixture.nativeElement.querySelector('.cra-btn-confirm-yes') as HTMLElement).click();

    expect(resetSpy).toHaveBeenCalled();
  });

  it('"+ Nuova richiesta" → "Annulla" goes back to the initial button without emitting reset', () => {
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

  describe('a11y: focus management in the "+ Nuova richiesta" confirmation flow (review #199 fix)', () => {
    it('when the confirmation appears the focus moves to the "Sì" button', () => {
      setup();
      document.body.appendChild(fixture.nativeElement);

      (fixture.nativeElement.querySelector('.cra-btn-new-request') as HTMLElement).click();
      fixture.detectChanges();

      expect(document.activeElement).toBe(
        fixture.nativeElement.querySelector('.cra-btn-confirm-yes'),
      );
    });

    it('"Annulla" closes the confirmation and brings the focus back to "+ Nuova richiesta"', () => {
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

    it('on dock mount the focus is NOT stolen onto "+ Nuova richiesta" (no unwanted autofocus)', () => {
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
