import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { HttpErrorResponse } from '@angular/common/http';
import { SourcesStore } from '@core/state/sources.store';
import { sessionInterceptor } from './session.interceptor';
import { SESSION_HEADER, sessionId } from './session-id';

describe('sessionInterceptor', () => {
  let http: HttpClient;
  let ctrl: HttpTestingController;

  beforeEach(() => {
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([sessionInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    ctrl = TestBed.inject(HttpTestingController);
  });

  it('aggiunge il token di sessione alle richieste relative', () => {
    http.get('/cities').subscribe();
    const req = ctrl.expectOne('/cities');
    expect(req.request.headers.get(SESSION_HEADER)).toBe(sessionId());
    req.flush([]);
  });

  it('non lo manda agli altri host', () => {
    http.get('https://example.org/x').subscribe();
    const req = ctrl.expectOne('https://example.org/x');
    expect(req.request.headers.has(SESSION_HEADER)).toBe(false);
    req.flush({});
  });

  it('il token ha il formato accettato dal backend e resta lo stesso nella scheda', () => {
    const id = sessionId();
    expect(id).toMatch(/^[A-Za-z0-9_-]{16,128}$/);
    expect(sessionId()).toBe(id);
  });

  it('non lo manda agli URL protocol-relative (//host)', () => {
    http.get('//example.org/x').subscribe();
    const req = ctrl.expectOne('//example.org/x');
    expect(req.request.headers.has(SESSION_HEADER)).toBe(false);
    req.flush({});
  });

  it('un 410 fonti_scadute segna le fonti come scadute', () => {
    const store = TestBed.inject(SourcesStore);
    http.post('/analyze', {}).subscribe({ error: (e: HttpErrorResponse) => e });
    ctrl
      .expectOne('/analyze')
      .flush(
        { detail: { errore: 'fonti_scadute', messaggio: 'scadute' } },
        { status: 410, statusText: 'Gone' },
      );
    expect(store.indicator().kind).toBe('expired');
  });

  it('altri errori non toccano lo stato delle fonti', () => {
    const store = TestBed.inject(SourcesStore);
    http.post('/analyze', {}).subscribe({ error: (e: HttpErrorResponse) => e });
    ctrl.expectOne('/analyze').flush({}, { status: 500, statusText: 'x' });
    expect(store.indicator().kind).toBe('default');
  });

  it('il 410 fonti_scadute vale anche per la narrativa del POI', () => {
    const store = TestBed.inject(SourcesStore);
    http.post('/analyze/poi', {}).subscribe({ error: (e: HttpErrorResponse) => e });
    ctrl
      .expectOne('/analyze/poi')
      .flush(
        { detail: { errore: 'fonti_scadute', messaggio: 'scadute' } },
        { status: 410, statusText: 'Gone' },
      );
    expect(store.indicator().kind).toBe('expired');
  });
});
