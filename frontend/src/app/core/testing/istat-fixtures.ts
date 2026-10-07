import type { IstatPoi, IstatRiga } from '@core/models/models';

/**
 * Fixture ISTAT condivise fra `ui-helpers.spec.ts` e `detail-panel.component.spec.ts` (#346,
 * dopo /code-review): prima esistevano due copie quasi identiche della stessa riga di comodo.
 * `istatRiga` ha valori di default sopra la soglia O8 (`delitti`/`tasso`/`tasso_italia` tutti
 * a 100, così il peso di default è 1), sovrascrivibili campo per campo; `istatPoi` assembla la
 * `cornice` (default «TOT», nessun collegamento) e le `righe` passate.
 *
 * Solo per gli spec: il file vive sotto `core/testing/`, escluso da `tsconfig.app.json` così non
 * entra mai nel grafo di `ng build` (è comunque raggiungibile dal programma di `tsconfig.spec.json`
 * solo transitivamente, via gli import dagli `*.spec.ts`).
 */
export function istatRiga(
  voce: string,
  hazards: string[],
  overrides: Partial<IstatRiga> = {},
): IstatRiga {
  return {
    luogo_codice: '058091',
    luogo_nome: 'Comune di Roma',
    luogo_breve: 'Roma',
    luogo_tipo: 'comune',
    voce,
    voce_label: voce,
    anno: 2024,
    anno_confronto: 2014,
    delitti: 100,
    delitti_confronto: 100,
    tasso: 100,
    tasso_sotto_soglia: false,
    tasso_italia: 100,
    tasso_italia_sotto_soglia: false,
    variazione_pct: 0,
    motivo_senza_variazione: null,
    rottura_2016: false,
    collegamenti: hazards.map((h) => ({
      hazard: h,
      hazard_label_it: h,
      corrispondenza: 'piu_larga' as const,
    })),
    ...overrides,
  };
}

export function istatPoi(...righe: IstatRiga[]): IstatPoi {
  return { cornice: istatRiga('TOT', []), righe };
}
