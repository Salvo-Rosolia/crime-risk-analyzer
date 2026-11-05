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

/**
 * What the results on screen are based on: the server identity of the set plus the expired state
 * (the server keeps `default` as id while expired, but the results still come from the lost set).
 * Two equal values give the same analyses.
 */
function basis(status: SourcesStatus | null, id: string | null): string {
  return `${status?.stato === 'scaduto' ? 'expired' : 'live'}:${id ?? DEFAULT_SET_ID}`;
}

/** Identity of the set served when nothing else is known (also what an expired session gets). */
const DEFAULT_SET_ID = 'default';

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
  /** Identity the server last declared for the active set (#473); `null` until something carries it. */
  private readonly _setId = signal<string | null>(null);
  private readonly _serverChanges = signal(0);
  /** Times the server rejected a POI type the client still offered (#467): part of `setKey`. */
  private readonly _staleTypes = signal(0);
  /** State generation: a read started before an action or a 410 does not override it. */
  private seq = 0;
  private staleInFlight = false;

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
  /**
   * Counter of the changes of the server's set identity that the user did NOT make (#473): backend
   * restarted or session expired with no 410, found out by a re-read of `/sources` or by the id that
   * `/poi-types` carries. The shell observes it to clear the results on screen (the indicator is already
   * corrected here) while keeping the form and the error. The first id ever seen is not a change.
   */
  readonly serverChanges = this._serverChanges.asReadonly();

  /**
   * Key of the active set for the caches that depend on it (the "Tipo POI" list, #463): the identity the
   * SERVER declares (#473: `default`, `example`, `custom-<hex>`), plus the counter that forces one reload
   * after a 422 `tipo_poi_non_riconosciuto` (#467, `markPoiTypesStale`). Until an id is known the server is
   * assumed to serve the default. It is not a reason to reset the analysis (that is `revision` and
   * `serverChanges`).
   */
  readonly setKey = computed(() => `${this._setId() ?? DEFAULT_SET_ID}:${this._staleTypes()}`);

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
    // The server keeps `default` as id while expired; the 410 itself is already known to the shell, so it is not a change to signal.
    this._setId.set(DEFAULT_SET_ID);
    this._status.set({
      stato: 'scaduto',
      scade_tra_secondi: null,
      set: null,
      source_set_id: DEFAULT_SET_ID,
    });
  }

  /**
   * A 422 `tipo_poi_non_riconosciuto`: the server no longer knows a class the client offered (backend
   * restarted or session expired with no 410, #467). The status is re-read so the indicator follows the
   * real set; if that does not change the key by itself the stale counter does, so the cached "Tipo POI"
   * list is reloaded exactly once. Calls made while a reload is in flight are ignored.
   */
  async markPoiTypesStale(): Promise<void> {
    if (this.staleInFlight) return;
    this.staleInFlight = true;
    try {
      const before = this.setKey();
      await this.refresh();
      if (this.setKey() === before) this._staleTypes.update((n) => n + 1);
    } finally {
      this.staleInFlight = false;
    }
  }

  closePage(): void {
    this._open.set(false);
  }

  /** Re-reads the state from the backend. If it does not answer the indicator stays as it was: it is not an error. */
  async refresh(): Promise<void> {
    const mine = ++this.seq;
    try {
      const status = await this.api.sourcesStatus();
      if (mine === this.seq) this.applyRead(status);
    } catch {
      // Backend unreachable: no message, the analysis will show its own error.
    }
  }

  /**
   * The id carried by a `/poi-types` answer (#473). Equal to the known one: nothing. Different: the
   * server is serving another set than the one the indicator and the results refer to, so the indicator
   * goes back to the default at once (the real status is re-read right after) and the change is signaled.
   */
  noteSetId(id: string): void {
    const known = this._setId();
    this._setId.set(id);
    if (known === null || known === id) return;
    this.seq++;
    this._status.set(null);
    this._serverChanges.update((n) => n + 1);
    void this.refresh();
  }

  /** A status read (not caused by an action of the user): applies it and signals an identity change. */
  private applyRead(status: SourcesStatus): void {
    const known = this._setId();
    this._status.set(status);
    this._setId.set(status.source_set_id);
    if (known !== null && known !== status.source_set_id) {
      this._serverChanges.update((n) => n + 1);
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
    const before = basis(this._status(), this._setId());
    this._busy.set(busy);
    this._report.set(null);
    this._message.set(null);
    try {
      const status = await call();
      // Reads started during the action, and closed after it, must not override it either.
      this.seq++;
      this._status.set(status);
      this._setId.set(status.source_set_id);
      // A successful upload brings new files even if the identity coincides with the previous one.
      if (alwaysChanges || basis(status, status.source_set_id) !== before) {
        this._revision.update((n) => n + 1);
      }
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
