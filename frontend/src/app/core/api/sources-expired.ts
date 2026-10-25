import { HttpErrorResponse } from '@angular/common/http';

/** `true` se `err` è il 410 `fonti_scadute`: le fonti caricate dalla sessione non ci sono più. */
export function isSourcesExpired(err: unknown): boolean {
  if (!(err instanceof HttpErrorResponse) || err.status !== 410) return false;
  return (err.error as { detail?: { errore?: string } } | null)?.detail?.errore === 'fonti_scadute';
}
