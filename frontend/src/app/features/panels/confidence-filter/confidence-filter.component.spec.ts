import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfidenceFilterComponent } from './confidence-filter.component';
import type { Confidence } from '@core/models/models';

const KEY_NOTE =
  "Il livello indica quanto il POI è ancorato a un'entità verificabile in mappa — non è un " +
  'livello di pericolosità.';

describe('ConfidenceFilterComponent', () => {
  let fixture: ComponentFixture<ConfidenceFilterComponent>;

  const counts: Record<Confidence, number> = { verificato: 2, da_confermare: 1 };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ConfidenceFilterComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(ConfidenceFilterComponent);
    fixture.componentRef.setInput('counts', counts);
    fixture.detectChanges();
  });

  it('renders the 2 levels with name, meaning and count', () => {
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Identificato');
    expect(text).toContain('entità identificata in mappa');
    expect(text).toContain('Anonimo');
    expect(text).toContain('punto anonimo in mappa');
  });

  it('shows the 2 levels in the order Identificato → Anonimo', () => {
    const names: string[] = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-confidence-row-name'),
    ).map((el) => (el as HTMLElement).textContent?.trim());
    expect(names).toEqual(['Identificato', 'Anonimo']);
  });

  it('shows the count of each level', () => {
    const counts_: string[] = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-confidence-row-count'),
    ).map((el) => (el as HTMLElement).textContent?.trim());
    expect(counts_).toEqual(['2', '1']);
  });

  it('ACCEPTANCE (fail-if-removed): shows the key note — confidence is not a dangerousness level', () => {
    expect(fixture.nativeElement.textContent).toContain(KEY_NOTE);
  });

  it('each row is a toggle inside a role="group" with aria-label "Filtra per confidence"', () => {
    const group = fixture.nativeElement.querySelector('[role="group"]');
    expect(group.getAttribute('aria-label')).toBe('Filtra per confidence');
    const rows = fixture.nativeElement.querySelectorAll('.cra-confidence-row');
    expect(rows.length).toBe(2);
    rows.forEach((row: HTMLElement) => expect(row.tagName).toBe('BUTTON'));
  });

  it('click on a row emits rowClick with the matching level', () => {
    const spy = jest.fn();
    fixture.componentInstance.rowClick.subscribe(spy);
    const rows = fixture.nativeElement.querySelectorAll('.cra-confidence-row');
    (rows[1] as HTMLElement).click();
    expect(spy).toHaveBeenCalledWith('da_confermare');
  });

  it('aria-pressed reflects activeFilter and the active row has the highlight class', () => {
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
