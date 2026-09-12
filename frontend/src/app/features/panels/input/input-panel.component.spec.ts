import { ComponentFixture, TestBed } from '@angular/core/testing';
import { InputPanelComponent } from './input-panel.component';

describe('InputPanelComponent', () => {
  let fixture: ComponentFixture<InputPanelComponent>;
  let component: InputPanelComponent;

  function submitForm(): void {
    const form: HTMLFormElement = fixture.nativeElement.querySelector('form');
    form.dispatchEvent(new Event('submit', { cancelable: true }));
  }

  function setDomanda(value: string): void {
    const textarea: HTMLTextAreaElement = fixture.nativeElement.querySelector('#cra-domanda');
    textarea.value = value;
    textarea.dispatchEvent(new Event('input'));
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [InputPanelComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(InputPanelComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('il bottone Analizza è disabilitato senza un cerchio disegnato', () => {
    fixture.componentRef.setInput('circle', null);
    fixture.detectChanges();
    const btn: HTMLButtonElement = fixture.nativeElement.querySelector('button[type="submit"]');
    expect(btn.disabled).toBe(true);
  });

  it('il bottone Analizza è abilitato quando un cerchio è stato disegnato', () => {
    fixture.componentRef.setInput('circle', { lat: 41.9, lon: 12.5, radiusM: 500 });
    fixture.detectChanges();
    const btn: HTMLButtonElement = fixture.nativeElement.querySelector('button[type="submit"]');
    expect(btn.disabled).toBe(false);
  });

  it('emette AnalyzeRequestPayload con center/radiusM dal cerchio disegnato', () => {
    const spy = jest.fn();
    component.analyze.subscribe(spy);
    fixture.componentRef.setInput('circle', { lat: 41.9, lon: 12.5, radiusM: 500 });
    fixture.detectChanges();
    component['domanda'].set('di sera?');
    fixture.nativeElement.querySelector('form').dispatchEvent(new Event('submit'));
    expect(spy).toHaveBeenCalledWith({
      center: { lat: 41.9, lon: 12.5 },
      radiusM: 500,
      domanda: 'di sera?',
    });
  });

  it('emette domanda null quando il campo è lasciato vuoto', () => {
    const spy = jest.fn();
    component.analyze.subscribe(spy);
    fixture.componentRef.setInput('circle', { lat: 41.9, lon: 12.5, radiusM: 500 });
    fixture.detectChanges();
    submitForm();
    expect(spy).toHaveBeenCalledWith({
      center: { lat: 41.9, lon: 12.5 },
      radiusM: 500,
      domanda: null,
    });
  });

  it('trimma la domanda prima di emetterla', () => {
    const spy = jest.fn();
    component.analyze.subscribe(spy);
    fixture.componentRef.setInput('circle', { lat: 41.9, lon: 12.5, radiusM: 500 });
    fixture.detectChanges();
    setDomanda('  di sera?  ');
    fixture.detectChanges();
    submitForm();
    expect(spy).toHaveBeenCalledWith({
      center: { lat: 41.9, lon: 12.5 },
      radiusM: 500,
      domanda: 'di sera?',
    });
  });

  it('senza cerchio il submit non emette analyze (guardia difensiva anche a bottone disabilitato)', () => {
    const spy = jest.fn();
    component.analyze.subscribe(spy);
    fixture.componentRef.setInput('circle', null);
    fixture.detectChanges();
    submitForm();
    expect(spy).not.toHaveBeenCalled();
  });

  it('il bottone disabilitato è collegato via aria-describedby al testo che spiega perché (fix reperto review accessibilità)', () => {
    fixture.componentRef.setInput('circle', null);
    fixture.detectChanges();
    const btn: HTMLButtonElement = fixture.nativeElement.querySelector('button[type="submit"]');
    const describedById = btn.getAttribute('aria-describedby');
    expect(describedById).toBeTruthy();
    const hint = fixture.nativeElement.querySelector(`#${describedById}`);
    expect(hint).toBeTruthy();
    expect(hint.classList).toContain('cra-hint');
  });

  it('mostra il messaggio di errore server (Stato Errore) via input serverError', () => {
    fixture.componentRef.setInput(
      'serverError',
      '"Atlantide" non corrisponde ad alcuna area nell\'ontologia.',
    );
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('non corrisponde ad alcuna area');
  });
});

describe('InputPanelComponent — pre-fill della domanda pending (retry dopo un remount in Stato Errore)', () => {
  let fixture: ComponentFixture<InputPanelComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [InputPanelComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(InputPanelComponent);
    // NIENTE detectChanges qui: il test imposta l'input *prima* del primo ciclo,
    // così ngOnInit lo legge esattamente come farebbe un remount reale dello @switch.
  });

  it("rimonto (percorso reale INPUT→LOADING→ERROR): ripopola domanda dall'input initialDomanda", () => {
    fixture.componentRef.setInput('initialDomanda', 'di sera?');
    fixture.detectChanges();

    const domanda: HTMLTextAreaElement = fixture.nativeElement.querySelector('#cra-domanda');
    expect(domanda.value).toBe('di sera?');
  });

  it('senza valore pending (primo mount, Stato A) il campo domanda resta vuoto', () => {
    fixture.detectChanges();
    const domanda: HTMLTextAreaElement = fixture.nativeElement.querySelector('#cra-domanda');
    expect(domanda.value).toBe('');
  });
});
