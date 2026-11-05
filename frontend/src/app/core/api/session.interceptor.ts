import { HttpInterceptorFn, HttpResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, tap, throwError } from 'rxjs';
import { SourcesStore } from '@core/state/sources.store';
import { isSourcesExpired, isUnknownPoiType } from './backend-errors';
import { SESSION_HEADER, sessionId } from './session-id';

/** The only route that answers 422 `tipo_poi_non_riconosciuto`; the re-read it triggers must not loop on itself. */
const BASELINE_URL = '/analyze/baseline';

/** The routes whose results depend on the session's source set and that do not carry its identity (#473). */
const ANALYSIS_URLS: readonly string[] = ['/analyze', BASELINE_URL];

/** URL towards the backend: relative to the root, but not `//host` (protocol-relative, another host). */
function isBackendUrl(url: string): boolean {
  return url.startsWith('/') && !url.startsWith('//');
}

/**
 * Adds the session token to every request towards the backend: the analysis routes work on the
 * session's source set, and without the header they would use the default even after an
 * upload. Other hosts do not receive it. It also intercepts the 410 `fonti_scadute` of
 * any route and reports it to the sources store, so the indicator does not stay stale, and the
 * 422 `tipo_poi_non_riconosciuto`, so the cached "Tipo POI" list is reloaded (#467). After a successful
 * analysis it re-reads `/sources` (#473): the analysis answers do not carry the identity of the set, so
 * this is where a set the server lost with no 410 (restart, silent expiry) is found out.
 */
export const sessionInterceptor: HttpInterceptorFn = (req, next) => {
  if (!isBackendUrl(req.url)) return next(req);
  const sources = inject(SourcesStore);
  return next(req.clone({ setHeaders: { [SESSION_HEADER]: sessionId() } })).pipe(
    tap((event) => {
      if (event instanceof HttpResponse && ANALYSIS_URLS.includes(req.url)) void sources.refresh();
    }),
    catchError((err: unknown) => {
      if (isSourcesExpired(err)) sources.markExpired();
      else if (req.url === BASELINE_URL && isUnknownPoiType(err)) void sources.markPoiTypesStale();
      return throwError(() => err);
    }),
  );
};
