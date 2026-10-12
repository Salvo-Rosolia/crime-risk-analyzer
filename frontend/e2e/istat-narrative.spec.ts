import { expect, test } from '@playwright/test';
import { mockApi } from './support/mocking';
import { S } from './support/selectors';
import { drawSearchCircle } from './support/map';
import analyzeFixture from './fixtures/analyze.happy.json';
import type {
  AnalyzeResponse,
  IstatPoi,
  ZoneNarrativeResponse,
} from '../src/app/core/models/models';

/**
 * Indicatore ISTAT in linea nella prosa ONTOLOGIA (#365): il testo del modello cita il rischio a
 * parole, i numeri li calcola l'app dai dati del POI e li mostra subito dopo la prima menzione.
 */
const riga = {
  luogo_codice: '058091',
  luogo_nome: 'Comune di Roma',
  luogo_breve: 'Roma',
  luogo_tipo: 'comune' as const,
  voce: 'PICKPOCKET',
  voce_label: 'borseggi',
  anno: 2024,
  anno_confronto: 2014,
  delitti: 5000,
  delitti_confronto: 4000,
  tasso: 180.5,
  tasso_sotto_soglia: false,
  tasso_italia: 90.2,
  tasso_italia_sotto_soglia: false,
  variazione_pct: 25,
  motivo_senza_variazione: null,
  rottura_2016: false,
  collegamenti: [
    {
      hazard: 'borseggioTuristi',
      hazard_label_it: 'Borseggio turisti',
      corrispondenza: 'esatta' as const,
    },
  ],
};
const istat: IstatPoi = { cornice: { ...riga, voce: 'TOT', collegamenti: [] }, righe: [riga] };

const base = analyzeFixture as unknown as AnalyzeResponse;
const fastAnalyze: AnalyzeResponse = {
  ...base,
  poi: base.poi.map((p) => (p.id === '1' ? { ...p, istat } : p)),
  narrativa: null,
  narrativa_fonti: { overview: '', ontologia: '', contesto: '', speculativo: '' },
};
const zoneNarrative: ZoneNarrativeResponse = {
  narrativa: 'x',
  narrativa_fonti: {
    overview: 'Sintesi.',
    ontologia:
      'Presso il Colosseo pesa il **“borseggio turisti”**, che secondo i dati ISTAT del Comune di Roma ha un tasso più alto di quello italiano.',
    contesto: 'Contesto.',
    speculativo: '',
  },
  tokens_input: 1,
  tokens_output: 1,
  latenza_ms: 1,
  repro: { temperature: 0, seed: 0, prompt_hash: 'h' },
  fallback: false,
  llm_used: 'test',
};

test('ISTAT in linea: l’indicatore compare dopo la prima menzione nel tab ONTOLOGIA e non negli altri', async ({
  page,
}) => {
  await mockApi(page, { analyze: fastAnalyze, zoneNarrative });
  await page.goto('/');
  await drawSearchCircle(page);
  await S.submitButton(page).click();

  const ontologia = page.locator('#cra-narr-panel-ONTOLOGIA');
  const indicatore = ontologia.locator('.cra-narr-istat');
  await expect(indicatore).toHaveCount(1);
  await expect(indicatore).toContainText(
    'ISTAT · Comune di Roma 2024 · borseggi: 180,5 ogni 100.000 ab. (Italia 90,2)',
  );
  await expect(indicatore).toContainText('+25% dal 2014');
  await expect(ontologia.locator('.cra-narr-istat-note')).toBeVisible();
  // markdown reso senza asterischi visibili, indicatore dopo la chiusura del grassetto
  await expect(ontologia.locator('.cra-narr-prose')).not.toContainText('*');
  await expect(ontologia.locator('.cra-narr-prose strong')).toHaveCount(1);

  await page.getByRole('tab', { name: 'CONTESTO' }).click();
  await expect(page.locator('.cra-narr-istat')).toHaveCount(1); // solo quello (nascosto) di ONTOLOGIA
  await expect(page.locator('#cra-narr-panel-CONTESTO .cra-narr-istat')).toHaveCount(0);
});
