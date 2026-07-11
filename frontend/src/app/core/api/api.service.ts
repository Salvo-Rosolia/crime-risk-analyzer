import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { AnalyzeResponse, BaselineParams } from '@core/models/models';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);

  analyze(
    citta: string,
    zona: string,
    domanda: string | null = null,
  ): Promise<AnalyzeResponse> {
    const payload: { citta: string; zona: string; domanda?: string } = { citta, zona };
    if (domanda && domanda.trim()) payload.domanda = domanda.trim();

    return firstValueFrom(this.http.post<AnalyzeResponse>('/analyze', payload));
  }

  analyzeBaseline(params: BaselineParams): Promise<AnalyzeResponse> {
    return firstValueFrom(this.http.post<AnalyzeResponse>('/analyze/baseline', params));
  }
}
