import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { ApiService } from '@core/api/api.service';
import type { SourceProblem, SourcesStatus, SourceUpload } from '@core/models/models';
import { SourcesStore } from './sources.store';

const DEFAULT: SourcesStatus = { stato: 'default', scade_tra_secondi: null, set: null };
const set = (kind: 'example' | 'custom', avvisi: SourceProblem[] = []): SourcesStatus => ({
  stato: 'attivo',
  scade_tra_secondi: 900,
  set: { kind, classi: 2, selettori_osm: 4, versione_dati: '2024', luoghi: ['Roma'], avvisi },
});
const problem = (file: SourceProblem['file'], message: string): SourceProblem => ({
  code: 'x',
  file,
  message,
  line: null,
});
const upload = { ontology: new File(['x'], 'o.ttl') } as unknown as SourceUpload;

describe('SourcesStore', () => {
  let api: {
    sourcesStatus: jest.Mock;
    uploadSources: jest.Mock;
    useExampleSources: jest.Mock;
    resetSources: jest.Mock;
  };
  let store: SourcesStore;

  beforeEach(() => {
    api = {
      sourcesStatus: jest.fn().mockResolvedValue(DEFAULT),
      uploadSources: jest.fn(),
      useExampleSources: jest.fn(),
      resetSources: jest.fn(),
    };
    TestBed.configureTestingModule({ providers: [{ provide: ApiService, useValue: api }] });
    store = TestBed.inject(SourcesStore);
  });

  it('without a known state the indicator says Predefinite', () => {
    expect(store.indicator()).toEqual({ label: 'Predefinite', kind: 'default' });
  });

  it('refresh reads the state from the backend', async () => {
    api.sourcesStatus.mockResolvedValue(set('custom'));
    await store.refresh();
    expect(store.indicator()).toEqual({ label: 'Personalizzate', kind: 'custom' });
  });

  it('refresh with the backend down leaves the indicator on the default, with no error', async () => {
    api.sourcesStatus.mockRejectedValue(new HttpErrorResponse({ status: 0 }));
    await store.refresh();
    expect(store.indicator().kind).toBe('default');
    expect(store.message()).toBeNull();
  });

  it('expired: indicator Scadute', async () => {
    api.sourcesStatus.mockResolvedValue({ stato: 'scaduto', scade_tra_secondi: null, set: null });
    await store.refresh();
    expect(store.indicator()).toEqual({ label: 'Scadute', kind: 'expired' });
  });

  it('useExample activates the example and signals the change', async () => {
    api.useExampleSources.mockResolvedValue(set('example'));
    expect(await store.useExample()).toBe(true);
    expect(store.indicator()).toEqual({ label: 'Esempio', kind: 'example' });
    expect(store.busy()).toBeNull();
  });

  it('reset goes back to the default', async () => {
    api.resetSources.mockResolvedValue(DEFAULT);
    expect(await store.reset()).toBe(true);
    expect(store.indicator().kind).toBe('default');
  });

  it('valid upload: active state and warnings of the set visible', async () => {
    const warning = problem('data', 'Colonna ignorata');
    api.uploadSources.mockResolvedValue(set('custom', [warning]));
    expect(await store.upload(upload)).toBe(true);
    expect(store.report()).toBeNull();
    expect(store.activeWarnings()).toEqual([warning]);
  });

  it('rejected upload (422): report with errors and warnings, no change', async () => {
    const err = problem('ontology', 'File non leggibile');
    const warn = problem('data', 'Riga vuota');
    api.uploadSources.mockRejectedValue(
      new HttpErrorResponse({
        status: 422,
        error: {
          detail: {
            errore: 'fonti_non_valide',
            messaggio: 'i file caricati non sono validi: correggi e riprova',
            errors: [err],
            warnings: [warn],
          },
        },
      }),
    );
    expect(await store.upload(upload)).toBe(false);
    expect(store.report()).toEqual({ errors: [err], warnings: [warn] });
    expect(store.message()).toBeNull();
    expect(store.busy()).toBeNull();
  });

  it('failed upload for another reason: backend message', async () => {
    api.uploadSources.mockRejectedValue(
      new HttpErrorResponse({
        status: 503,
        error: { detail: { errore: 'caricamento_occupato', messaggio: 'troppi caricamenti' } },
      }),
    );
    expect(await store.upload(upload)).toBe(false);
    expect(store.message()).toBe('troppi caricamenti');
    expect(store.report()).toBeNull();
  });

  it('a new outcome clears the previous report and message', async () => {
    api.uploadSources.mockRejectedValue(new HttpErrorResponse({ status: 500 }));
    await store.upload(upload);
    expect(store.message()).not.toBeNull();
    api.useExampleSources.mockResolvedValue(set('example'));
    await store.useExample();
    expect(store.message()).toBeNull();
  });

  it('busy marks the operation in progress', async () => {
    let done!: (s: SourcesStatus) => void;
    api.resetSources.mockReturnValue(new Promise<SourcesStatus>((r) => (done = r)));
    const p = store.reset();
    expect(store.busy()).toBe('reset');
    done(DEFAULT);
    await p;
    expect(store.busy()).toBeNull();
  });

  it('open/close of the page', () => {
    store.openPage();
    expect(store.open()).toBe(true);
    store.closePage();
    expect(store.open()).toBe(false);
  });

  describe('revision (effective change of the active set)', () => {
    it('successful upload: always increments (they are new files)', async () => {
      api.uploadSources.mockResolvedValue(set('custom'));
      await store.upload(upload);
      api.uploadSources.mockResolvedValue(set('custom'));
      await store.upload(upload);
      expect(store.revision()).toBe(2);
    });

    it('rejected upload: does not increment', async () => {
      api.uploadSources.mockRejectedValue(new HttpErrorResponse({ status: 500 }));
      await store.upload(upload);
      expect(store.revision()).toBe(0);
    });

    it('example from default increments, example already active does not', async () => {
      api.useExampleSources.mockResolvedValue(set('example'));
      await store.useExample();
      expect(store.revision()).toBe(1);
      await store.useExample();
      expect(store.revision()).toBe(1);
    });

    it('reset from active sources increments, reset already at default does not', async () => {
      api.resetSources.mockResolvedValue(DEFAULT);
      await store.reset();
      expect(store.revision()).toBe(0);
      api.useExampleSources.mockResolvedValue(set('example'));
      await store.useExample();
      await store.reset();
      expect(store.revision()).toBe(2);
    });

    it('reset from expired increments (the results on screen were on the expired set)', async () => {
      store.markExpired();
      api.resetSources.mockResolvedValue(DEFAULT);
      await store.reset();
      expect(store.revision()).toBe(1);
    });
  });

  describe('setKey (identity of the active set, #463)', () => {
    it('changes on example and expiry; stays put on a refresh that changes nothing', async () => {
      const keys = [store.setKey()];
      api.useExampleSources.mockResolvedValue(set('example'));
      await store.useExample();
      keys.push(store.setKey());
      api.sourcesStatus.mockResolvedValue(set('example'));
      await store.refresh();
      expect(store.setKey()).toBe(keys[1]);
      store.markExpired();
      expect(store.setKey()).not.toBe(keys[1]);
      expect(new Set(keys).size).toBe(keys.length);
    });

    it('expired and default share the key: the step from one to the other reloads nothing', async () => {
      const initial = store.setKey();
      api.useExampleSources.mockResolvedValue(set('example'));
      await store.useExample();
      store.markExpired();
      const expired = store.setKey();
      api.resetSources.mockResolvedValue(DEFAULT);
      await store.reset();
      expect(expired).toBe(initial);
      expect(store.setKey()).toBe(initial);
    });

    it('markPoiTypesStale re-reads the status and changes the key even if the status does not (#467)', async () => {
      const before = store.setKey();
      await store.markPoiTypesStale();
      expect(api.sourcesStatus).toHaveBeenCalledTimes(1);
      expect(store.setKey()).not.toBe(before);
    });

    it('markPoiTypesStale with a changed status applies it and changes the key once, revision untouched', async () => {
      api.sourcesStatus.mockResolvedValue(set('custom'));
      const before = store.setKey();
      await store.markPoiTypesStale();
      expect(store.indicator().kind).toBe('custom');
      expect(store.setKey()).not.toBe(before);
      expect(store.setKey()).toMatch(/^0:0:custom:/);
      expect(store.revision()).toBe(0);
    });

    it('markPoiTypesStale with the backend down still invalidates the key', async () => {
      api.sourcesStatus.mockRejectedValue(new HttpErrorResponse({ status: 0 }));
      const before = store.setKey();
      await store.markPoiTypesStale();
      expect(store.setKey()).not.toBe(before);
    });

    it('markPoiTypesStale calls made while one is in flight are ignored', async () => {
      await Promise.all([store.markPoiTypesStale(), store.markPoiTypesStale()]);
      expect(api.sourcesStatus).toHaveBeenCalledTimes(1);
    });
  });

  it('markExpired brings the indicator to Scadute without calling the network', () => {
    store.markExpired();
    expect(store.indicator()).toEqual({ label: 'Scadute', kind: 'expired' });
    expect(api.sourcesStatus).not.toHaveBeenCalled();
  });

  it('opening the page re-reads the state from the backend', () => {
    store.openPage();
    expect(api.sourcesStatus).toHaveBeenCalledTimes(1);
  });

  describe('in-flight refresh does not overwrite a more recent state', () => {
    const deferred = () => {
      let resolve!: (s: SourcesStatus) => void;
      const promise = new Promise<SourcesStatus>((r) => (resolve = r));
      return { promise, resolve };
    };

    it('markExpired during a refresh: stays Scadute', async () => {
      const d = deferred();
      api.sourcesStatus.mockReturnValue(d.promise);
      const p = store.refresh();
      store.markExpired();
      d.resolve(DEFAULT);
      await p;
      expect(store.indicator().kind).toBe('expired');
    });

    it('upload during a refresh: the outcome of the upload wins', async () => {
      const d = deferred();
      api.sourcesStatus.mockReturnValue(d.promise);
      api.uploadSources.mockResolvedValue(set('custom'));
      const p = store.refresh();
      await store.upload(upload);
      d.resolve(DEFAULT);
      await p;
      expect(store.indicator().kind).toBe('custom');
    });

    it('example and reset during a refresh: the action wins', async () => {
      const d = deferred();
      api.sourcesStatus.mockReturnValue(d.promise);
      api.useExampleSources.mockResolvedValue(set('example'));
      const p = store.refresh();
      await store.useExample();
      d.resolve(DEFAULT);
      await p;
      expect(store.indicator().kind).toBe('example');

      const d2 = deferred();
      api.sourcesStatus.mockReturnValue(d2.promise);
      api.resetSources.mockResolvedValue(DEFAULT);
      const p2 = store.refresh();
      await store.reset();
      d2.resolve(set('custom'));
      await p2;
      expect(store.indicator().kind).toBe('default');
    });

    it('a refresh started during the action and concluded after it does not win', async () => {
      let finish!: (s: SourcesStatus) => void;
      api.useExampleSources.mockReturnValue(new Promise<SourcesStatus>((r) => (finish = r)));
      const run = store.useExample();
      const d = deferred();
      api.sourcesStatus.mockReturnValue(d.promise);
      const p = store.refresh();
      finish(set('example'));
      await run;
      d.resolve(DEFAULT);
      await p;
      expect(store.indicator().kind).toBe('example');
    });

    it('two close refreshes: the last one counts, even if it arrives first', async () => {
      const a = deferred();
      const b = deferred();
      api.sourcesStatus.mockReturnValueOnce(a.promise).mockReturnValueOnce(b.promise);
      const p1 = store.refresh();
      const p2 = store.refresh();
      b.resolve(set('custom'));
      await p2;
      a.resolve(DEFAULT);
      await p1;
      expect(store.indicator().kind).toBe('custom');
    });

    it('the initial read and openPage keep writing the state', async () => {
      api.sourcesStatus.mockResolvedValue(set('example'));
      await store.refresh();
      expect(store.indicator().kind).toBe('example');
      api.sourcesStatus.mockResolvedValue(set('custom'));
      store.openPage();
      await Promise.resolve();
      await Promise.resolve();
      expect(store.indicator().kind).toBe('custom');
    });
  });
});
