import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { catchError, firstValueFrom, map, of, throwError } from 'rxjs';
import { AnalyzeResponse, BaselineParams, ScenarioPreset } from '@core/models/models';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);

  analyze(
    zona: string,
    scenarioId: string | null = null,
    domanda: string | null = null,
  ): Promise<AnalyzeResponse> {
    const payload: { zona: string; domanda?: string } = { zona };
    if (domanda && domanda.trim()) payload.domanda = domanda.trim();

    const request$ = this.http.post<AnalyzeResponse>('/analyze', payload).pipe(
      catchError((err) => {
        if (scenarioId) {
          return this.http
            .get<AnalyzeResponse>(`/demo/cache/${scenarioId}.json`)
            .pipe(map((data) => ({ ...data, _fromCache: true as const })));
        }
        return throwError(() => err);
      }),
    );

    return firstValueFrom(request$);
  }

  getScenarios(): Promise<ScenarioPreset[]> {
    return firstValueFrom(
      this.http.get<ScenarioPreset[]>('/scenarios').pipe(catchError(() => of([]))),
    );
  }

  analyzeBaseline(params: BaselineParams): Promise<AnalyzeResponse> {
    return firstValueFrom(this.http.post<AnalyzeResponse>('/analyze/baseline', params));
  }
}
