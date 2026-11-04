import { HttpErrorResponse } from '@angular/common/http';

/** `true` if `err` is an HTTP error with this `status` and `detail.errore` code (the backend's error envelope). */
function hasBackendError(err: unknown, status: number, code: string): boolean {
  if (!(err instanceof HttpErrorResponse) || err.status !== status) return false;
  return (err.error as { detail?: { errore?: string } } | null)?.detail?.errore === code;
}

/** `true` if `err` is the 410 `fonti_scadute`: the sources uploaded by the session are gone. */
export function isSourcesExpired(err: unknown): boolean {
  return hasBackendError(err, 410, 'fonti_scadute');
}

/** `true` if `err` is the 422 `tipo_poi_non_riconosciuto`: the class sent is not in the server's active set. */
export function isUnknownPoiType(err: unknown): boolean {
  return hasBackendError(err, 422, 'tipo_poi_non_riconosciuto');
}
