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

  function setQuestion(value: string): void {
    const textarea: HTMLTextAreaElement = fixture.nativeElement.querySelector('#cra-question');
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

  it('loads the cities from ApiService.cities() and offers them in the datalist', () => {
    expect(api.cities).toHaveBeenCalled();
    const options = fixture.nativeElement.querySelectorAll('#cra-city-options option');
    expect(options.length).toBe(3);
  });

  it('the Analizza button is always enabled (pre-#318: better a submit that explains what is missing than a disabled button with no why)', () => {
    fixture.componentRef.setInput('area', null);
    fixture.detectChanges();
    const btn: HTMLButtonElement = fixture.nativeElement.querySelector('button[type="submit"]');
    expect(btn.disabled).toBe(false);
  });

  it('emits AnalyzeRequestPayload with center/radiusM from the drawn circle', () => {
    const spy = jest.fn();
    component.analyze.subscribe(spy);
    fixture.componentRef.setInput('area', {
      kind: 'circle',
      center: { lat: 41.9, lon: 12.5 },
      radiusM: 500,
    });
    fixture.detectChanges();
    component['question'].set('di sera?');
    fixture.nativeElement.querySelector('form').dispatchEvent(new Event('submit'));
    expect(spy).toHaveBeenCalledWith({
      area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 },
      question: 'di sera?',
    });
  });

  it('emits AnalyzeRequestPayload with city/zone when the area is in city/zone mode', () => {
    const spy = jest.fn();
    component.analyze.subscribe(spy);
    fixture.componentRef.setInput('area', { kind: 'zone', city: 'Roma', zone: 'Colosseo' });
    fixture.detectChanges();
    submitForm();
    expect(spy).toHaveBeenCalledWith({
      area: { kind: 'zone', city: 'Roma', zone: 'Colosseo' },
      question: null,
    });
  });

  it('emits question null when the field is left empty', () => {
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
      question: null,
    });
  });

  it('trims the question before emitting it', () => {
    const spy = jest.fn();
    component.analyze.subscribe(spy);
    fixture.componentRef.setInput('area', {
      kind: 'circle',
      center: { lat: 41.9, lon: 12.5 },
      radiusM: 500,
    });
    fixture.detectChanges();
    setQuestion('  di sera?  ');
    fixture.detectChanges();
    submitForm();
    expect(spy).toHaveBeenCalledWith({
      area: { kind: 'circle', center: { lat: 41.9, lon: 12.5 }, radiusM: 500 },
      question: 'di sera?',
    });
  });

  it('without an area (neither circle nor city/zone filled) the submit does not emit analyze and shows the error on the city field', () => {
    const spy = jest.fn();
    component.analyze.subscribe(spy);
    fixture.componentRef.setInput('area', null);
    fixture.detectChanges();
    submitForm();
    fixture.detectChanges();
    expect(spy).not.toHaveBeenCalled();
    expect(fixture.nativeElement.textContent).toContain('Inserisci una città.');
    const cityField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-city');
    expect(cityField.classList).toContain('cra-field-error');
  });

  it('with city filled and zone empty the submit shows the error on the zone field', () => {
    fixture.componentRef.setInput('area', null);
    fixture.componentRef.setInput('city', 'Roma');
    fixture.detectChanges();
    submitForm();
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Inserisci una zona.');
    const zoneField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-zone');
    expect(zoneField.classList).toContain('cra-field-error');
  });

  it('typing in city/zone emits cityChange/zoneChange towards the shell (shared state, not owned here)', () => {
    const citySpy = jest.fn();
    const zoneSpy = jest.fn();
    component.cityChange.subscribe(citySpy);
    component.zoneChange.subscribe(zoneSpy);

    setFieldValue('#cra-city', 'Milano');
    setFieldValue('#cra-zone', 'Duomo');

    expect(citySpy).toHaveBeenCalledWith('Milano');
    expect(zoneSpy).toHaveBeenCalledWith('Duomo');
  });

  it('the city/zone field reflects the input received from the shell', () => {
    fixture.componentRef.setInput('city', 'Napoli');
    fixture.componentRef.setInput('zone', 'Centro');
    fixture.detectChanges();
    const cityField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-city');
    const zoneField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-zone');
    expect(cityField.value).toBe('Napoli');
    expect(zoneField.value).toBe('Centro');
  });

  it('a11y: the field in error carries aria-invalid and aria-describedby pointing to the message id', () => {
    fixture.componentRef.setInput('area', null);
    fixture.detectChanges();
    submitForm();
    fixture.detectChanges();

    const cityField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-city');
    const zoneField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-zone');
    const errorMsg: HTMLElement = fixture.nativeElement.querySelector('.cra-input-error');

    expect(errorMsg.id).toBeTruthy();
    expect(cityField.getAttribute('aria-invalid')).toBe('true');
    expect(cityField.getAttribute('aria-describedby')).toBe(errorMsg.id);
    // Only the field attributed by the validation carries the attributes: the other stays clean.
    expect(zoneField.getAttribute('aria-invalid')).toBeNull();
    expect(zoneField.getAttribute('aria-describedby')).toBeNull();
  });

  it('the button is linked via aria-describedby to the text explaining the two area-selection modes', () => {
    const btn: HTMLButtonElement = fixture.nativeElement.querySelector('button[type="submit"]');
    const describedById = btn.getAttribute('aria-describedby');
    expect(describedById).toBeTruthy();
    const hint = fixture.nativeElement.querySelector(`#${describedById}`);
    expect(hint).toBeTruthy();
    expect(hint.classList).toContain('cra-hint');
  });

  it('shows the server error message (Error State) via the serverError input', () => {
    fixture.componentRef.setInput(
      'serverError',
      '"Atlantide" non corrisponde ad alcuna area nell\'ontologia.',
    );
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('non corrisponde ad alcuna area');
  });

  it('server error with area in city/zone mode: the error border goes on the zone field', () => {
    fixture.componentRef.setInput('area', { kind: 'zone', city: 'Roma', zone: 'Atlantide' });
    fixture.componentRef.setInput('serverError', '"Atlantide" non trovata.');
    fixture.detectChanges();
    const zoneField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-zone');
    expect(zoneField.classList).toContain('cra-field-error');
  });

  it('server error with a circle area: no error border on the zone field (the circle geocoding is cosmetic)', () => {
    fixture.componentRef.setInput('area', {
      kind: 'circle',
      center: { lat: 41.9, lon: 12.5 },
      radiusM: 500,
    });
    fixture.componentRef.setInput('serverError', 'Errore generico.');
    fixture.detectChanges();
    const zoneField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-zone');
    expect(zoneField.classList).not.toContain('cra-field-error');
  });

  it('BLOCKER (review finding): an empty submit shows "Inserisci una città.", but drawing a circle right after clears the error', () => {
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
    const cityField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-city');
    expect(cityField.classList).not.toContain('cra-field-error');
  });

  it('BLOCKER (review finding): a 503 in circle mode does not stay attached to the zone field after typing a NEW city/zone', () => {
    const circleArea = { kind: 'circle' as const, center: { lat: 41.9, lon: 12.5 }, radiusM: 500 };
    fixture.componentRef.setInput('area', circleArea);
    fixture.componentRef.setInput('serverError', 'Servizio di geocoding non raggiungibile.');
    fixture.detectChanges();

    // The new area is another INSTANCE (even if, absurdly, it had equal values): it simulates the
    // shell recomputing `area()` because city/zone have just become a valid pair.
    fixture.componentRef.setInput('area', { kind: 'zone', city: 'Roma', zone: 'Colosseo' });
    fixture.detectChanges();

    const zoneField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-zone');
    expect(zoneField.classList).not.toContain('cra-field-error');
  });

  it('a server error on the SAME city/zone area (retry without modifying the fields) stays attached to the zone field', () => {
    const zoneArea = { kind: 'zone' as const, city: 'Roma', zone: 'Atlantide' };
    fixture.componentRef.setInput('area', zoneArea);
    fixture.componentRef.setInput('serverError', '"Atlantide" non trovata.');
    fixture.detectChanges();

    // Same reference (no change in the fields, identical retry): the border must stay.
    fixture.componentRef.setInput('serverError', '"Atlantide" non trovata.');
    fixture.detectChanges();

    const zoneField: HTMLInputElement = fixture.nativeElement.querySelector('#cra-zone');
    expect(zoneField.classList).toContain('cra-field-error');
  });
});

describe('InputPanelComponent — pre-fill of the pending question (retry after a remount in Error State)', () => {
  let fixture: ComponentFixture<InputPanelComponent>;

  beforeEach(async () => {
    const api = { cities: jest.fn().mockResolvedValue([]) };
    await TestBed.configureTestingModule({
      imports: [InputPanelComponent],
      providers: [{ provide: ApiService, useValue: api }],
    }).compileComponents();
    fixture = TestBed.createComponent(InputPanelComponent);
    // NO detectChanges here: the test sets the input *before* the first cycle,
    // so ngOnInit reads it exactly as a real remount of the @switch would.
  });

  it('remount (real path INPUT→LOADING→ERROR): repopulates question from the initialQuestion input', () => {
    fixture.componentRef.setInput('initialQuestion', 'di sera?');
    fixture.detectChanges();

    const question: HTMLTextAreaElement = fixture.nativeElement.querySelector('#cra-question');
    expect(question.value).toBe('di sera?');
  });

  it('without a pending value (first mount, State A) the question field stays empty', () => {
    fixture.detectChanges();
    const question: HTMLTextAreaElement = fixture.nativeElement.querySelector('#cra-question');
    expect(question.value).toBe('');
  });
});
