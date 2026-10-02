import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ApiService } from '@core/api/api.service';
import { InputPanelComponent } from './input-panel.component';

describe('InputPanelComponent', () => {
  let fixture: ComponentFixture<InputPanelComponent>;
  let component: InputPanelComponent;
  let api: { cities: jest.Mock };

  function submitForm(): void {
    const form: HTMLFormElement = fixture.nativeElement.querySelector('form');
    form.dispatchEvent(new Event('submit', { cancelable: true }));
  }

  function setDomanda(value: string): void {
    const textarea: HTMLTextAreaElement = fixture.nativeElement.querySelector('#cra-domanda');
    textarea.value = value;
    textarea.dispatchEvent(new Event('input'));
  }

  function setFieldValue(selector: string, value: string): void {
    const input: HTMLInputElement = fixture.nativeElement.querySelector(selector);
    input.value = value;
    input.dispatchEvent(new Event('input'));
  }

  beforeEach(async () => {
    api = { cities: jest.fn().mockResolvedValue(['Roma', 'Milano', 'Napoli']) };
    await TestBed.configureTestingModule({
      imports: [InputPanelComponent],
      providers: [{ provide: ApiService, useValue: api }],
    }).compileComponents();
    fixture = TestBed.createComponent(InputPanelComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  });

  it('carica le città da ApiService.cities() e le propone nella datalist', () => {
    expect(api.cities).toHaveBeenCalled();
    const options = fixture.nativeElement.querySelectorAll('#cra-citta-options option');
    expect(options.length).toBe(3);
  });

  it('il bottone Analizza è sempre abilitato (pre-#318: meglio un submit che spiega cosa manca che un bottone disabilitato senza perché)', () => {
    fixture.componentRef.setInput('area', null);
    fixture.detectChanges();
    const btn: HTMLButtonElement = fixture.nativeElement.querySelector('button[type="submit"]');
    expect(btn.disabled).toBe(false);
  });

  it('emette AnalyzeRequestPayload con center/radiusM dal cerchio disegnato', () => {
    const spy = jest.fn();
    component.analyze.subscribe(spy);
    fixture.componentRef.setInput('area', {
      kind: 'circle',
      center: { lat: 41.9, lon: 12.5 },
      radiusM: 500,
    });
    fixture.detectChanges();
    component['domanda'].set('di sera?');
    fixture.nativeElement.querySelector('form').dispatchEvent(new Event('submit'));
    expect(spy).toHaveBeenCalledWith({
      area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 },
      domanda: 'di sera?',
    });
  });

  it('emette AnalyzeRequestPayload con citta/zona quando l’area è nella modalità città/zona', () => {
    const spy = jest.fn();
    component.analyze.subscribe(spy);
    fixture.componentRef.setInput('area', { kind: 'zone', citta: 'Roma', zona: 'Colosseo' });
    fixture.detectChanges();
    submitForm();
    expect(spy).toHaveBeenCalledWith({
      area: { kind: 'zone', citta: 'Roma', zona: 'Colosseo' },
      domanda: null,
    });
  });

  it('emette domanda null quando il campo è lasciato vuoto', () => {
    const spy = jest.fn();
    component.analyze.subscribe(spy);
    fixture.componentRef.setInput('area', {
      kind: 'circle',
      center: { lat: 41.9, lon: 12.5 },
      radiusM: 500,
    });
    fixture.detectChanges();
    submitForm();
    expect(spy).toHaveBeenCalledWith({
      area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 },
      domanda: null,
    });
  });

  it('trimma la domanda prima di emetterla', () => {
    const spy = jest.fn();
    component.analyze.subscribe(spy);
    fixture.componentRef.setInput('area', {
      kind: 'circle',
      center: { lat: 41.9, lon: 12.5 },
      radiusM: 500,
    });
    fixture.detectChanges();
    setDomanda('  di sera?  ');
    fixture.detectChanges();
    submitForm();
    expect(spy).toHaveBeenCalledWith({
      area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 },
      domanda: 'di sera?',
    });
  });

  it('senza area (né cerchio né città/zona compilate) il submit non emette analyze e mostra l’errore sul campo città', () => {
    const spy = jest.fn();
    component.analyze.subscribe(spy);
    fixture.componentRef.setInput('area', null);
    fixture.detectChanges();
    submitForm();
    fixture.detectChanges();
    expect(spy).not.toHaveBeenCalled();
    expect(fixture.nativeElement.textContent).toContain('Inserisci una città.');
    const cittaField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-citta');
    expect(cittaField.classList).toContain('cra-field-error');
  });

  it('con città compilata e zona vuota il submit mostra l’errore sul campo zona', () => {
    fixture.componentRef.setInput('area', null);
    fixture.componentRef.setInput('citta', 'Roma');
    fixture.detectChanges();
    submitForm();
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Inserisci una zona.');
    const zonaField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-zona');
    expect(zonaField.classList).toContain('cra-field-error');
  });

  it('digitare in città/zona emette cittaChange/zonaChange verso lo shell (stato condiviso, non posseduto qui)', () => {
    const cittaSpy = jest.fn();
    const zonaSpy = jest.fn();
    component.cittaChange.subscribe(cittaSpy);
    component.zonaChange.subscribe(zonaSpy);

    setFieldValue('#cra-citta', 'Milano');
    setFieldValue('#cra-zona', 'Duomo');

    expect(cittaSpy).toHaveBeenCalledWith('Milano');
    expect(zonaSpy).toHaveBeenCalledWith('Duomo');
  });

  it('il campo città/zona riflette l’input ricevuto dallo shell', () => {
    fixture.componentRef.setInput('citta', 'Napoli');
    fixture.componentRef.setInput('zona', 'Centro');
    fixture.detectChanges();
    const cittaField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-citta');
    const zonaField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-zona');
    expect(cittaField.value).toBe('Napoli');
    expect(zonaField.value).toBe('Centro');
  });

  it('a11y: il campo in errore porta aria-invalid e aria-describedby verso l’id del messaggio', () => {
    fixture.componentRef.setInput('area', null);
    fixture.detectChanges();
    submitForm();
    fixture.detectChanges();

    const cittaField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-citta');
    const zonaField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-zona');
    const errorMsg: HTMLElement = fixture.nativeElement.querySelector('.cra-input-error');

    expect(errorMsg.id).toBeTruthy();
    expect(cittaField.getAttribute('aria-invalid')).toBe('true');
    expect(cittaField.getAttribute('aria-describedby')).toBe(errorMsg.id);
    // Solo il campo imputato dalla validazione porta gli attributi: l'altro resta pulito.
    expect(zonaField.getAttribute('aria-invalid')).toBeNull();
    expect(zonaField.getAttribute('aria-describedby')).toBeNull();
  });

  it('il bottone è collegato via aria-describedby al testo che spiega le due modalità di scelta dell’area', () => {
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

  it('errore server con area in modalità città/zona: il bordo d’errore va sul campo zona', () => {
    fixture.componentRef.setInput('area', { kind: 'zone', citta: 'Roma', zona: 'Atlantide' });
    fixture.componentRef.setInput('serverError', '"Atlantide" non trovata.');
    fixture.detectChanges();
    const zonaField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-zona');
    expect(zonaField.classList).toContain('cra-field-error');
  });

  it('errore server con area a cerchio: nessun bordo d’errore sul campo zona (il geocoding del cerchio è cosmetico)', () => {
    fixture.componentRef.setInput('area', {
      kind: 'circle',
      center: { lat: 41.9, lon: 12.5 },
      radiusM: 500,
    });
    fixture.componentRef.setInput('serverError', 'Errore generico.');
    fixture.detectChanges();
    const zonaField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-zona');
    expect(zonaField.classList).not.toContain('cra-field-error');
  });

  it('BLOCCANTE (reperto review): un submit vuoto mostra "Inserisci una città.", ma disegnare un cerchio subito dopo azzera l’errore', () => {
    fixture.componentRef.setInput('area', null);
    fixture.detectChanges();
    submitForm();
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Inserisci una città.');

    fixture.componentRef.setInput('area', {
      kind: 'circle',
      center: { lat: 41.9, lon: 12.5 },
      radiusM: 500,
    });
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).not.toContain('Inserisci una città.');
    const cittaField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-citta');
    expect(cittaField.classList).not.toContain('cra-field-error');
  });

  it('BLOCCANTE (reperto review): un 503 in modalità cerchio non resta agganciato al campo zona dopo aver digitato una NUOVA città/zona', () => {
    const circleArea = { kind: 'circle' as const, center: { lat: 41.9, lon: 12.5 }, radiusM: 500 };
    fixture.componentRef.setInput('area', circleArea);
    fixture.componentRef.setInput('serverError', 'Servizio di geocoding non raggiungibile.');
    fixture.detectChanges();

    // La nuova area è un'altra ISTANZA (anche se, per assurdo, avesse valori uguali): simula lo
    // shell che ricalcola `area()` perché citta/zona sono appena diventate una coppia valida.
    fixture.componentRef.setInput('area', { kind: 'zone', citta: 'Roma', zona: 'Colosseo' });
    fixture.detectChanges();

    const zonaField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-zona');
    expect(zonaField.classList).not.toContain('cra-field-error');
  });

  it('un errore server sulla STESSA area città/zona (retry senza modificare i campi) resta agganciato al campo zona', () => {
    const zoneArea = { kind: 'zone' as const, citta: 'Roma', zona: 'Atlantide' };
    fixture.componentRef.setInput('area', zoneArea);
    fixture.componentRef.setInput('serverError', '"Atlantide" non trovata.');
    fixture.detectChanges();

    // Stesso riferimento (nessun cambio nei campi, retry identico): il bordo deve restare.
    fixture.componentRef.setInput('serverError', '"Atlantide" non trovata.');
    fixture.detectChanges();

    const zonaField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-zona');
    expect(zonaField.classList).toContain('cra-field-error');
  });
});

describe('InputPanelComponent — pre-fill della domanda pending (retry dopo un remount in Stato Errore)', () => {
  let fixture: ComponentFixture<InputPanelComponent>;

  beforeEach(async () => {
    const api = { cities: jest.fn().mockResolvedValue([]) };
    await TestBed.configureTestingModule({
      imports: [InputPanelComponent],
      providers: [{ provide: ApiService, useValue: api }],
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
