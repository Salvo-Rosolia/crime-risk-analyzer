import { computed, inject, Injectable, signal } from '@angular/core';
import { ApiService } from '@core/api/api.service';
import type { SourceProblem, SourcesStatus, SourceUpload } from '@core/models/models';
import { errorMessage } from './state.store';

/** Esito del controllo di un caricamento rifiutato: tutti i problemi, per file. */
export interface SourcesReport {
  errors: SourceProblem[];
  warnings: SourceProblem[];
}

export type IndicatorKind = 'default' | 'example' | 'custom' | 'expired';

/** Cosa mostra l'indicatore sempre visibile: il template antepone "Fonti: ". */
export interface SourcesIndicator {
  label: string;
  kind: IndicatorKind;
}

export type SourcesBusy = 'upload' | 'example' | 'reset';

/** Impronta del set attivo: due stati con la stessa impronta danno le stesse analisi. */
function signature(status: SourcesStatus | null): string {
  if (status?.stato === 'attivo' && status.set) {
    const { kind, versione_dati, classi, selettori_osm } = status.set;
    return `${kind}:${versione_dati}:${classi}:${selettori_osm}`;
  }
  return status?.stato === 'scaduto' ? 'scaduto' : 'default';
}

/** Corpo di un 422 `fonti_non_valide`, se `err` lo è. */
function reportFrom(err: unknown): SourcesReport | null {
  const res = (err as { status?: number; error?: { detail?: unknown } } | null) ?? {};
  const detail = res.error?.detail as
    { errore?: string; errors?: SourceProblem[]; warnings?: SourceProblem[] } | undefined;
  if (res.status !== 422 || detail?.errore !== 'fonti_non_valide') return null;
  return { errors: detail.errors ?? [], warnings: detail.warnings ?? [] };
}

/**
 * Stato delle fonti della sessione (#419), separato dalla FSM dell'analisi: caricare o cambiare
 * fonti non è uno stato della mappa, e la pagina Fonti si apre sopra qualunque schermata. Le
 * azioni ritornano `true` se il set attivo è cambiato, così lo shell può azzerare i risultati
 * dell'analisi, calcolati sul set precedente.
 */
@Injectable({ providedIn: 'root' })
export class SourcesStore {
  private readonly api = inject(ApiService);
  private readonly _status = signal<SourcesStatus | null>(null);
  private readonly _report = signal<SourcesReport | null>(null);
  private readonly _message = signal<string | null>(null);
  private readonly _busy = signal<SourcesBusy | null>(null);
  private readonly _open = signal(false);
  private readonly _revision = signal(0);
  /** Generazione dello stato: una lettura partita prima di un'azione o di un 410 non lo scavalca. */
  private seq = 0;

  readonly status = this._status.asReadonly();
  /** Problemi dell'ultimo caricamento rifiutato; `null` dopo ogni esito diverso. */
  readonly report = this._report.asReadonly();
  /** Errore non di validazione (rete, upload troppo grande, sistema occupato…). */
  readonly message = this._message.asReadonly();
  readonly busy = this._busy.asReadonly();
  readonly open = this._open.asReadonly();
  /**
   * Contatore dei cambi EFFETTIVI del set attivo (caricamento riuscito, esempio o default che
   * cambiano davvero il set). Vive nello store, non nel dialog: chi chiude la pagina mentre
   * un'operazione è in volo non perde la notifica. Lo shell lo osserva per azzerare l'analisi.
   */
  readonly revision = this._revision.asReadonly();

  readonly indicator = computed<SourcesIndicator>(() => {
    const status = this._status();
    if (status?.stato === 'scaduto') return { label: 'Scadute', kind: 'expired' };
    if (status?.stato === 'attivo' && status.set) {
      return status.set.kind === 'example'
        ? { label: 'Esempio', kind: 'example' }
        : { label: 'Personalizzate', kind: 'custom' };
    }
    return { label: 'Predefinite', kind: 'default' };
  });

  /** Avvisi (non bloccanti) del set attivo, emersi al suo caricamento. */
  readonly activeWarnings = computed(() => this._status()?.set?.avvisi ?? []);

  /** Apre la pagina e rilegge lo stato: le fonti possono essere scadute nel frattempo. */
  openPage(): void {
    this._open.set(true);
    void this.refresh();
  }

  /** Un 410 `fonti_scadute` dalle rotte di analisi: l'indicatore lo riflette senza altra rete. */
  markExpired(): void {
    this.seq++;
    this._status.set({ stato: 'scaduto', scade_tra_secondi: null, set: null });
  }

  closePage(): void {
    this._open.set(false);
  }

  /** Rilegge lo stato dal backend. Se non risponde l'indicatore resta com'era: non è un errore. */
  async refresh(): Promise<void> {
    const mine = ++this.seq;
    try {
      const status = await this.api.sourcesStatus();
      if (mine === this.seq) this._status.set(status);
    } catch {
      // Backend irraggiungibile: nessun messaggio, l'analisi mostrerà il suo errore.
    }
  }

  upload(files: SourceUpload): Promise<boolean> {
    return this.run(
      'upload',
      () => this.api.uploadSources(files),
      'Caricamento non riuscito.',
      true,
    );
  }

  useExample(): Promise<boolean> {
    return this.run('example', () => this.api.useExampleSources(), 'Esempio non disponibile.');
  }

  reset(): Promise<boolean> {
    return this.run('reset', () => this.api.resetSources(), 'Ritorno al default non riuscito.');
  }

  private async run(
    busy: SourcesBusy,
    call: () => Promise<SourcesStatus>,
    fallback: string,
    alwaysChanges = false,
  ): Promise<boolean> {
    this.seq++;
    const before = signature(this._status());
    this._busy.set(busy);
    this._report.set(null);
    this._message.set(null);
    try {
      const status = await call();
      // Anche le letture partite durante l'azione, e chiuse dopo, non devono scavalcarla.
      this.seq++;
      this._status.set(status);
      // Un caricamento riuscito porta file nuovi anche se l'impronta coincide con quella di prima.
      if (alwaysChanges || signature(status) !== before) this._revision.update((n) => n + 1);
      return true;
    } catch (err) {
      const report = reportFrom(err);
      if (report) this._report.set(report);
      else this._message.set(errorMessage(err, fallback));
      return false;
    } finally {
      this._busy.set(null);
    }
  }
}
