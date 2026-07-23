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
      confidence: 'ipotesi',
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

  it('#207: il controllo unificato "Confidenza" (cra-confidence-filter) è sempre montato', () => {
    const control = fixture.nativeElement.querySelector('cra-confidence-filter');
    expect(control).toBeTruthy();
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

  it('click su una riga del controllo Confidenza emette setFilter con il livello scelto', () => {
    const spy = jest.fn();
    fixture.componentInstance.setFilter.subscribe(spy);
    const rows = fixture.nativeElement.querySelectorAll('.cra-confidence-row');
    (rows[1] as HTMLElement).click(); // da_confermare
    expect(spy).toHaveBeenCalledWith('da_confermare');
  });

  it('aria-pressed sulle righe riflette il livello di filtro attivo (toggle)', () => {
    const rows = fixture.nativeElement.querySelectorAll('.cra-confidence-row');
    expect(rows[0].getAttribute('aria-pressed')).toBe('false');

    fixture.componentRef.setInput('filter', 'verificato');
    fixture.detectChanges();
    expect(rows[0].getAttribute('aria-pressed')).toBe('true');
    expect(rows[1].getAttribute('aria-pressed')).toBe('false');
  });

  it('riclic sulla riga già attiva emette clearFilter', () => {
    fixture.componentRef.setInput('filter', 'da_confermare');
    fixture.detectChanges();
    const spy = jest.fn();
    fixture.componentInstance.clearFilter.subscribe(spy);
    const rows = fixture.nativeElement.querySelectorAll('.cra-confidence-row');
    (rows[1] as HTMLElement).click();
    expect(spy).toHaveBeenCalled();
  });

  it('con filtro attivo mostra solo i POI corrispondenti e la barra "N nascosti"', () => {
    fixture.componentRef.setInput('filter', 'verificato');
    fixture.detectChanges();
    const cards = fixture.nativeElement.querySelectorAll('.cra-poi-card');
    expect(cards.length).toBe(1);
    expect(fixture.nativeElement.textContent).toContain('2 nascosti');
  });

  it('senza filtro nessuna barra "nascosti"', () => {
    expect(fixture.nativeElement.textContent).not.toContain('nascosti');
  });

  it("la numerazione delle card resta quella dell'array originale anche filtrando", () => {
    fixture.componentRef.setInput('filter', 'ipotesi');
    fixture.detectChanges();
    const badge = fixture.nativeElement.querySelector('.cra-poi-pin-badge');
    expect(badge.textContent.trim()).toBe('3');
  });

  it('mostra il conteggio per ciascun livello di confidence nel controllo Confidenza', () => {
    const counts = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-confidence-row-count'),
    ).map((el) => (el as HTMLElement).textContent?.trim());
    expect(counts).toEqual(['1', '1', '1']);
  });
});
