import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';
import { SourcesStore } from '@core/state/sources.store';
import { isSourcesExpired, isUnknownPoiType } from './backend-errors';
import { SESSION_HEADER, sessionId } from './session-id';

/** The only route that answers 422 `tipo_poi_non_riconosciuto`; the re-read it triggers must not loop on itself. */
const BASELINE_URL = '/analyze/baseline';

/** URL towards the backend: relative to the root, but not `//host` (protocol-relative, another host). */
function isBackendUrl(url: string): boolean {
  return url.startsWith('/') && !url.startsWith('//');
}

/**
 * Adds the session token to every request towards the backend: the analysis routes work on the
 * session's source set, and without the header they would use the default even after an
 * upload. Other hosts do not receive it. It also intercepts the 410 `fonti_scadute` of
 * any route and reports it to the sources store, so the indicator does not stay stale, and the
 * 422 `tipo_poi_non_riconosciuto`, so the cached "Tipo POI" list is reloaded (#467).
 */
export const sessionInterceptor: HttpInterceptorFn = (req, next) => {
  if (!isBackendUrl(req.url)) return next(req);
  const sources = inject(SourcesStore);
  return next(req.clone({ setHeaders: { [SESSION_HEADER]: sessionId() } })).pipe(
    catchError((err: unknown) => {
      if (isSourcesExpired(err)) sources.markExpired();
      else if (req.url === BASELINE_URL && isUnknownPoiType(err)) void sources.markPoiTypesStale();
      return throwError(() => err);
    }),
  );
};
