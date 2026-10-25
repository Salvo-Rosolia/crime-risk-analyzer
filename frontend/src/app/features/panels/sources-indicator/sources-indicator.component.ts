import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import type { IndicatorKind } from '@core/state/sources.store';

/**
 * Indicatore sempre visibile delle fonti attive (#419): vive nell'header, quindi resta in vista in
 * qualunque stato della mappa. È anche il modo di aprire la pagina Fonti. Componente "thin":
 * nessun accesso allo store, solo `input()`/`output()`.
 */
@Component({
  selector: 'cra-sources-indicator',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './sources-indicator.component.html',
  styleUrl: './sources-indicator.component.css',
})
export class SourcesIndicatorComponent {
  readonly label = input('Predefinite');
  readonly kind = input<IndicatorKind>('default');
  readonly openPage = output<void>();
}
