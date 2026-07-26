import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { AnalyzeResponse, BaselineParams, PoiNarrativeResponse } from '@core/models/models';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);

  /** Elenco delle città suggerite per l'autocomplete (`GET /cities`). */
  cities(): Promise<string[]> {
    return firstValueFrom(this.http.get<string[]>('/cities'));
  }

  analyze(citta: string, zona: string, domanda: string | null = null): Promise<AnalyzeResponse> {
    const payload: { citta: string; zona: string; domanda?: string } = { citta, zona };
    if (domanda && domanda.trim()) payload.domanda = domanda.trim();

    return firstValueFrom(this.http.post<AnalyzeResponse>('/analyze', payload));
  }

  analyzeBaseline(params: BaselineParams): Promise<AnalyzeResponse> {
    return firstValueFrom(this.http.post<AnalyzeResponse>('/analyze/baseline', params));
  }

  /**
   * Narrativa del singolo POI selezionato (`POST /analyze/poi`, #197). Il client manda solo l'id e
   * l'impronta del contesto che sta mostrando (#242): classe, rischi e percorso ontologico sono
   * ri-derivati dal server, e l'impronta è confrontata dal backend, mai usata per il prompt.
   */
  poiNarrative(
    citta: string,
    zona: string,
    poiId: string,
    contestoHash: string,
  ): Promise<PoiNarrativeResponse> {
    return firstValueFrom(
      this.http.post<PoiNarrativeResponse>('/analyze/poi', {
        citta,
        zona,
        poi_id: poiId,
        contesto_hash: contestoHash,
      }),
    );
  }
}
