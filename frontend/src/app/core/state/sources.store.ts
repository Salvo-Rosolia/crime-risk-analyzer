import { computed, inject, Injectable, signal } from '@angular/core';
import { ApiService } from '@core/api/api.service';
import type { SourceProblem, SourcesStatus, SourceUpload } from '@core/models/models';
import { errorMessage } from './state.store';

/** Outcome of the check of a rejected upload: all the problems, per file. */
export interface SourcesReport {
  errors: SourceProblem[];
  warnings: SourceProblem[];
}

export type IndicatorKind = 'default' | 'example' | 'custom' | 'expired';

/** What the always-visible indicator shows: the template prepends "Fonti: ". */
export interface SourcesIndicator {
  label: string;
  kind: IndicatorKind;
}

export type SourcesBusy = 'upload' | 'example' | 'reset';

/** Fingerprint of the active set: two states with the same fingerprint give the same analyses. */
function signature(status: SourcesStatus | null): string {
  if (status?.stato === 'attivo' && status.set) {
    const { kind, versione_dati, classi, selettori_osm } = status.set;
    return `${kind}:${versione_dati}:${classi}:${selettori_osm}`;
  }
  return status?.stato === 'scaduto' ? 'scaduto' : 'default';
}

/** Body of a 422 `fonti_non_valide`, if `err` is one. */
function reportFrom(err: unknown): SourcesReport | null {
  const res = (err as { status?: number; error?: { detail?: unknown } } | null) ?? {};
  const detail = res.error?.detail as
    { errore?: string; errors?: SourceProblem[]; warnings?: SourceProblem[] } | undefined;
  if (res.status !== 422 || detail?.errore !== 'fonti_non_valide') return null;
  return { errors: detail.errors ?? [], warnings: detail.warnings ?? [] };
}

/**
 * State of the session's sources (#419), separate from the analysis FSM: uploading or changing
 * sources is not a state of the map, and the Fonti page opens above any screen. The
 * actions return `true` if the active set changed, so the shell can clear the
 * analysis results, computed on the previous set.
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
  /** State generation: a read started before an action or a 410 does not override it. */
  private seq = 0;

  readonly status = this._status.asReadonly();
  /** Problems of the last rejected upload; `null` after any different outcome. */
  readonly report = this._report.asReadonly();
  /** Non-validation error (network, upload too large, system busy…). */
  readonly message = this._message.asReadonly();
  readonly busy = this._busy.asReadonly();
  readonly open = this._open.asReadonly();
  /**
   * Counter of the EFFECTIVE changes of the active set (successful upload, example or default that
   * really change the set). It lives in the store, not in the dialog: whoever closes the page while
   * an operation is in flight does not lose the notification. The shell observes it to clear the analysis.
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

  /** Non-blocking warnings of the active set, emerged at its loading. */
  readonly activeWarnings = computed(() => this._status()?.set?.avvisi ?? []);

  /** Opens the page and re-reads the state: the sources may have expired in the meantime. */
  openPage(): void {
    this._open.set(true);
    void this.refresh();
  }

  /** A 410 `fonti_scadute` from the analysis routes: the indicator reflects it with no further network. */
  markExpired(): void {
    this.seq++;
    this._status.set({ stato: 'scaduto', scade_tra_secondi: null, set: null });
  }

  closePage(): void {
    this._open.set(false);
  }

  /** Re-reads the state from the backend. If it does not answer the indicator stays as it was: it is not an error. */
  async refresh(): Promise<void> {
    const mine = ++this.seq;
    try {
      const status = await this.api.sourcesStatus();
      if (mine === this.seq) this._status.set(status);
    } catch {
      // Backend unreachable: no message, the analysis will show its own error.
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
      // Reads started during the action, and closed after it, must not override it either.
      this.seq++;
      this._status.set(status);
      // A successful upload brings new files even if the fingerprint coincides with the previous one.
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
