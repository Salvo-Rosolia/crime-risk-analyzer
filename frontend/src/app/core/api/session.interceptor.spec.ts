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

  it('adds the session token to relative requests', () => {
    http.get('/cities').subscribe();
    const req = ctrl.expectOne('/cities');
    expect(req.request.headers.get(SESSION_HEADER)).toBe(sessionId());
    req.flush([]);
  });

  it('does not send it to other hosts', () => {
    http.get('https://example.org/x').subscribe();
    const req = ctrl.expectOne('https://example.org/x');
    expect(req.request.headers.has(SESSION_HEADER)).toBe(false);
    req.flush({});
  });

  it('the token has the format accepted by the backend and stays the same within the tab', () => {
    const id = sessionId();
    expect(id).toMatch(/^[A-Za-z0-9_-]{16,128}$/);
    expect(sessionId()).toBe(id);
  });

  it('does not send it to protocol-relative URLs (//host)', () => {
    http.get('//example.org/x').subscribe();
    const req = ctrl.expectOne('//example.org/x');
    expect(req.request.headers.has(SESSION_HEADER)).toBe(false);
    req.flush({});
  });

  it('a 410 fonti_scadute marks the sources as expired', () => {
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

  it('other errors do not touch the sources state', () => {
    const store = TestBed.inject(SourcesStore);
    http.post('/analyze', {}).subscribe({ error: (e: HttpErrorResponse) => e });
    ctrl.expectOne('/analyze').flush({}, { status: 500, statusText: 'x' });
    expect(store.indicator().kind).toBe('default');
  });

  it('the 410 fonti_scadute also applies to the POI narrative', () => {
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
