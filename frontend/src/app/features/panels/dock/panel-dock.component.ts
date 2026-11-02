import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Injector,
  afterNextRender,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { Confidence, NumberedPoi, Poi, RiskModel } from '@core/models/models';
import { PoiPanelComponent } from '@features/panels/poi/poi-panel.component';
import { DetailPanelComponent } from '@features/panels/detail/detail-panel.component';

/**
 * Single dock on the left (Approach A, variant 1, #199): POI List and Detail are no longer
 * separate floating panels (List top-left + Detail top-right), but two mutually
 * exclusive VIEWS of this same container — drill-down `List → POI click → Detail → "‹
 * indietro"` (`cra-detail-back`, inside `cra-detail-panel`). It reuses `cra-poi-panel`/
 * `cra-detail-panel` as they are, no filter/detail logic rewritten here.
 *
 * The List view stays MOUNTED (`[hidden]`, not `@if`) when switching to the Detail view: the
 * dock does not unmount when moving between views, to preserve scroll/state — consistent with the existing
 * non-remount tests (`app.spec.ts`).
 *
 * Height coordinated with `narrOpen` (the narrative bottom sheet is full-width below: dock and
 * narrative must never overlap, acceptance criteria #199) via host class
 * `cra-dock-narr-open` read by `panel-dock.component.css`. Collapsible (`open`, wired to
 * `TOGGLE_POI_PANEL`/`poiPanelOpen`, dormant in the FSM until no UI control invoked it).
 */
@Component({
  selector: 'cra-panel-dock',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [PoiPanelComponent, DetailPanelComponent],
  templateUrl: './panel-dock.component.html',
  styleUrl: './panel-dock.component.css',
  host: {
    '[class.cra-dock-collapsed]': '!open()',
    '[class.cra-dock-narr-open]': 'narrOpen()',
  },
})
export class PanelDockComponent {
  readonly pois = input<Poi[]>([]);
  readonly filter = input<Confidence | null>(null);
  readonly selectedId = input<string | null>(null);
  /** Selected POI + number (Detail view): `null` → shows the List view. */
  readonly detail = input<NumberedPoi | null>(null);
  readonly riskModels = input<RiskModel[]>([]);
  /** Collapse of the dock (`store.poiPanelOpen()`). */
  readonly open = input<boolean>(true);
  /** State of the narrative bottom sheet (`store.narrOpen()`): drives the dock height via CSS. */
  readonly narrOpen = input<boolean>(true);

  readonly selectPoi = output<string>();
  readonly setFilter = output<Confidence>();
  readonly clearFilter = output<void>();
  /** "‹ indietro" from the Detail view (`cra-detail-panel`): the shell dispatches `DESELECT_POI`. */
  readonly closeDetail = output<void>();
  readonly toggleOpen = output<void>();
  /** Emitted only AFTER the light in-app confirmation (never `window.confirm`, #199 decision 4). Name
   * not `reset` because of `@angular-eslint/no-output-native` (it collides with the DOM `reset` event). */
  readonly resetConfirmed = output<void>();

  /** Light IN-APP confirmation: "+ Nuova richiesta" turns into
   * "Ricominciare? Perderai i risultati [Sì] [Annulla]" before emitting `resetConfirmed`. */
  protected readonly confirmingReset = signal(false);

  private readonly newRequestButtonRef = viewChild<ElementRef<HTMLButtonElement>>('newRequestBtn');
  private readonly confirmYesButtonRef = viewChild<ElementRef<HTMLButtonElement>>('confirmYesBtn');
  /** Needed to call `afterNextRender` outside the construction injection context
   * (inside the click handlers below), per-`options.injector` as the API provides. */
  private readonly injector = inject(Injector);

  protected onNewRequestClick(): void {
    this.confirmingReset.set(true);
    // Focus management (a11y, review #199 fix, same principle as `detail-panel.component.ts`):
    // moves the focus to the "Sì" button AFTER Angular has updated the DOM for the new value
    // of `confirmingReset` (otherwise the `confirmYesButtonRef` query would still read `undefined`
    // — the `@else` block with "Sì"/"Annulla" does not exist until that render has happened).
    afterNextRender(() => this.confirmYesButtonRef()?.nativeElement.focus(), {
      injector: this.injector,
    });
  }

  protected onConfirmReset(): void {
    this.confirmingReset.set(false);
    this.resetConfirmed.emit();
  }

  protected onCancelReset(): void {
    this.confirmingReset.set(false);
    // "Annulla" (a11y, review #199 fix): puts the focus back on "+ Nuova richiesta" after the DOM
    // has gone back to the normal button (same reason as `onNewRequestClick`).
    afterNextRender(() => this.newRequestButtonRef()?.nativeElement.focus(), {
      injector: this.injector,
    });
  }
}
