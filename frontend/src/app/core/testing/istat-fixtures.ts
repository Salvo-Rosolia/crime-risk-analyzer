import type { IstatPoi, IstatRow } from '@core/models/models';

/**
 * ISTAT fixtures shared between `ui-helpers.spec.ts` and `detail-panel.component.spec.ts` (#346,
 * after /code-review): before, there were two almost identical copies of the same convenience row.
 * `istatRow` has default values above the O8 threshold (`delitti`/`tasso`/`tasso_italia` all
 * at 100, so the default weight is 1), overridable field by field; `istatPoi` assembles the
 * `cornice` (default "TOT", no links) and the `righe` passed.
 *
 * Specs only: the file lives under `core/testing/`, excluded from `tsconfig.app.json` so it
 * never enters the `ng build` graph (it is in any case reachable from the `tsconfig.spec.json`
 * program only transitively, via the imports from the `*.spec.ts`).
 */
export function istatRow(
  voce: string,
  hazards: string[],
  overrides: Partial<IstatRow> = {},
): IstatRow {
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

export function istatPoi(...righe: IstatRow[]): IstatPoi {
  return { cornice: istatRow('TOT', []), righe };
}
