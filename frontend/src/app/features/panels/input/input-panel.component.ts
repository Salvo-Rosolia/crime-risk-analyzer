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
import { AnalyzeRequestPayload, SearchArea } from '@core/models/models';
import { validateInputPanel } from '@core/ui-helpers';

/**
 * "Analisi zona" panel: covers both State A (initial input) and the Error State
 * (same form, with the server message shown inline) — see spec-frontend.md §Error State.
 *
 * The AREA is chosen in one of the TWO modes that coexist (as before #318, restored
 * by #335 after #318/#331 had replaced them with only the circle + text search): the circle
 * drawn on `MapComponent`, or city and zone typed HERE (`city`/`zone`, state shared
 * in the shell — it survives the remount of this component across INPUT/LOADING/ERROR and stays
 * in sync with `BasePanelComponent`). `area` arrives from outside already combined by the shell
 * (`App.area`, "the last choice wins"): this component never decides on its own which mode is
 * active, it just reflects `city`/`zone` in the fields and propagates the changes upwards.
 *
 * `@switch (store.screen())` unmounts/remounts this component at every state change
 * (INPUT→LOADING→ERROR are distinct `@case`s): the local `question` signal would be cleared
 * at every remount. `initialQuestion` (set by the shell with the last "pending" value of the
 * store, which survived LOADING/ERROR) allows reseeding the form at construction, so
 * the user finds what they had typed after an error. `city`/`zone` do not need the
 * same treatment: they live in the shell, not in this component, so they survive on their own.
 */
@Component({
  selector: 'cra-input-panel',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './input-panel.component.html',
  styleUrl: './input-panel.component.css',
})
export class InputPanelComponent implements OnInit {
  /** Error message coming from the backend (Error State, e.g. zone that cannot be geocoded). */
  readonly serverError = input<string | null>(null);
  /** Last value sent (from `store.pendingQuestion`): reseeds the form on remount. */
  readonly initialQuestion = input<string | null>(null);
  /** Chosen area (drawn circle or typed city/zone), combined by the shell; `null` until
   * one has been chosen in either of the two modes. */
  readonly area = input<SearchArea | null>(null);
  /** Current city/zone (state shared in the shell, #335): this component reflects them in the
   * fields and that is all, it does not own them. */
  readonly city = input<string>('');
  readonly zone = input<string>('');
  readonly cityChange = output<string>();
  readonly zoneChange = output<string>();
  readonly analyze = output<AnalyzeRequestPayload>();

  private readonly api = inject(ApiService);

  protected readonly cities = signal<string[]>([]);
  protected readonly question = signal('');
  protected readonly validationError = signal<string | null>(null);
  protected readonly validationField = signal<'city' | 'zone' | null>(null);
  /**
   * The area for which the last server error arrived (review finding: otherwise a 503 in
   * circle mode stays "stuck" on the zone border as soon as the user types city/zone,
   * despite having nothing to do with that submit). Comparison by reference: `area()` is a
   * `computed` in the shell (`App.area`) that Angular re-evaluates and thus re-references ONLY when
   * one of its sources (`circle`/`city`/`zone`) really changes — a retry with the same
   * values (no change in the fields) keeps the same reference, so the error stays
   * correctly attached; a new circle or a new city/zone pair produces a
   * different one, and the attachment is cleared.
   */
  private readonly serverErrorArea = signal<SearchArea | null>(null);
  protected readonly displayError = computed(() => this.validationError() ?? this.serverError());

  /** Error border on the city field: only if the client validation attributed it to it. */
  protected readonly cityHasError = computed(() => this.validationField() === 'city');
  /**
   * Error border on the zone field: client validation on it, or — when there is no
   * active client error — the server error of the Error State, BUT only if the CURRENT area is the
   * same one for which that error arrived AND it is in city/zone mode (a geocoding error on
   * a circle is cosmetic, see `App.onCircleChange`/`startAnalysis`, and must not light up the
   * border of unrelated fields; an error born on an area later replaced must not stay
   * attached to a field that now represents a different area).
   */
  protected readonly zoneHasError = computed(
    () =>
      this.validationField() === 'zone' ||
      (!this.validationError() &&
        !!this.serverError() &&
        this.area()?.kind === 'zone' &&
        this.area() === this.serverErrorArea()),
  );

  constructor() {
    // Changing area (new drawn circle, or city/zone that become a valid pair/
    // another pair) clears the CLIENT validation still visible — otherwise "Inserisci una
    // città." would stay stuck even after a circle has been drawn (review finding).
    // `untracked` because the effect must fire ONLY when `area` changes, not every time
    // `clearValidation` touches the other signals it reads.
    effect(() => {
      this.area();
      untracked(() => this.clearValidation());
    });
    // Captures the area for which THIS server error was born, read without tracking it (otherwise
    // the effect would also fire at every area change, defeating the comparison in
    // `zoneHasError`): it must depend ONLY on `serverError`.
    effect(() => {
      const err = this.serverError();
      this.serverErrorArea.set(err ? untracked(() => this.area()) : null);
    });
  }

  ngOnInit(): void {
    this.question.set(this.initialQuestion() ?? '');
    void this.loadCities();
  }

  protected onCityInput(event: Event): void {
    this.cityChange.emit((event.target as HTMLInputElement).value);
    this.clearValidation();
  }

  protected onZoneInput(event: Event): void {
    this.zoneChange.emit((event.target as HTMLInputElement).value);
    this.clearValidation();
  }

  protected onQuestionInput(event: Event): void {
    this.question.set((event.target as HTMLTextAreaElement).value);
  }

  protected onSubmit(event: Event): void {
    event.preventDefault();

    const area = this.area();
    if (!area) {
      // No circle drawn AND city/zone not (yet) both filled: same rule as
      // `App.area` (a city/zone area exists only as a complete pair), here only to give a
      // precise message about WHICH field is missing — the button stays enabled anyway (pre-#318 UX:
      // better a submit that explains what is missing than a disabled button with no why).
      const { ok, error, field } = validateInputPanel({ city: this.city(), zone: this.zone() });
      if (!ok) {
        this.validationError.set(error);
        this.validationField.set(field);
      }
      return;
    }

    this.clearValidation();
    const question = this.question().trim();
    this.analyze.emit({ area, question: question || null });
  }

  private clearValidation(): void {
    this.validationError.set(null);
    this.validationField.set(null);
  }

  private async loadCities(): Promise<void> {
    try {
      const cities = await this.api.cities();
      this.cities.set(cities);
    } catch {
      this.cities.set([]);
    }
  }
}
