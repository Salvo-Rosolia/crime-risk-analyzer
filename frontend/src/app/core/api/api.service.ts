import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { expectShape, isAnalyzeResponse, isPoiTypeList, isSourcesStatus } from '@core/api/response-guards';
import {
  AnalyzeResponse,
  BaselineParams,
  PoiNarrativeResponse,
  PoiType,
  SearchArea,
  SourceTemplate,
  SourcesStatus,
  SourceUpload,
  ZoneNarrativeResponse,
} from '@core/models/models';

/**
 * Serializes the area into the body expected by the backend (whose field names are Italian: the
 * API contract). The one place where the shape is decided: `/analyze` and `/analyze/baseline`
 * share the same area contract, and two copies would diverge as soon as one is touched.
 */
function areaBody(area: SearchArea): Record<string, unknown> {
  return area.kind === 'circle'
    ? { center: area.center, radius_m: area.radiusM }
    : { citta: area.city, zona: area.zone };
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);

  /** Memoized Promises of `cities()` and `poiTypes()` (see `memoized`). */
  private readonly memos = new Map<string, { key: string; promise: Promise<unknown> }>();

  /**
   * One Promise per `name`, reused while `key` stays the same; a different key refetches. On error the
   * memo is cleared (so a later call can retry) unless a newer key superseded it: a superseded
   * request failing must not wipe the memo of the newer one.
   */
  private memoized<T>(name: string, key: string, load: () => Promise<T>): Promise<T> {
    const current = this.memos.get(name);
    if (current?.key === key) return current.promise as Promise<T>;
    const memo = {
      key,
      promise: load().catch((err) => {
        if (this.memos.get(name) === memo) this.memos.delete(name);
        throw err;
      }),
    };
    this.memos.set(name, memo);
    return memo.promise;
  }

  /**
   * List of cities suggested for the search panels' datalist (`GET /cities`): a SINGLE HTTP call
   * per session, later calls (from any panel) reuse the same Promise — both `InputPanelComponent`
   * and `BasePanelComponent` call it in their own `ngOnInit`, and a Full↔Base round trip or an
   * INPUT→ERROR remount would otherwise repeat the same GET for a list that does not change. If the
   * request fails the memoization is cleared, so a later remount can retry.
   */
  cities(): Promise<string[]> {
    return this.memoized('cities', '', () => firstValueFrom(this.http.get<string[]>('/cities')));
  }

  /**
   * POI types selectable in the optional filter of the base-system panel (`GET /poi-types`, #143):
   * already sorted by `label_it` by the backend, which answers with the classes of the session's
   * active source set (#463). Memoized like `cities()` (cleared on error so a later call can
   * retry), but only for the given `setKey` (required: omitting it would never invalidate the
   * memo, #463): a different key means the set may have changed (or the client found its list stale,
   * #467) and refetches.
   */
  poiTypes(setKey: string): Promise<PoiType[]> {
    return this.memoized('poiTypes', setKey, () =>
      firstValueFrom(this.http.get<unknown>('/poi-types')).then((body) =>
        expectShape(body, isPoiTypeList),
      ),
    );
  }

  /**
   * Phase 1 (`POST /analyze`): sends the AREA in the mode chosen by the user — the drawn circle
   * (center+radius) or the typed city and zone. The backend accepts exactly one of the two
   * forms and answers 422 if zero or two arrive: an ambiguous body is never composed here
   * because `SearchArea` does not allow it.
   */
  analyze(area: SearchArea): Promise<AnalyzeResponse> {
    return firstValueFrom(this.http.post<unknown>('/analyze', areaBody(area))).then((body) =>
      expectShape(body, isAnalyzeResponse),
    );
  }

  analyzeBaseline(params: BaselineParams): Promise<AnalyzeResponse> {
    const body: Record<string, unknown> = { ...areaBody(params.area) };
    if (params.poiType) body['tipo_poi'] = params.poiType;
    return firstValueFrom(this.http.post<unknown>('/analyze/baseline', body)).then((res) =>
      expectShape(res, isAnalyzeResponse),
    );
  }

  geocodePlace(query: string): Promise<{ lat: number; lon: number }> {
    return firstValueFrom(
      this.http.get<{ lat: number; lon: number }>('/geocode', { params: { query } }),
    );
  }

  /**
   * Narrative of the single selected POI (`POST /analyze/poi`, #197). The client sends only the id
   * and the fingerprint of the context it is showing (#242): class, risks and ontology path are
   * re-derived by the server, and the fingerprint is compared by the backend, never used for the
   * prompt.
   */
  poiNarrative(
    city: string,
    zone: string,
    poiId: string,
    contextHash: string,
  ): Promise<PoiNarrativeResponse> {
    return firstValueFrom(
      this.http.post<PoiNarrativeResponse>('/analyze/poi', {
        citta: city,
        zona: zone,
        poi_id: poiId,
        contesto_hash: contextHash,
      }),
    );
  }

  /**
   * ZONE narrative in phase 2 (`POST /analyze/narrativa`, #259/#292): phase 1 of `/analyze`
   * no longer calls the LLM, so `question` goes here — sending it to phase 1 would have no
   * effect, the backend would silently ignore it. `contextHash` is the fingerprint received from
   * phase 1, sent back verbatim (#242): the backend compares it, never uses it to build the prompt.
   */
  zoneNarrative(
    city: string,
    zone: string,
    contextHash: string,
    question: string | null = null,
  ): Promise<ZoneNarrativeResponse> {
    const payload: { citta: string; zona: string; domanda?: string; contesto_hash: string } = {
      citta: city,
      zona: zone,
      contesto_hash: contextHash,
    };
    if (question && question.trim()) payload.domanda = question.trim();

    return firstValueFrom(this.http.post<ZoneNarrativeResponse>('/analyze/narrativa', payload));
  }

  /** State of the session's sources (`GET /sources`): default, active or expired. */
  sourcesStatus(): Promise<SourcesStatus> {
    return firstValueFrom(this.http.get<unknown>('/sources')).then((body) =>
      expectShape(body, isSourcesStatus),
    );
  }

  /**
   * Uploads the files and, if the check accepts them, activates the set for the session (`POST
   * /sources`, multipart). With errors the backend answers 422 with the full report and does not
   * touch the already active set. Empty vocabulary fields are not sent: the TERMINUS ones apply.
   */
  uploadSources(upload: SourceUpload): Promise<SourcesStatus> {
    const body = new FormData();
    body.append('ontology', upload.ontology);
    body.append('osm_table', upload.osm_table);
    body.append('data', upload.data);
    body.append('hazard_table', upload.hazard_table);
    if (upload.boundaries) body.append('boundaries', upload.boundaries);
    const v = upload.vocabulary;
    for (const key of ['namespace', 'hazard', 'critical_event', 'performer'] as const) {
      const value = v?.[key]?.trim();
      if (value) body.append(key, value);
    }
    for (const value of v?.vulnerability ?? []) {
      if (value.trim()) body.append('vulnerability', value.trim());
    }
    return firstValueFrom(this.http.post<unknown>('/sources', body)).then((res) =>
      expectShape(res, isSourcesStatus),
    );
  }

  /** Activates the example set without uploading files (`POST /sources/example`). */
  useExampleSources(): Promise<SourcesStatus> {
    return firstValueFrom(this.http.post<unknown>('/sources/example', null)).then((res) =>
      expectShape(res, isSourcesStatus),
    );
  }

  /** Goes back to the default sources (`DELETE /sources`, idempotent). */
  resetSources(): Promise<SourcesStatus> {
    return firstValueFrom(this.http.delete<unknown>('/sources')).then((res) =>
      expectShape(res, isSourcesStatus),
    );
  }

  /** URL of the downloadable CSV template: a `download` link is enough, the backend sends the attachment. */
  templateUrl(name: SourceTemplate): string {
    return `/sources/templates/${name}`;
  }
}
