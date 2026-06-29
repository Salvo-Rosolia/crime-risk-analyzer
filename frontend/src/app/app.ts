import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MapComponent } from '@features/map/map.component';
import { StateStore } from '@core/state/state.store';

@Component({
  selector: 'cra-root',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [MapComponent],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App {
  protected readonly store = inject(StateStore);
}
