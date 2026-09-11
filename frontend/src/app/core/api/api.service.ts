import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import {
  AnalyzeResponse,
  BaselineParams,
  PoiNarrativeResponse,
  ZoneNarrativeResponse,
} from '@core/models/models';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);

  /**
   * Fase 1 (`POST /analyze`): accetta il centro del cerchio di ricerca e il raggio in metri.
   * Il backend emette i rischi geospaziali per i POI entro il cerchio.
   */
  analyze(center: { lat: number; lon: number }, radiusM: number): Promise<AnalyzeResponse> {
    return firstValueFrom(
      this.http.post<AnalyzeResponse>('/analyze', { center, radius_m: radiusM }),
    );
  }

  analyzeBaseline(params: BaselineParams): Promise<AnalyzeResponse> {
    const body: { center: { lat: number; lon: number }; radius_m: number; tipo_poi?: string } = {
      center: params.center,
      radius_m: params.radiusM,
    };
    if (params.tipo_poi) body.tipo_poi = params.tipo_poi;
    return firstValueFrom(this.http.post<AnalyzeResponse>('/analyze/baseline', body));
  }

  geocodePlace(query: string): Promise<{ lat: number; lon: number }> {
    return firstValueFrom(
      this.http.get<{ lat: number; lon: number }>('/geocode', { params: { query } }),
    );
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

  /**
   * Narrativa di ZONA in fase 2 (`POST /analyze/narrativa`, #259/#292): la fase 1 di `/analyze`
   * non chiama più l'LLM, quindi `domanda` va qui — mandarla alla fase 1 non avrebbe alcun effetto,
   * il backend la ignorerebbe silenziosamente. `contestoHash` è l'impronta ricevuta dalla fase 1,
   * rimandata verbatim (#242): il backend la confronta, mai per costruire il prompt.
   */
  zoneNarrative(
    citta: string,
    zona: string,
    contestoHash: string,
    domanda: string | null = null,
  ): Promise<ZoneNarrativeResponse> {
    const payload: { citta: string; zona: string; domanda?: string; contesto_hash: string } = {
      citta,
      zona,
      contesto_hash: contestoHash,
    };
    if (domanda && domanda.trim()) payload.domanda = domanda.trim();

    return firstValueFrom(this.http.post<ZoneNarrativeResponse>('/analyze/narrativa', payload));
  }
}
