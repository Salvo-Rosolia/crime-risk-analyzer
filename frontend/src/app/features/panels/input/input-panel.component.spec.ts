import { ComponentFixture, TestBed } from '@angular/core/testing';
import { InputPanelComponent } from './input-panel.component';
import { ApiService } from '@core/api/api.service';

describe('InputPanelComponent', () => {
  let fixture: ComponentFixture<InputPanelComponent>;
  let api: { cities: jest.Mock };

  function setCitta(value: string): void {
    const input: HTMLInputElement = fixture.nativeElement.querySelector('#cra-citta');
    input.value = value;
    input.dispatchEvent(new Event('input'));
  }

  function setZona(value: string): void {
    const input: HTMLInputElement = fixture.nativeElement.querySelector('#cra-zona');
    input.value = value;
    input.dispatchEvent(new Event('input'));
  }

  function submitForm(): void {
    const form: HTMLFormElement = fixture.nativeElement.querySelector('form');
    form.dispatchEvent(new Event('submit', { cancelable: true }));
  }

  beforeEach(async () => {
    api = { cities: jest.fn().mockResolvedValue(['Roma', 'Milano', 'Napoli']) };
    await TestBed.configureTestingModule({
      imports: [InputPanelComponent],
      providers: [{ provide: ApiService, useValue: api }],
    }).compileComponents();
    fixture = TestBed.createComponent(InputPanelComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  });

  it('carica le città da ApiService.cities() e le propone nella datalist', () => {
    expect(api.cities).toHaveBeenCalled();
    const options = fixture.nativeElement.querySelectorAll('#cra-citta-options option');
    expect(Array.from(options).map((o) => (o as HTMLOptionElement).value)).toEqual([
      'Roma',
      'Milano',
      'Napoli',
    ]);
  });

  it("senza città valorizzata NON invia analyze e mostra l'errore di validazione", () => {
    const spy = jest.fn();
    fixture.componentInstance.analyze.subscribe(spy);

    setZona('Trastevere');
    fixture.detectChanges();
    submitForm();
    fixture.detectChanges();

    expect(spy).not.toHaveBeenCalled();
    expect(fixture.nativeElement.textContent).toContain('Seleziona una città');
  });

  it("con città non supportata mostra l'errore e non invia", () => {
    const spy = jest.fn();
    fixture.componentInstance.analyze.subscribe(spy);

    setCitta('Atlantide');
    setZona('Centro');
    fixture.detectChanges();
    submitForm();
    fixture.detectChanges();

    expect(spy).not.toHaveBeenCalled();
    expect(fixture.nativeElement.textContent).toContain('non supportata');
  });

  it("senza zona valorizzata (ma con città valida) NON invia e mostra l'errore zona", () => {
    const spy = jest.fn();
    fixture.componentInstance.analyze.subscribe(spy);

    setCitta('Roma');
    fixture.detectChanges();
    submitForm();
    fixture.detectChanges();

    expect(spy).not.toHaveBeenCalled();
    expect(fixture.nativeElement.textContent).toContain('Inserisci una zona');
  });

  it('con città e zona valide invia analyze con il payload atteso (domanda opzionale assente)', () => {
    const spy = jest.fn();
    fixture.componentInstance.analyze.subscribe(spy);

    setCitta('Roma');
    setZona('Colosseo');
    fixture.detectChanges();
    submitForm();

    expect(spy).toHaveBeenCalledWith({ citta: 'Roma', zona: 'Colosseo', domanda: null });
  });

  it('include la domanda opzionale (trimmata) quando valorizzata', () => {
    const spy = jest.fn();
    fixture.componentInstance.analyze.subscribe(spy);

    setCitta('Roma');
    setZona('Colosseo');
    const textarea: HTMLTextAreaElement = fixture.nativeElement.querySelector('#cra-domanda');
    textarea.value = '  di sera?  ';
    textarea.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    submitForm();

    expect(spy).toHaveBeenCalledWith({ citta: 'Roma', zona: 'Colosseo', domanda: 'di sera?' });
  });

  it('mostra il messaggio di errore server (Stato Errore) via input serverError', () => {
    fixture.componentRef.setInput(
      'serverError',
      '"Atlantide" non corrisponde ad alcuna area nell\'ontologia.',
    );
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('non corrisponde ad alcuna area');
  });

  it('la validazione client ha priorità sul messaggio server quando entrambi sono presenti', () => {
    fixture.componentRef.setInput('serverError', 'errore server');
    submitForm();
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Seleziona una città');
  });

  it('i campi hanno aria-required per la a11y (senza il required nativo, per non bypassare la validazione custom)', () => {
    const citta: HTMLInputElement = fixture.nativeElement.querySelector('#cra-citta');
    const zona: HTMLInputElement = fixture.nativeElement.querySelector('#cra-zona');
    expect(citta.getAttribute('aria-required')).toBe('true');
    expect(zona.getAttribute('aria-required')).toBe('true');
  });

  it("l'errore di validazione si pulisce mentre si digita (non resta stale durante la correzione)", () => {
    submitForm();
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Seleziona una città');

    setCitta('R');
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).not.toContain('Seleziona una città');
  });

  it("bordo d'errore per-campo: un errore di sola città non evidenzia la zona", () => {
    setZona('Trastevere');
    fixture.detectChanges();
    submitForm();
    fixture.detectChanges();

    const citta: HTMLInputElement = fixture.nativeElement.querySelector('#cra-citta');
    const zona: HTMLInputElement = fixture.nativeElement.querySelector('#cra-zona');
    expect(citta.classList.contains('cra-field-error')).toBe(true);
    expect(zona.classList.contains('cra-field-error')).toBe(false);
  });

  it("bordo d'errore per-campo: un errore di sola zona non evidenzia la città", () => {
    setCitta('Roma');
    fixture.detectChanges();
    submitForm();
    fixture.detectChanges();

    const citta: HTMLInputElement = fixture.nativeElement.querySelector('#cra-citta');
    const zona: HTMLInputElement = fixture.nativeElement.querySelector('#cra-zona');
    expect(zona.classList.contains('cra-field-error')).toBe(true);
    expect(citta.classList.contains('cra-field-error')).toBe(false);
  });

  it("l'errore server (Stato Errore) evidenzia il bordo della zona, non della città", () => {
    fixture.componentRef.setInput('serverError', '"Atlantide" non corrisponde ad alcuna area.');
    fixture.detectChanges();

    const citta: HTMLInputElement = fixture.nativeElement.querySelector('#cra-citta');
    const zona: HTMLInputElement = fixture.nativeElement.querySelector('#cra-zona');
    expect(zona.classList.contains('cra-field-error')).toBe(true);
    expect(citta.classList.contains('cra-field-error')).toBe(false);
  });
});

describe('InputPanelComponent — pre-fill dai valori pending dello store (retry dopo un remount in Stato Errore)', () => {
  let fixture: ComponentFixture<InputPanelComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [InputPanelComponent],
      providers: [{ provide: ApiService, useValue: { cities: jest.fn().mockResolvedValue([]) } }],
    }).compileComponents();
    fixture = TestBed.createComponent(InputPanelComponent);
    // NIENTE detectChanges qui: i test impostano gli input *prima* del primo ciclo,
    // così ngOnInit li legge esattamente come farebbe un remount reale dello @switch.
  });

  it('rimonto (percorso reale INPUT→LOADING→ERROR): ripopola citta/zona/domanda dagli input initial*', () => {
    fixture.componentRef.setInput('initialCitta', 'Roma');
    fixture.componentRef.setInput('initialZona', 'Atlantide');
    fixture.componentRef.setInput('initialDomanda', 'di sera?');
    fixture.detectChanges();

    const citta: HTMLInputElement = fixture.nativeElement.querySelector('#cra-citta');
    const zona: HTMLInputElement = fixture.nativeElement.querySelector('#cra-zona');
    const domanda: HTMLTextAreaElement = fixture.nativeElement.querySelector('#cra-domanda');
    expect(citta.value).toBe('Roma');
    expect(zona.value).toBe('Atlantide');
    expect(domanda.value).toBe('di sera?');
  });

  it('senza valori pending (primo mount, Stato A) i campi restano vuoti', () => {
    fixture.detectChanges();
    const citta: HTMLInputElement = fixture.nativeElement.querySelector('#cra-citta');
    const zona: HTMLInputElement = fixture.nativeElement.querySelector('#cra-zona');
    expect(citta.value).toBe('');
    expect(zona.value).toBe('');
  });
});
