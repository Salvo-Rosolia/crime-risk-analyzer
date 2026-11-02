import { ComponentFixture, TestBed } from '@angular/core/testing';
import { PoiPanelComponent } from './poi-panel.component';
import type { Poi } from '@core/models/models';

function makePoi(overrides: Partial<Poi>): Poi {
  return {
    id: '1',
    name: 'Colosseo',
    terminus_class: 'Archaeological_site',
    lat: 0,
    lon: 0,
    confidence: 'verificato',
    sparql_path: null,
    terminus_label_it: 'Sito archeologico',
    terminus_label_en: 'Archaeological site',
    ...overrides,
  };
}

describe('PoiPanelComponent', () => {
  let fixture: ComponentFixture<PoiPanelComponent>;

  const pois: Poi[] = [
    makePoi({ id: '1', name: 'Colosseo', confidence: 'verificato' }),
    makePoi({
      id: '2',
      name: 'Bar X',
      confidence: 'da_confermare',
      terminus_class: 'Bank',
      terminus_label_it: 'Banca',
    }),
    makePoi({
      id: '3',
      name: 'Vicolo Y',
      confidence: null,
      terminus_class: 'Alley',
      terminus_label_it: '',
    }),
  ];

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [PoiPanelComponent] }).compileComponents();
    fixture = TestBed.createComponent(PoiPanelComponent);
    fixture.componentRef.setInput('pois', pois);
    fixture.detectChanges();
  });

  it('lists one card for each POI with IT label (fallback to terminus_class if absent)', () => {
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Colosseo');
    expect(text).toContain('Banca');
    expect(text).toContain('Alley');
  });

  it('#207: the unified "Confidenza" control (cra-confidence-filter) is always mounted', () => {
    const control = fixture.nativeElement.querySelector('cra-confidence-filter');
    expect(control).toBeTruthy();
  });

  it('numbers the cards based on the original order of the POI array', () => {
    const badges = fixture.nativeElement.querySelectorAll('.cra-poi-pin-badge');
    expect(Array.from(badges).map((b) => (b as HTMLElement).textContent?.trim())).toEqual([
      '1',
      '2',
      '3',
    ]);
  });

  it('click on a card emits selectPoi with the POI id', () => {
    const spy = jest.fn();
    fixture.componentInstance.selectPoi.subscribe(spy);
    const cards = fixture.nativeElement.querySelectorAll('.cra-poi-card');
    (cards[1] as HTMLElement).click();
    expect(spy).toHaveBeenCalledWith('2');
  });

  it('highlights the card matching selectedId (class + aria-current)', () => {
    fixture.componentRef.setInput('selectedId', '2');
    fixture.detectChanges();
    const cards = fixture.nativeElement.querySelectorAll('.cra-poi-card');
    expect(cards[1].classList.contains('cra-poi-card-selected')).toBe(true);
    expect(cards[0].classList.contains('cra-poi-card-selected')).toBe(false);
    expect(cards[1].getAttribute('aria-current')).toBe('true');
    expect(cards[0].getAttribute('aria-current')).toBeNull();
  });

  it('click on a row of the Confidenza control emits setFilter with the chosen level', () => {
    const spy = jest.fn();
    fixture.componentInstance.setFilter.subscribe(spy);
    const rows = fixture.nativeElement.querySelectorAll('.cra-confidence-row');
    (rows[1] as HTMLElement).click(); // da_confermare
    expect(spy).toHaveBeenCalledWith('da_confermare');
  });

  it('aria-pressed on the rows reflects the active filter level (toggle)', () => {
    const rows = fixture.nativeElement.querySelectorAll('.cra-confidence-row');
    expect(rows[0].getAttribute('aria-pressed')).toBe('false');

    fixture.componentRef.setInput('filter', 'verificato');
    fixture.detectChanges();
    expect(rows[0].getAttribute('aria-pressed')).toBe('true');
    expect(rows[1].getAttribute('aria-pressed')).toBe('false');
  });

  it('clicking the already active row again emits clearFilter', () => {
    fixture.componentRef.setInput('filter', 'da_confermare');
    fixture.detectChanges();
    const spy = jest.fn();
    fixture.componentInstance.clearFilter.subscribe(spy);
    const rows = fixture.nativeElement.querySelectorAll('.cra-confidence-row');
    (rows[1] as HTMLElement).click();
    expect(spy).toHaveBeenCalled();
  });

  it('with an active filter shows only the matching POIs and the "N nascosti" bar', () => {
    fixture.componentRef.setInput('filter', 'verificato');
    fixture.detectChanges();
    const cards = fixture.nativeElement.querySelectorAll('.cra-poi-card');
    expect(cards.length).toBe(1);
    expect(fixture.nativeElement.textContent).toContain('2 nascosti');
  });

  it('without a filter no "nascosti" bar', () => {
    expect(fixture.nativeElement.textContent).not.toContain('nascosti');
  });

  it('the card numbering stays that of the original array even when filtering', () => {
    fixture.componentRef.setInput('filter', 'da_confermare');
    fixture.detectChanges();
    const badge = fixture.nativeElement.querySelector('.cra-poi-pin-badge');
    expect(badge.textContent.trim()).toBe('2');
  });

  it('shows the count for each confidence level in the Confidenza control (#220: only 2 levels, the POI outside the ontology is not counted)', () => {
    const counts = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-confidence-row-count'),
    ).map((el) => (el as HTMLElement).textContent?.trim());
    expect(counts).toEqual(['1', '1']);
  });

  it('#220: a POI outside the ontology (confidence null) stays visible without an active filter, without a text confidence badge', () => {
    const cards = fixture.nativeElement.querySelectorAll('.cra-poi-card');
    const alleyCard = cards[2] as HTMLElement;
    expect(alleyCard.textContent).toContain('Vicolo Y');
    expect(alleyCard.querySelector('.cra-badge-confidence')).toBeNull();
    expect(alleyCard.querySelector('.cra-poi-pin-badge')).not.toBeNull();
  });

  it('#220: a POI outside the ontology (confidence null) is not filterable as a category: with an active filter it disappears from the list like the non-matching levels', () => {
    fixture.componentRef.setInput('filter', 'verificato');
    fixture.detectChanges();
    const names = Array.from(fixture.nativeElement.querySelectorAll('.cra-poi-name')).map((el) =>
      (el as HTMLElement).textContent?.trim(),
    );
    expect(names).not.toContain('Vicolo Y');
  });

  it('#261: a POI without a name (anonymous OSM feature) shows the class fallback instead of a blank row', () => {
    fixture.componentRef.setInput('pois', [
      ...pois,
      makePoi({
        id: '4',
        name: '',
        confidence: 'da_confermare',
        terminus_class: 'School',
        terminus_label_it: 'Scuola',
      }),
    ]);
    fixture.detectChanges();
    const names = Array.from(fixture.nativeElement.querySelectorAll('.cra-poi-name')).map((el) =>
      (el as HTMLElement).textContent?.trim(),
    );
    expect(names).toContain('Scuola (senza nome su OSM)');
    expect(names.some((n) => n === '')).toBe(false);
  });
});
