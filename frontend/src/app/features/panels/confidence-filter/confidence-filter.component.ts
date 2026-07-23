import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { CONF } from '@core/confidence';
import { Confidence } from '@core/models/models';

const LEVELS: readonly Confidence[] = ['verificato', 'da_confermare', 'ipotesi'];

const ZERO_COUNTS: Readonly<Record<Confidence, number>> = Object.freeze({
  verificato: 0,
  da_confermare: 0,
  ipotesi: 0,
});

/**
 * Significato breve di ciascun livello di confidence (story #207): distinto dalla `label` di
 * `CONF` (nome del livello) — qui è la spiegazione mostrata accanto al nome, non riusata altrove.
 */
const MEANINGS: Readonly<Record<Confidence, string>> = Object.freeze({
  verificato: 'entità identificata in mappa',
  da_confermare: 'punto anonimo in mappa',
  ipotesi: 'fuori ontologia',
});

/**
 * Nota chiave (story #207): il livello di confidence NON è un punteggio di pericolosità — vincolo
 * di posizionamento non negoziabile (_project.md §Vincoli). Testo esatto richiesto dalla story.
 */
export const CONFIDENCE_FILTER_NOTE =
  "Il livello indica quanto il POI è ancorato a un'entità verificabile in mappa — non è un " +
  'livello di pericolosità.';

/**
 * Controllo unificato "Confidenza" (story #207, opzione A): sostituisce la vecchia coppia
 * legenda + barra chip-filtro (duplicava i 3 livelli). Ogni riga è insieme legenda (nome +
 * significato) e filtro (toggle): click su una riga chiede al genitore di attivarla come filtro,
 * click sulla riga già attiva chiede di azzerarlo. Il componente non decide da sé
 * set/clear — resta "thin": emette solo il livello cliccato (`rowClick`), il genitore
 * (`PoiPanelComponent`) applica la logica di toggle già esistente (`onChipClick`), cambia solo
 * come viene attivata/renderizzata, non la logica di filtering.
 */
@Component({
  selector: 'cra-confidence-filter',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './confidence-filter.component.html',
  styleUrl: './confidence-filter.component.css',
})
export class ConfidenceFilterComponent {
  readonly counts = input<Record<Confidence, number>>(ZERO_COUNTS);
  readonly activeFilter = input<Confidence | null>(null);

  readonly rowClick = output<Confidence>();

  protected readonly levels = LEVELS;
  protected readonly conf = CONF;
  protected readonly meanings = MEANINGS;
  protected readonly note = CONFIDENCE_FILTER_NOTE;
}
