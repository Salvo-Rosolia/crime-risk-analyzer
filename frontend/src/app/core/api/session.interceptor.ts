import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';
import { SourcesStore } from '@core/state/sources.store';
import { SESSION_HEADER, sessionId } from './session-id';

/** URL verso il backend: relativo alla radice, ma non `//host` (protocol-relative, altro host). */
function isBackendUrl(url: string): boolean {
  return url.startsWith('/') && !url.startsWith('//');
}

function isSourcesExpired(err: unknown): boolean {
  if (!(err instanceof HttpErrorResponse) || err.status !== 410) return false;
  return (err.error as { detail?: { errore?: string } } | null)?.detail?.errore === 'fonti_scadute';
}

/**
 * Aggiunge il token di sessione a ogni richiesta verso il backend: le rotte di analisi lavorano sul
 * set di fonti della sessione, e senza intestazione userebbero il default anche dopo un
 * caricamento. Gli altri host non lo ricevono. Inoltre intercetta il 410 `fonti_scadute` di
 * qualunque rotta e lo segnala allo store delle fonti, così l'indicatore non resta stantio.
 */
export const sessionInterceptor: HttpInterceptorFn = (req, next) => {
  if (!isBackendUrl(req.url)) return next(req);
  const sources = inject(SourcesStore);
  return next(req.clone({ setHeaders: { [SESSION_HEADER]: sessionId() } })).pipe(
    catchError((err: unknown) => {
      if (isSourcesExpired(err)) sources.markExpired();
      return throwError(() => err);
    }),
  );
};
