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
    fixture.detectChanges();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('lists the cosmetic steps of phase 1 (geocoding → Overpass → SPARQL → grounding, no LLM generation here)', () => {
    const text = fixture.nativeElement.textContent;
    for (const step of LOADING_STEPS) {
      expect(text).toContain(step);
    }
    expect(LOADING_STEPS.length).toBe(4);
    expect(text).not.toContain('LLM');
  });

  it('the first step is "current" right away', () => {
    const steps = fixture.nativeElement.querySelectorAll('.cra-loading-step');
    expect(steps[0].classList.contains('cra-step-current')).toBe(true);
    expect(steps[1].classList.contains('cra-step-current')).toBe(false);
  });

  it('advances the current step over time (cosmetic, no real streaming from the server)', () => {
    jest.advanceTimersByTime(1400);
    fixture.detectChanges();
    const steps = fixture.nativeElement.querySelectorAll('.cra-loading-step');
    expect(steps[0].classList.contains('cra-step-done')).toBe(true);
    expect(steps[1].classList.contains('cra-step-current')).toBe(true);
  });

  it('stops at the last step and no further', () => {
    jest.advanceTimersByTime(1400 * (LOADING_STEPS.length + 5));
    fixture.detectChanges();
    const steps = fixture.nativeElement.querySelectorAll('.cra-loading-step');
    expect(steps[LOADING_STEPS.length - 1].classList.contains('cra-step-current')).toBe(true);
  });

  it('cleans up the timer when the component is destroyed (no later advance)', () => {
    const clearSpy = jest.spyOn(window, 'clearInterval');
    fixture.destroy();
    expect(clearSpy).toHaveBeenCalled();
  });

  it('in base mode shows only geocoding and Overpass, no SPARQL nor grounding (#494)', () => {
    fixture = TestBed.createComponent(LoadingOverlayComponent);
    fixture.componentRef.setInput('mode', 'base');
    fixture.detectChanges();
    const text = fixture.nativeElement.textContent;
    expect(fixture.nativeElement.querySelectorAll('.cra-loading-step').length).toBe(2);
    expect(text).toContain('Overpass');
    expect(text).not.toContain('SPARQL');
    expect(text).not.toContain('Grounding');
  });
});
