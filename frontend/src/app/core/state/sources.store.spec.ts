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

  it('senza stato noto l indicatore dice Predefinite', () => {
    expect(store.indicator()).toEqual({ label: 'Predefinite', kind: 'default' });
  });

  it('refresh legge lo stato dal backend', async () => {
    api.sourcesStatus.mockResolvedValue(set('custom'));
    await store.refresh();
    expect(store.indicator()).toEqual({ label: 'Personalizzate', kind: 'custom' });
  });

  it('refresh con backend giu lascia l indicatore sul default, senza errore', async () => {
    api.sourcesStatus.mockRejectedValue(new HttpErrorResponse({ status: 0 }));
    await store.refresh();
    expect(store.indicator().kind).toBe('default');
    expect(store.message()).toBeNull();
  });

  it('scaduto: indicatore Scadute', async () => {
    api.sourcesStatus.mockResolvedValue({ stato: 'scaduto', scade_tra_secondi: null, set: null });
    await store.refresh();
    expect(store.indicator()).toEqual({ label: 'Scadute', kind: 'expired' });
  });

  it('useExample attiva l esempio e segnala il cambio', async () => {
    api.useExampleSources.mockResolvedValue(set('example'));
    expect(await store.useExample()).toBe(true);
    expect(store.indicator()).toEqual({ label: 'Esempio', kind: 'example' });
    expect(store.busy()).toBeNull();
  });

  it('reset torna al default', async () => {
    api.resetSources.mockResolvedValue(DEFAULT);
    expect(await store.reset()).toBe(true);
    expect(store.indicator().kind).toBe('default');
  });

  it('upload valido: stato attivo e avvisi del set visibili', async () => {
    const avviso = problem('data', 'Colonna ignorata');
    api.uploadSources.mockResolvedValue(set('custom', [avviso]));
    expect(await store.upload(upload)).toBe(true);
    expect(store.report()).toBeNull();
    expect(store.activeWarnings()).toEqual([avviso]);
  });

  it('upload rifiutato (422): report con errori e avvisi, nessun cambio', async () => {
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

  it('upload fallito per altro motivo: messaggio del backend', async () => {
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

  it('un esito nuovo cancella il report e il messaggio precedenti', async () => {
    api.uploadSources.mockRejectedValue(new HttpErrorResponse({ status: 500 }));
    await store.upload(upload);
    expect(store.message()).not.toBeNull();
    api.useExampleSources.mockResolvedValue(set('example'));
    await store.useExample();
    expect(store.message()).toBeNull();
  });

  it('busy segna l operazione in corso', async () => {
    let done!: (s: SourcesStatus) => void;
    api.resetSources.mockReturnValue(new Promise<SourcesStatus>((r) => (done = r)));
    const p = store.reset();
    expect(store.busy()).toBe('reset');
    done(DEFAULT);
    await p;
    expect(store.busy()).toBeNull();
  });

  it('open/close della pagina', () => {
    store.openPage();
    expect(store.open()).toBe(true);
    store.closePage();
    expect(store.open()).toBe(false);
  });

  describe('revision (cambio effettivo del set attivo)', () => {
    it('upload riuscito: incrementa sempre (sono file nuovi)', async () => {
      api.uploadSources.mockResolvedValue(set('custom'));
      await store.upload(upload);
      api.uploadSources.mockResolvedValue(set('custom'));
      await store.upload(upload);
      expect(store.revision()).toBe(2);
    });

    it('upload rifiutato: non incrementa', async () => {
      api.uploadSources.mockRejectedValue(new HttpErrorResponse({ status: 500 }));
      await store.upload(upload);
      expect(store.revision()).toBe(0);
    });

    it('esempio da default incrementa, esempio gia attivo no', async () => {
      api.useExampleSources.mockResolvedValue(set('example'));
      await store.useExample();
      expect(store.revision()).toBe(1);
      await store.useExample();
      expect(store.revision()).toBe(1);
    });

    it('reset da fonti attive incrementa, reset gia al default no', async () => {
      api.resetSources.mockResolvedValue(DEFAULT);
      await store.reset();
      expect(store.revision()).toBe(0);
      api.useExampleSources.mockResolvedValue(set('example'));
      await store.useExample();
      await store.reset();
      expect(store.revision()).toBe(2);
    });

    it('reset da scadute incrementa (i risultati a schermo erano sul set scaduto)', async () => {
      store.markExpired();
      api.resetSources.mockResolvedValue(DEFAULT);
      await store.reset();
      expect(store.revision()).toBe(1);
    });
  });

  it('markExpired porta l indicatore su Scadute senza chiamare la rete', () => {
    store.markExpired();
    expect(store.indicator()).toEqual({ label: 'Scadute', kind: 'expired' });
    expect(api.sourcesStatus).not.toHaveBeenCalled();
  });

  it('aprire la pagina rilegge lo stato dal backend', () => {
    store.openPage();
    expect(api.sourcesStatus).toHaveBeenCalledTimes(1);
  });

  describe('refresh in volo non sovrascrive uno stato piu recente', () => {
    const deferred = () => {
      let resolve!: (s: SourcesStatus) => void;
      const promise = new Promise<SourcesStatus>((r) => (resolve = r));
      return { promise, resolve };
    };

    it('markExpired durante una refresh: resta Scadute', async () => {
      const d = deferred();
      api.sourcesStatus.mockReturnValue(d.promise);
      const p = store.refresh();
      store.markExpired();
      d.resolve(DEFAULT);
      await p;
      expect(store.indicator().kind).toBe('expired');
    });

    it('upload durante una refresh: vince l esito dell upload', async () => {
      const d = deferred();
      api.sourcesStatus.mockReturnValue(d.promise);
      api.uploadSources.mockResolvedValue(set('custom'));
      const p = store.refresh();
      await store.upload(upload);
      d.resolve(DEFAULT);
      await p;
      expect(store.indicator().kind).toBe('custom');
    });

    it('esempio e reset durante una refresh: vince l azione', async () => {
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

    it('una refresh partita durante l azione e conclusa dopo non vince', async () => {
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

    it('due refresh ravvicinate: vale l ultima, anche se arriva prima', async () => {
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

    it('la lettura iniziale e openPage continuano a scrivere lo stato', async () => {
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
