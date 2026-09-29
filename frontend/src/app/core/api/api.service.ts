import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import {
  AnalyzeResponse,
  BaselineParams,
  PoiNarrativeResponse,
  SearchArea,
  ZoneNarrativeResponse,
} from '@core/models/models';

/**
 * Serializza l'area nel body atteso dal backend. Un solo posto in cui la forma viene decisa:
 * `/analyze` e `/analyze/baseline` condividono lo stesso contratto di area, e due copie
 * divergerebbero al primo che ne tocca una.
 */
function areaBody(area: SearchArea): Record<string, unknown> {
  return area.kind === 'circle'
    ? { center: area.center, radius_m: area.radiusM }
    : { query: area.query };
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);

  /**
   * Fase 1 (`POST /analyze`): manda l'AREA nella modalita' scelta dall'utente — il cerchio
   * disegnato (centro+raggio) oppure una ricerca testuale libera. Il backend accetta
   * esattamente una delle due forme e risponde 422 se ne arrivano zero o due: qui non si
   * compone mai un body ambiguo perche' `SearchArea` non lo permette.
   */
  analyze(area: SearchArea): Promise<AnalyzeResponse> {
    return firstValueFrom(this.http.post<AnalyzeResponse>('/analyze', areaBody(area)));
  }

  analyzeBaseline(params: BaselineParams): Promise<AnalyzeResponse> {
    const body: Record<string, unknown> = { ...areaBody(params.area) };
    if (params.tipo_poi) body['tipo_poi'] = params.tipo_poi;
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
