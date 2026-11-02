import { ComponentFixture, TestBed } from '@angular/core/testing';
import { SourcesIndicatorComponent } from './sources-indicator.component';

describe('SourcesIndicatorComponent', () => {
  let fixture: ComponentFixture<SourcesIndicatorComponent>;
  const btn = () => fixture.nativeElement.querySelector('button') as HTMLButtonElement;

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [SourcesIndicatorComponent] });
    fixture = TestBed.createComponent(SourcesIndicatorComponent);
  });

  it('shows "Fonti: Predefinite" by default', () => {
    fixture.detectChanges();
    expect(btn().textContent).toContain('Fonti: Predefinite');
    expect(btn().getAttribute('data-kind')).toBe('default');
  });

  it('shows the received label and kind', () => {
    fixture.componentRef.setInput('label', 'Personalizzate');
    fixture.componentRef.setInput('kind', 'custom');
    fixture.detectChanges();
    expect(btn().textContent).toContain('Fonti: Personalizzate');
    expect(btn().getAttribute('data-kind')).toBe('custom');
  });

  it('the accessible name contains the visible text (WCAG 2.5.3)', () => {
    fixture.detectChanges();
    const label = btn().getAttribute('aria-label')!;
    expect(label).toContain('Fonti: Predefinite');
    expect(label).toContain('Apri la pagina Fonti');
  });

  it('the click emits openPage', () => {
    const spy = jest.fn();
    fixture.componentInstance.openPage.subscribe(spy);
    fixture.detectChanges();
    btn().click();
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
