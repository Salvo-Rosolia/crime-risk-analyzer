import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ApiService } from '@core/api/api.service';
import type { SourcesStatus } from '@core/models/models';

const attivo: SourcesStatus = {
  stato: 'attivo',
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

describe('ApiService - fonti', () => {
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
    req.flush(attivo);
    expect(await p).toEqual(attivo);
  });

  it('useExampleSources: POST /sources/example', async () => {
    const p = api.useExampleSources();
    const req = ctrl.expectOne('/sources/example');
    expect(req.request.method).toBe('POST');
    req.flush(attivo);
    expect(await p).toEqual(attivo);
  });

  it('resetSources: DELETE /sources', async () => {
    const p = api.resetSources();
    const req = ctrl.expectOne('/sources');
    expect(req.request.method).toBe('DELETE');
    req.flush({ stato: 'default', scade_tra_secondi: null, set: null });
    expect((await p).stato).toBe('default');
  });

  it('uploadSources: POST multipart con i file e solo i campi del vocabolario indicati', async () => {
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
    req.flush(attivo);
    await p;
  });

  it('uploadSources: allega i confini se presenti', async () => {
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
    req.flush(attivo);
    await p;
  });

  it('templateUrl: percorso relativo del modello', () => {
    expect(api.templateUrl('osm_table')).toBe('/sources/templates/osm_table');
  });
});
