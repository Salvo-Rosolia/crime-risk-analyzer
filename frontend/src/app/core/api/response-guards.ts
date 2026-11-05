import { AnalyzeResponse, PoiType } from '@core/models/models';

/**
 * Minimal runtime checks of backend responses (#464): `HttpClient.get<T>()` is only a cast, so a
 * renamed or missing key (as in #418) would reach the UI as `undefined`. These guards check only
 * the fields the UI cannot work without, not the full schema. A failed check makes the caller throw
 * `UnexpectedResponseError`, i.e. a failed load handled by the existing error path.
 */

/** User-facing message (Italian: shown in the UI by `errorMessage`). */
export class UnexpectedResponseError extends Error {
  constructor() {
    super('Risposta del server in un formato inatteso.');
    this.name = 'UnexpectedResponseError';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isPoiType(value: unknown): value is PoiType {
  return (
    isRecord(value) &&
    typeof value['ontology_class'] === 'string' &&
    typeof value['label_it'] === 'string'
  );
}

function isPoi(value: unknown): boolean {
  return (
    isRecord(value) &&
    typeof value['id'] === 'string' &&
    typeof value['name'] === 'string' &&
    typeof value['ontology_class'] === 'string' &&
    typeof value['lat'] === 'number' &&
    typeof value['lon'] === 'number'
  );
}

export function isPoiTypeList(value: unknown): value is PoiType[] {
  return Array.isArray(value) && value.every(isPoiType);
}

export function isAnalyzeResponse(value: unknown): value is AnalyzeResponse {
  return (
    isRecord(value) &&
    typeof value['citta'] === 'string' &&
    typeof value['zona_normalizzata'] === 'string' &&
    Array.isArray(value['poi']) &&
    value['poi'].every(isPoi) &&
    Array.isArray(value['risk_models']) &&
    isRecord(value['confidence_summary'])
  );
}

/** Returns `value` typed as `T` if `guard` accepts it, otherwise throws `UnexpectedResponseError`. */
export function expectShape<T>(value: unknown, guard: (v: unknown) => v is T): T {
  if (!guard(value)) throw new UnexpectedResponseError();
  return value;
}
