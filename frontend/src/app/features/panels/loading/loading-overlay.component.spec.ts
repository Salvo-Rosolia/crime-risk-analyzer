import { ComponentFixture, TestBed } from '@angular/core/testing';
import { LOADING_STEPS, LoadingOverlayComponent } from './loading-overlay.component';

describe('LoadingOverlayComponent', () => {
  let fixture: ComponentFixture<LoadingOverlayComponent>;

  beforeEach(async () => {
    jest.useFakeTimers();
    await TestBed.configureTestingModule({
      imports: [LoadingOverlayComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(LoadingOverlayComponent);
    fixture.componentRef.setInput('zona', 'Trastevere');
    fixture.detectChanges();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('mostra "Analizzando {zona}"', () => {
    expect(fixture.nativeElement.textContent).toContain('Analizzando Trastevere');
  });

  it('senza zona mostra un fallback generico', () => {
    fixture.componentRef.setInput('zona', null);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Analizzando la zona');
  });

  it('elenca gli step cosmetici della pipeline reale (geocoding → Overpass → SPARQL → grounding → LLM)', () => {
    const text = fixture.nativeElement.textContent;
    for (const step of LOADING_STEPS) {
      expect(text).toContain(step);
    }
    expect(LOADING_STEPS.length).toBe(5);
  });

  it('il primo step è "corrente" da subito', () => {
    const steps = fixture.nativeElement.querySelectorAll('.cra-loading-step');
    expect(steps[0].classList.contains('cra-step-current')).toBe(true);
    expect(steps[1].classList.contains('cra-step-current')).toBe(false);
  });

  it('avanza lo step corrente nel tempo (cosmetico, nessuno streaming reale dal server)', () => {
    jest.advanceTimersByTime(1400);
    fixture.detectChanges();
    const steps = fixture.nativeElement.querySelectorAll('.cra-loading-step');
    expect(steps[0].classList.contains('cra-step-done')).toBe(true);
    expect(steps[1].classList.contains('cra-step-current')).toBe(true);
  });

  it("si ferma all'ultimo step e non oltre", () => {
    jest.advanceTimersByTime(1400 * (LOADING_STEPS.length + 5));
    fixture.detectChanges();
    const steps = fixture.nativeElement.querySelectorAll('.cra-loading-step');
    expect(steps[LOADING_STEPS.length - 1].classList.contains('cra-step-current')).toBe(true);
  });

  it('ripulisce il timer alla distruzione del componente (nessun avanzamento successivo)', () => {
    const clearSpy = jest.spyOn(window, 'clearInterval');
    fixture.destroy();
    expect(clearSpy).toHaveBeenCalled();
  });
});
