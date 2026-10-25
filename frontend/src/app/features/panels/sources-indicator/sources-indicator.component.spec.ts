import { ComponentFixture, TestBed } from '@angular/core/testing';
import { SourcesIndicatorComponent } from './sources-indicator.component';

describe('SourcesIndicatorComponent', () => {
  let fixture: ComponentFixture<SourcesIndicatorComponent>;
  const btn = () => fixture.nativeElement.querySelector('button') as HTMLButtonElement;

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [SourcesIndicatorComponent] });
    fixture = TestBed.createComponent(SourcesIndicatorComponent);
  });

  it('mostra "Fonti: Predefinite" di default', () => {
    fixture.detectChanges();
    expect(btn().textContent).toContain('Fonti: Predefinite');
    expect(btn().getAttribute('data-kind')).toBe('default');
  });

  it('mostra l etichetta e il tipo ricevuti', () => {
    fixture.componentRef.setInput('label', 'Personalizzate');
    fixture.componentRef.setInput('kind', 'custom');
    fixture.detectChanges();
    expect(btn().textContent).toContain('Fonti: Personalizzate');
    expect(btn().getAttribute('data-kind')).toBe('custom');
  });

  it('il nome accessibile contiene il testo visibile (WCAG 2.5.3)', () => {
    fixture.detectChanges();
    const label = btn().getAttribute('aria-label')!;
    expect(label).toContain('Fonti: Predefinite');
    expect(label).toContain('Apri la pagina Fonti');
  });

  it('il clic emette openPage', () => {
    const spy = jest.fn();
    fixture.componentInstance.openPage.subscribe(spy);
    fixture.detectChanges();
    btn().click();
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
