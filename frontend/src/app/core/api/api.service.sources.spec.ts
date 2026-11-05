import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ApiService } from '@core/api/api.service';
import type { SourcesStatus } from '@core/models/models';

const active: SourcesStatus = {
  stato: 'attivo',
  source_set_id: 'example',
  scade_tra_secondi: 600,
  set: {
    kind: 'example',
    classi: 3,
    selettori_osm: 5,
    versione_dati: '2024',
    luoghi: [],
    avvisi: [],
  },
};

describe('ApiService - sources', () => {
  let api: ApiService;
  let ctrl: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(ApiService);
    ctrl = TestBed.inject(HttpTestingController);
  });

  afterEach(() => ctrl.verify());

  it('sourcesStatus: GET /sources', async () => {
    const p = api.sourcesStatus();
    const req = ctrl.expectOne('/sources');
    expect(req.request.method).toBe('GET');
    req.flush(active);
    expect(await p).toEqual(active);
  });

  it('useExampleSources: POST /sources/example', async () => {
    const p = api.useExampleSources();
    const req = ctrl.expectOne('/sources/example');
    expect(req.request.method).toBe('POST');
    req.flush(active);
    expect(await p).toEqual(active);
  });

  it('resetSources: DELETE /sources', async () => {
    const p = api.resetSources();
    const req = ctrl.expectOne('/sources');
    expect(req.request.method).toBe('DELETE');
    req.flush({ stato: 'default', scade_tra_secondi: null, set: null, source_set_id: 'default' });
    expect((await p).stato).toBe('default');
  });

  it('uploadSources: multipart POST with the files and only the indicated vocabulary fields', async () => {
    const f = (n: string) => new File(['x'], n);
    const p = api.uploadSources({
      ontology: f('o.ttl'),
      osm_table: f('osm.csv'),
      data: f('d.csv'),
      hazard_table: f('h.csv'),
      vocabulary: { namespace: 'http://x/#', hazard: '', vulnerability: ['a', 'b'] },
    });
    const req = ctrl.expectOne('/sources');
    expect(req.request.method).toBe('POST');
    const body = req.request.body as FormData;
    expect((body.get('ontology') as File).name).toBe('o.ttl');
    expect((body.get('hazard_table') as File).name).toBe('h.csv');
    expect(body.has('boundaries')).toBe(false);
    expect(body.get('namespace')).toBe('http://x/#');
    expect(body.has('hazard')).toBe(false);
    expect(body.getAll('vulnerability')).toEqual(['a', 'b']);
    req.flush(active);
    await p;
  });

  it('uploadSources: attaches the boundaries if present', async () => {
    const f = (n: string) => new File(['x'], n);
    const p = api.uploadSources({
      ontology: f('o.ttl'),
      osm_table: f('osm.csv'),
      data: f('d.csv'),
      hazard_table: f('h.csv'),
      boundaries: f('b.geojson'),
    });
    const req = ctrl.expectOne('/sources');
    expect((req.request.body as FormData).has('boundaries')).toBe(true);
    req.flush(active);
    await p;
  });

  describe('response shape (#473)', () => {
    const SHAPE_ERROR = 'Risposta del server in un formato inatteso.';
    const noId = { stato: 'default', scade_tra_secondi: null, set: null };

    it.each([
      ['sourcesStatus', () => api.sourcesStatus(), '/sources'],
      ['useExampleSources', () => api.useExampleSources(), '/sources/example'],
      ['resetSources', () => api.resetSources(), '/sources'],
    ])('%s: a status without source_set_id rejects', async (_name, call, url) => {
      const p = call();
      ctrl.expectOne(url).flush(noId);
      await expect(p).rejects.toThrow(SHAPE_ERROR);
    });

    it('uploadSources: a status without source_set_id rejects', async () => {
      const f = (n: string) => new File(['x'], n);
      const p = api.uploadSources({
        ontology: f('o.ttl'),
        osm_table: f('osm.csv'),
        data: f('d.csv'),
        hazard_table: f('h.csv'),
      });
      ctrl.expectOne('/sources').flush(noId);
      await expect(p).rejects.toThrow(SHAPE_ERROR);
    });

    it('sourcesStatus: an unknown stato or a non-string id rejects', async () => {
      const p1 = api.sourcesStatus();
      ctrl.expectOne('/sources').flush({ ...noId, source_set_id: 'default', stato: 'boh' });
      await expect(p1).rejects.toThrow(SHAPE_ERROR);
      const p2 = api.sourcesStatus();
      ctrl.expectOne('/sources').flush({ ...noId, source_set_id: 7 });
      await expect(p2).rejects.toThrow(SHAPE_ERROR);
    });

    it('sourcesStatus: an expired status keeps the default id', async () => {
      const expired = {
        stato: 'scaduto',
        scade_tra_secondi: null,
        set: null,
        source_set_id: 'default',
      };
      const p = api.sourcesStatus();
      ctrl.expectOne('/sources').flush(expired);
      await expect(p).resolves.toEqual(expired);
    });
  });

  it('templateUrl: relative path of the template', () => {
    expect(api.templateUrl('osm_table')).toBe('/sources/templates/osm_table');
  });
});
