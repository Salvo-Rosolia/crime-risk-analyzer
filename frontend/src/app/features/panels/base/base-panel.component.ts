import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { ApiService } from '@core/api/api.service';
import { AnalyzeResponse, BaselineParams, PoiType, SearchArea } from '@core/models/models';
import { buildBaseRows, validateInputPanel } from '@core/ui-helpers';

/**
 * "Sistema base" panel (ablation study, Base-system State — spec-frontend.md): structured
 * form (optional POI type + City/Zone) → "POI · Hazard · Categoria" table via
 * `POST /analyze/baseline`, deliberately spartan (no NL, narrative, confidence, SPARQL
 * path, map: the contrast with the full system is itself a thesis topic).
 *
 * The area is chosen in one of the TWO modes that coexist (#335, same scheme as
 * `InputPanelComponent`): the circle drawn on `MapComponent`, or city and zone typed
 * HERE — `city`/`zone` are state shared in the shell (`App`), so they survive both the remount
 * of this component and a Full↔Base round trip (the same typed value stays visible in
 * both panels).
 *
 * Dead end otherwise (final review finding C1): `:host` (base-panel.component.css) is an
 * opaque overlay that coincides, above, with the whole map — if the user switches to "Sistema base" BEFORE
 * ever having drawn a circle in full mode AND without having typed city/zone, the map
 * to draw the circle stays hidden/unclickable. `!area()` therefore shows a message that
 * recalls BOTH ways (type here, or go back to Full for the circle) plus a button that
 * emits `backToFull`, wired in `app.html` to the same `onToggleMode('full')` that already
 * exists for the header.
 */
@Component({
  selector: 'cra-base-panel',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './base-panel.component.html',
  styleUrl: './base-panel.component.css',
})
export class BasePanelComponent implements OnInit {
  readonly data = input<AnalyzeResponse | null>(null);
  /** Chosen area (drawn circle or typed city/zone), combined by the shell; `null` until
   * one has been chosen in either of the two modes. */
  readonly area = input<SearchArea | null>(null);
  /** Current city/zone (state shared in the shell, #335): reflected in the fields, not owned here. */
  readonly city = input<string>('');
  readonly zone = input<string>('');
  readonly cityChange = output<string>();
  readonly zoneChange = output<string>();
  /** `terminus_class` selected in the "Tipo POI" select, or empty string for "Tutti i tipi"
   * (no filter): same state shared in the shell as `city`/`zone` (#143, review finding),
   * so it survives the Full↔Base remount and is cleared with "+ Nuova richiesta" together with the rest
   * of the area, instead of a local copy that a mode round trip would silently lose. */
  readonly poiType = input<string>('');
  readonly poiTypeChange = output<string>();
  /** Emitted by the "Torna a Completo" button (visible only without an area, #318 C1): the shell
   * wires it to `onToggleMode('full')`, the same transition already reachable from the header
   * toggle. */
  readonly backToFull = output<void>();
  /**
   * Error message from the server (`store.error()` when `LOAD_ERROR` arrives in base mode —
   * transition.ts routes here instead of the Error State shared with the full-system
   * form): the error and the retry stay inside this same panel, whose form persists
   * regardless of the outcome (blocker 2 review #67).
   */
  readonly serverError = input<string | null>(null);

  readonly analyzeBaseline = output<BaselineParams>();

  private readonly api = inject(ApiService);

  protected readonly cities = signal<string[]>([]);
  /** Options of the "Tipo POI" select (`GET /poi-types`, #143), already sorted by `label_it` by the
   * backend. Empty if the request fails: the select shows only "Tutti i tipi" — the filter is
   * optional, it must not block the search. */
  protected readonly poiTypes = signal<PoiType[]>([]);
  protected readonly validationError = signal<string | null>(null);
  protected readonly validationField = signal<'city' | 'zone' | null>(null);
  /** The area for which the last server error arrived (review finding, same convention as
   * InputPanelComponent.serverErrorArea): comparison by reference, reliable because `area()`
   * (the shell combines circle/city/zone in a `computed`) changes reference only when one of
   * those sources really changes. */
  private readonly serverErrorArea = signal<SearchArea | null>(null);
  /** Client validation always takes priority over the server error, same convention as InputPanelComponent. */
  protected readonly displayError = computed(() => this.validationError() ?? this.serverError());
  protected readonly cityHasError = computed(() => this.validationField() === 'city');
  /** Error border on the zone: client validation on it, or — without an active client error,
   * only if the rejected area was in city/zone mode AND the CURRENT area is still the one for which
   * the error arrived (same convention as InputPanelComponent.zoneHasError). */
  protected readonly zoneHasError = computed(
    () =>
      this.validationField() === 'zone' ||
      (!this.validationError() &&
        !!this.serverError() &&
        this.area()?.kind === 'zone' &&
        this.area() === this.serverErrorArea()),
  );

  protected readonly rows = computed(() =>
    buildBaseRows(this.data()?.poi, this.data()?.risk_models),
  );

  constructor() {
    // Same pair of effects as InputPanelComponent: the area change clears the client
    // validation still visible, and the area of a server error is captured ONLY at the moment
    // the error arrives (read without tracking it, otherwise the effect would fire at every
    // area change defeating the comparison in `zoneHasError`).
    effect(() => {
      this.area();
      untracked(() => this.clearValidation());
    });
    effect(() => {
      const err = this.serverError();
      this.serverErrorArea.set(err ? untracked(() => this.area()) : null);
    });
  }

  ngOnInit(): void {
    void this.loadCities();
    void this.loadPoiTypes();
  }

  protected onCityInput(event: Event): void {
    this.cityChange.emit((event.target as HTMLInputElement).value);
    this.clearValidation();
  }

  protected onZoneInput(event: Event): void {
    this.zoneChange.emit((event.target as HTMLInputElement).value);
    this.clearValidation();
  }

  protected onPoiTypeChange(event: Event): void {
    this.poiTypeChange.emit((event.target as HTMLSelectElement).value);
  }

  protected onSubmit(event: Event): void {
    event.preventDefault();

    const area = this.area();
    if (!area) {
      const { ok, error, field } = validateInputPanel({ city: this.city(), zone: this.zone() });
      if (!ok) {
        this.validationError.set(error);
        this.validationField.set(field);
      }
      return;
    }

    this.clearValidation();
    const poiType = this.poiType().trim();
    const params: BaselineParams = { area };
    if (poiType) params.poiType = poiType;
    this.analyzeBaseline.emit(params);
  }

  private clearValidation(): void {
    this.validationError.set(null);
    this.validationField.set(null);
  }

  private async loadCities(): Promise<void> {
    try {
      this.cities.set(await this.api.cities());
    } catch {
      this.cities.set([]);
    }
  }

  /** Fails without blocking the search (#143): the Tipo POI filter is optional, an empty list
   * leaves only "Tutti i tipi" in the select instead of showing an error. */
  private async loadPoiTypes(): Promise<void> {
    try {
      this.poiTypes.set(await this.api.poiTypes());
    } catch {
      this.poiTypes.set([]);
    }
  }
}
