import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import type { IndicatorKind } from '@core/state/sources.store';

/**
 * Always-visible indicator of the active sources (#419): it lives in the header, so it stays in view in
 * any state of the map. It is also the way to open the Fonti page. "Thin" component:
 * no access to the store, only `input()`/`output()`.
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
