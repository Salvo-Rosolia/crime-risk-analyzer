import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { HttpErrorResponse } from '@angular/common/http';
import type { SourcesStatus } from '@core/models/models';
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

  describe('422 tipo_poi_non_riconosciuto (#467)', () => {
    const UNKNOWN = {
      detail: { errore: 'tipo_poi_non_riconosciuto', messaggio: 'tipo sconosciuto' },
    };
    const CUSTOM: SourcesStatus = {
      stato: 'attivo',
      scade_tra_secondi: 900,
      set: {
        kind: 'custom',
        classi: 2,
        selettori_osm: 4,
        versione_dati: '2024',
        luoghi: [],
        avvisi: [],
      },
    };
    const settle = () => new Promise((resolve) => setTimeout(resolve));

    function failWith(url: string, status: number, body: unknown): void {
      http.post(url, {}).subscribe({ error: (e: HttpErrorResponse) => e });
      ctrl.expectOne(url).flush(body, { status, statusText: 'x' });
    }

    afterEach(() => ctrl.verify());

    it('re-reads the status and changes the set key once even if the status is unchanged', async () => {
      const store = TestBed.inject(SourcesStore);
      const before = store.setKey();
      failWith('/analyze/baseline', 422, UNKNOWN);
      ctrl.expectOne('/sources').flush({ stato: 'default', scade_tra_secondi: null, set: null });
      await settle();
      expect(store.setKey()).not.toBe(before);
    });

    it('a status that changed is applied and the key changes by itself, with no extra bump', async () => {
      const store = TestBed.inject(SourcesStore);
      failWith('/analyze/baseline', 422, UNKNOWN);
      ctrl.expectOne('/sources').flush(CUSTOM);
      await settle();
      expect(store.indicator().kind).toBe('custom');
      expect(store.setKey()).toMatch(/^0:0:custom:/);
    });

    it('repeated 422 while the re-read is in flight cause a single re-read', async () => {
      failWith('/analyze/baseline', 422, UNKNOWN);
      failWith('/analyze/baseline', 422, UNKNOWN);
      ctrl.expectOne('/sources').flush(CUSTOM);
      await settle();
    });

    it.each([
      ['a list detail', '/analyze/baseline', 422, { detail: [{ msg: 'x' }] }],
      [
        'another object errore',
        '/analyze/baseline',
        422,
        { detail: { errore: 'zona_non_geocodificabile' } },
      ],
      ['a null body', '/analyze/baseline', 422, null],
      ['a string body', '/analyze/baseline', 422, 'boom'],
      ['the same body with another status', '/analyze/baseline', 500, UNKNOWN],
      ['the same error from another route', '/sources', 422, UNKNOWN],
    ])('does not react to %s', async (_label, url, status, body) => {
      const store = TestBed.inject(SourcesStore);
      const before = store.setKey();
      failWith(url, status, body);
      await settle();
      expect(store.setKey()).toBe(before);
    });
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
