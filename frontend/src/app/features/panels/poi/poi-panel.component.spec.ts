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
    confidence: 'confermato',
    sparql_path: null,
    terminus_label_it: 'Sito archeologico',
    terminus_label_en: 'Archaeological site',
    ...overrides,
  };
}

describe('PoiPanelComponent', () => {
  let fixture: ComponentFixture<PoiPanelComponent>;

  const pois: Poi[] = [
    makePoi({ id: '1', name: 'Colosseo', confidence: 'confermato' }),
    makePoi({
      id: '2',
      name: 'Bar X',
      confidence: 'plausibile',
      terminus_class: 'Bank',
      terminus_label_it: 'Banca',
    }),
    makePoi({
      id: '3',
      name: 'Vicolo Y',
      confidence: 'speculativo',
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

  it('elenca una card per ogni POI con etichetta IT (fallback a terminus_class se assente)', () => {
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Colosseo');
    expect(text).toContain('Banca');
    expect(text).toContain('Alley');
  });

  it("numera le card in base all'ordine originale dell'array POI", () => {
    const badges = fixture.nativeElement.querySelectorAll('.cra-poi-pin-badge');
    expect(Array.from(badges).map((b) => (b as HTMLElement).textContent?.trim())).toEqual([
      '1',
      '2',
      '3',
    ]);
  });

  it("click su una card emette selectPoi con l'id del POI", () => {
    const spy = jest.fn();
    fixture.componentInstance.selectPoi.subscribe(spy);
    const cards = fixture.nativeElement.querySelectorAll('.cra-poi-card');
    (cards[1] as HTMLElement).click();
    expect(spy).toHaveBeenCalledWith('2');
  });

  it('evidenzia la card corrispondente a selectedId (classe + aria-current)', () => {
    fixture.componentRef.setInput('selectedId', '2');
    fixture.detectChanges();
    const cards = fixture.nativeElement.querySelectorAll('.cra-poi-card');
    expect(cards[1].classList.contains('cra-poi-card-selected')).toBe(true);
    expect(cards[0].classList.contains('cra-poi-card-selected')).toBe(false);
    expect(cards[1].getAttribute('aria-current')).toBe('true');
    expect(cards[0].getAttribute('aria-current')).toBeNull();
  });

  it('click su un chip di confidence emette setFilter con il livello scelto', () => {
    const spy = jest.fn();
    fixture.componentInstance.setFilter.subscribe(spy);
    const chips = fixture.nativeElement.querySelectorAll('.cra-chip');
    (chips[1] as HTMLElement).click(); // plausibile
    expect(spy).toHaveBeenCalledWith('plausibile');
  });

  it('aria-pressed sui chip riflette il livello di filtro attivo (toggle)', () => {
    const chips = fixture.nativeElement.querySelectorAll('.cra-chip');
    expect(chips[0].getAttribute('aria-pressed')).toBe('false');

    fixture.componentRef.setInput('filter', 'confermato');
    fixture.detectChanges();
    expect(chips[0].getAttribute('aria-pressed')).toBe('true');
    expect(chips[1].getAttribute('aria-pressed')).toBe('false');
  });

  it('riclic sul chip già attivo emette clearFilter', () => {
    fixture.componentRef.setInput('filter', 'plausibile');
    fixture.detectChanges();
    const spy = jest.fn();
    fixture.componentInstance.clearFilter.subscribe(spy);
    const chips = fixture.nativeElement.querySelectorAll('.cra-chip');
    (chips[1] as HTMLElement).click();
    expect(spy).toHaveBeenCalled();
  });

  it('con filtro attivo mostra solo i POI corrispondenti e la barra "N nascosti"', () => {
    fixture.componentRef.setInput('filter', 'confermato');
    fixture.detectChanges();
    const cards = fixture.nativeElement.querySelectorAll('.cra-poi-card');
    expect(cards.length).toBe(1);
    expect(fixture.nativeElement.textContent).toContain('2 nascosti');
  });

  it('senza filtro nessuna barra "nascosti"', () => {
    expect(fixture.nativeElement.textContent).not.toContain('nascosti');
  });

  it("la numerazione delle card resta quella dell'array originale anche filtrando", () => {
    fixture.componentRef.setInput('filter', 'speculativo');
    fixture.detectChanges();
    const badge = fixture.nativeElement.querySelector('.cra-poi-pin-badge');
    expect(badge.textContent.trim()).toBe('3');
  });

  it('mostra il conteggio per ciascun livello di confidence nei chip', () => {
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Confermato (1)');
    expect(text).toContain('Plausibile (1)');
    expect(text).toContain('Speculativo (1)');
  });
});
