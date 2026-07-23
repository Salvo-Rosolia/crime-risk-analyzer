import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfidenceFilterComponent } from './confidence-filter.component';
import type { Confidence } from '@core/models/models';

const KEY_NOTE =
  "Il livello indica quanto il POI è ancorato a un'entità verificabile in mappa — non è un " +
  'livello di pericolosità.';

describe('ConfidenceFilterComponent', () => {
  let fixture: ComponentFixture<ConfidenceFilterComponent>;

  const counts: Record<Confidence, number> = { verificato: 2, da_confermare: 1, ipotesi: 3 };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ConfidenceFilterComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(ConfidenceFilterComponent);
    fixture.componentRef.setInput('counts', counts);
    fixture.detectChanges();
  });

  it('rende i 3 livelli con nome, significato e conteggio', () => {
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Verificato');
    expect(text).toContain('entità identificata in mappa');
    expect(text).toContain('Da confermare');
    expect(text).toContain('punto anonimo in mappa');
    expect(text).toContain('Ipotesi');
    expect(text).toContain('fuori ontologia');
  });

  it("mostra i 3 livelli nell'ordine Verificato → Da confermare → Ipotesi", () => {
    const names: string[] = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-confidence-row-name'),
    ).map((el) => (el as HTMLElement).textContent?.trim());
    expect(names).toEqual(['Verificato', 'Da confermare', 'Ipotesi']);
  });

  it('mostra il conteggio di ciascun livello', () => {
    const counts_: string[] = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-confidence-row-count'),
    ).map((el) => (el as HTMLElement).textContent?.trim());
    expect(counts_).toEqual(['2', '1', '3']);
  });

  it('ACCEPTANCE (fail-if-removed): mostra la nota chiave — la confidence non è un livello di pericolosità', () => {
    expect(fixture.nativeElement.textContent).toContain(KEY_NOTE);
  });

  it('ogni riga è un toggle dentro un role="group" con aria-label "Filtra per confidence"', () => {
    const group = fixture.nativeElement.querySelector('[role="group"]');
    expect(group.getAttribute('aria-label')).toBe('Filtra per confidence');
    const rows = fixture.nativeElement.querySelectorAll('.cra-confidence-row');
    expect(rows.length).toBe(3);
    rows.forEach((row: HTMLElement) => expect(row.tagName).toBe('BUTTON'));
  });

  it('click su una riga emette rowClick con il livello corrispondente', () => {
    const spy = jest.fn();
    fixture.componentInstance.rowClick.subscribe(spy);
    const rows = fixture.nativeElement.querySelectorAll('.cra-confidence-row');
    (rows[1] as HTMLElement).click();
    expect(spy).toHaveBeenCalledWith('da_confermare');
  });

  it('aria-pressed riflette activeFilter e la riga attiva ha la classe di evidenza', () => {
    const rows = fixture.nativeElement.querySelectorAll('.cra-confidence-row');
    expect(rows[0].getAttribute('aria-pressed')).toBe('false');
    expect(rows[0].classList.contains('cra-confidence-row-active')).toBe(false);

    fixture.componentRef.setInput('activeFilter', 'verificato');
    fixture.detectChanges();
    expect(rows[0].getAttribute('aria-pressed')).toBe('true');
    expect(rows[0].classList.contains('cra-confidence-row-active')).toBe(true);
    expect(rows[1].getAttribute('aria-pressed')).toBe('false');
    expect(rows[1].classList.contains('cra-confidence-row-active')).toBe(false);
  });
});
