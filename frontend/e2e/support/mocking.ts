import type { Page } from '@playwright/test';
import cities from '../fixtures/cities.json';
import type { AnalyzeResponse } from '../../src/app/core/models/models';

/**
 * Helper di mocking a livello browser (`page.route`) per gli E2E di parità (#69): nessuna
 * chiamata reale al backend FastAPI, tutte le risposte vengono dai fixture JSON versionati in
 * `e2e/fixtures/`. Registra sempre `/cities` (di default dal fixture condiviso, sovrascrivibile);
 * `/analyze` e `/analyze/baseline` solo se lo scenario li richiede.
 */
export interface MockOpts {
  cities?: unknown;
  analyze?: unknown;
  baseline?: unknown;
  /** Status HTTP della risposta `/analyze` (default 200; usare 4xx/5xx per lo stato ERROR). */
  analyzeStatus?: number;
  /** Risposta di `POST /analyze/poi` (#197): narrativa del singolo POI selezionato. */
  poiNarrative?: unknown;
  /**
   * Status HTTP della risposta `/analyze/poi` (default 200; 404 = POI fuori dal contesto,
   * 409 = contesto disallineato rispetto a quello mostrato, #242).
   */
  poiNarrativeStatus?: number;
  /**
   * Risposta esplicita di `POST /analyze/narrativa` (#259 fase 2, #292): narrativa di ZONA
   * generata in background dopo la fase 1 di `/analyze`. Se omessa ma `analyze` è fornito, si
   * deriva da lì (stesso narrativa/narrativa_fonti/fallback/llm_used): i fixture "happy" esistenti
   * restano validi senza doverli duplicare, come se il testo fosse "già arrivato" alla fase 2.
   */
  zoneNarrative?: unknown;
  /** Status HTTP della risposta `/analyze/narrativa` (default 200; 409 = contesto disallineato). */
  zoneNarrativeStatus?: number;
}

export async function mockApi(page: Page, opts: MockOpts = {}): Promise<void> {
  await page.route('**/cities', (route) => route.fulfill({ json: opts.cities ?? cities }));

  if (opts.analyze !== undefined || opts.analyzeStatus !== undefined) {
    await page.route('**/analyze', (route) =>
      route.fulfill({ status: opts.analyzeStatus ?? 200, json: opts.analyze ?? {} }),
    );
  }

  if (opts.baseline !== undefined) {
    await page.route('**/analyze/baseline', (route) => route.fulfill({ json: opts.baseline }));
  }

  // `**/analyze` sopra non intercetta `/analyze/poi` (il glob àncora il suffisso), quindi la rotta
  // per-POI va registrata a parte, come già per `/analyze/baseline`.
  if (opts.poiNarrative !== undefined || opts.poiNarrativeStatus !== undefined) {
    await page.route('**/analyze/poi', (route) =>
      route.fulfill({
        status: opts.poiNarrativeStatus ?? 200,
        json: opts.poiNarrative ?? {},
      }),
    );
  }

  // `/analyze/narrativa` (#259 fase 2, #292): stesso trattamento di `/analyze/poi` sopra, con
  // l'ECHO di default descritto sull'opzione `zoneNarrative`.
  const analyzeObj = opts.analyze as Partial<AnalyzeResponse> | undefined;
  if (
    opts.zoneNarrative !== undefined ||
    opts.zoneNarrativeStatus !== undefined ||
    analyzeObj !== undefined
  ) {
    await page.route('**/analyze/narrativa', (route) =>
      route.fulfill({
        status: opts.zoneNarrativeStatus ?? 200,
        json:
          opts.zoneNarrative ??
          (analyzeObj
            ? {
                narrativa: analyzeObj.narrativa ?? '',
                narrativa_fonti: analyzeObj.narrativa_fonti ?? {
                  overview: '',
                  ontologia: '',
                  contesto: '',
                  speculativo: '',
                },
                tokens_input: analyzeObj.tokens_input ?? 0,
                tokens_output: analyzeObj.tokens_output ?? 0,
                latenza_ms: analyzeObj.latenza_ms ?? 0,
                repro: analyzeObj.repro ?? { temperature: 0, seed: 0, prompt_hash: '' },
                fallback: analyzeObj.fallback ?? false,
                llm_used: analyzeObj.llm_used ?? '',
              }
            : {}),
      }),
    );
  }
}
