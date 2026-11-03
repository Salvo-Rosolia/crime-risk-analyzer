import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { MapComponent } from '@features/map/map.component';
import { InputPanelComponent } from '@features/panels/input/input-panel.component';
import { LoadingOverlayComponent } from '@features/panels/loading/loading-overlay.component';
import { PanelDockComponent } from '@features/panels/dock/panel-dock.component';
import { NarrativeSheetComponent } from '@features/panels/narrative/narrative-sheet.component';
import { BasePanelComponent } from '@features/panels/base/base-panel.component';
import { HeaderControlsComponent } from '@features/panels/header-controls/header-controls.component';
import { SourcesIndicatorComponent } from '@features/panels/sources-indicator/sources-indicator.component';
import { SourcesPageComponent } from '@features/panels/sources/sources-page.component';
import { ApiService } from '@core/api/api.service';
import { SourcesStore } from '@core/state/sources.store';
import { errorMessage, StateStore } from '@core/state/state.store';
import {
  AnalyzeRequestPayload,
  BaselineParams,
  Circle,
  Confidence,
  Mode,
  NumberedPoi,
  SearchArea,
} from '@core/models/models';

/**
 * Error message for "go to a place" (review finding fix): unlike all the other
 * points of this app that use `errorMessage(err, fallback)` with a fixed fallback, here the
 * literal "Luogo non trovato." is correct ONLY when the backend really answers 404 (no
 * result for the query — `/geocode` sends it as a STRING `detail`, not `{messaggio}`, see
 * `main.py:geocode`). Showing it for ANY other error — backend down (Vite proxy → 500 with an empty
 * body), Starlette 500, `status 0` (network unreachable), pydantic 422 with a LIST `detail` (e.g.
 * query over 200 characters), non-JSON response from the proxy (200 with parse error) — would hide
 * the real failure behind a message implying "the place does not exist" instead of "the service
 * did not answer": it is exactly the bug that hid, under `ng serve`, the absence of `/geocode` in
 * `proxy.config.json`. Outside the 404, it reuses `errorMessage` for the same unpacking of
 * `error.error.detail.messaggio` (e.g. the 503 "Servizio di geocoding non raggiungibile."), with a
 * generic fallback when the backend provides no unpackable message.
 */
function placeSearchErrorMessage(err: unknown): string {
  if (err instanceof HttpErrorResponse && err.status === 404) return 'Luogo non trovato.';
  return errorMessage(err, 'Ricerca del luogo non disponibile, riprova.');
}

/** Enter key pressed while a composition is active or ending (#375): accent dead keys,
 * IME. `isComposing` covers the browsers that set it; `keyCode 229` ("Process") covers
 * Safari, which emits the confirming `keydown` AFTER `compositionend` with `isComposing` already false.
 *
 * Known trade-off, not verified on a real device: `(keydown.enter)` fires only with
 * `key === 'Enter'`, so keyboards that emit `key: 'Unidentified'` do not get here. The
 * residual risk is a `key: 'Enter'` with `keyCode 229` while a composition is active (possible
 * second Enter on some Android keyboards): it is ignored, and the user presses Enter again once the composition is closed. */
function isCompositionEnter(event: KeyboardEvent): boolean {
  return event.isComposing || event.keyCode === 229;
}

@Component({
  selector: 'cra-root',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    MapComponent,
    InputPanelComponent,
    LoadingOverlayComponent,
    PanelDockComponent,
    NarrativeSheetComponent,
    BasePanelComponent,
    HeaderControlsComponent,
    SourcesIndicatorComponent,
    SourcesPageComponent,
  ],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App {
  protected readonly store = inject(StateStore);
  protected readonly sources = inject(SourcesStore);
  private readonly api = inject(ApiService);
  /** Handle on the real map (#318): needed only for `flyTo` from the "go to a place" box — see
   * the identical idiom inside `MapComponent` itself (`mapEl = viewChild.required(...)`). */
  private readonly mapRef = viewChild.required(MapComponent);

  /**
   * Circle drawn on the map: one of the TWO area-selection modes that coexist
   * (#335, as before #318), fed by the `circleChange` output of `MapComponent`.
   * `MapComponent` is not inside the screen `@switch` (always mounted), so this signal
   * needs no reseeding on screen change — only `onResetConfirmed` clears it
   * explicitly ("+ Nuova richiesta" forces redrawing or retyping).
   */
  protected readonly circle = signal<Circle | null>(null);
  /**
   * City/zone typed (#335): the OTHER area-selection mode, state shared here in the shell
   * (not in the panels, not in the FSM) because both `InputPanelComponent` and
   * `BasePanelComponent` must see them identical and they must survive their own remount between states
   * (`@switch (store.screen())`) and a Full↔Base round trip.
   */
  protected readonly city = signal('');
  protected readonly zone = signal('');
  /**
   * `ontology_class` selected in the "Tipo POI" select of the base-system panel (#143), same
   * state shared in the shell as `city`/`zone`: `BasePanelComponent` is remounted at every
   * Full↔Base round trip (`@switch (store.screen())`, `app.html`), so a local copy in the panel
   * would silently lose the selection. It does not enter `area` (unlike `city`/`zone`): it is an
   * optional filter of the form, not one of the two area-selection modes.
   */
  protected readonly poiType = signal('');
  /**
   * The active AREA, in the mode chosen last. The two modes coexist but do not
   * add up: choosing one clears the other (see `onCircleChange`/`onCityChange`/`onZoneChange`),
   * so there is no state in which the user does not know which area would be analyzed.
   * `SearchArea` makes that mutual exclusion a fact of the type, not a convention to remember.
   * City/zone count only as a COMPLETE (trimmed) PAIR: only one filled is not yet an area,
   * same rule as `validateInputPanel` (`core/ui-helpers.ts`).
   */
  protected readonly area = computed<SearchArea | null>(() => {
    const c = this.circle();
    if (c) return { kind: 'circle', center: { lat: c.lat, lon: c.lon }, radiusM: c.radiusM };
    const city = this.city().trim();
    const zone = this.zone().trim();
    return city && zone ? { kind: 'zone', city, zone } : null;
  });
  /** "Go to a place" box in the header (#318, back to pure navigation with #335): a
   * map navigation aid (Nominatim + flyTo), independent of the search area — it does not touch the
   * FSM nor `circle`/`city`/`zone`. */
  protected readonly placeQuery = signal('');
  protected readonly placeError = signal<string | null>(null);
  /** Sequence token for `onGoToPlace` (review finding fix, same idiom as
   * `StateStore.contextChanged`, here with a counter instead of a fingerprint because there is no
   * request hash to compare): incremented at every submit, captured locally before the
   * `await`. A request A launched and then overtaken by a more recent request B must not
   * apply its own effects (`flyTo`/`placeError`) if it arrives later — otherwise a late response A
   * would silently overwrite the map/error that B has already set. */
  private placeRequestSeq = 0;
  /** Normalized text (trim) of the most recent `/geocode` request STILL in flight (#344), `null`
   * when the request has finished (success or error). An Enter on the same text while set does not
   * launch a new request: the one in progress will already apply the same effects. In-flight
   * dedup only, no caching of results (that lives in the backend). */
  private placeInFlightQuery: string | null = null;

  /**
   * Selected POI + its number (same order/number as the paired pin and card), for
   * the dock's Detail view (#199): a single computed prevents the two pieces of information from
   * getting out of sync.
   *
   * Guard on `store.screen() === 'DETAIL'` (review #199 fix): `TOGGLE_MODE` does NOT clear
   * `selectedPoiId` (transition.ts, behavior unchanged/tested elsewhere), so a
   * RESULTS→DETAIL→(toggle Base)→(toggle Full) round trip would return to RESULTS with `selectedPoiId`
   * still set — without this guard the dock would show the Detail view while the FSM
   * state is RESULTS (UI↔FSM desync). The dock's view must depend EXCLUSIVELY on
   * `screen`, never be inferred from the mere presence of a leftover `selectedPoiId`.
   */
  protected readonly selectedDetail = computed<NumberedPoi | null>(() => {
    if (this.store.screen() !== 'DETAIL') return null;
    const id = this.store.selectedPoiId();
    const poi = this.store.fullData()?.poi ?? [];
    const index = poi.findIndex((p) => p.id === id);
    return index >= 0 ? { poi: poi[index], number: index + 1 } : null;
  });

  constructor() {
    // The active set really changed (#419): the results on screen were computed on the
    // previous set, so we start over from a new request (same reset as "+ Nuova
    // richiesta"). It observes the store, not the dialog: it works even if the page was closed
    // while the upload was in flight. The initial value is not a change.
    let seen = this.sources.revision();
    effect(() => {
      const revision = this.sources.revision();
      if (revision === seen) return;
      seen = revision;
      untracked(() => {
        this.onResetConfirmed();
      });
    });
    // The sources live in the server session: at startup we re-read which ones are active (a
    // reload finds the ones uploaded before), so the indicator is right immediately.
    void this.sources.refresh();
  }

  protected onCircleChange(c: Circle | null): void {
    this.circle.set(c);
    // Drawing a circle REPLACES city/zone as the active area: keeping both would leave
    // the user with no way to know which of the two would be analyzed (and the backend would reject
    // a body with both anyway, 422).
    if (c) {
      this.city.set('');
      this.zone.set('');
    }
  }

  /** Typing in city/zone (non-empty value) REPLACES the circle as the active area — same
   * mutual exclusion as `onCircleChange`, in the opposite direction: "the last choice wins". */
  protected onCityChange(value: string): void {
    this.city.set(value);
    if (value.trim()) this.clearCircleIfAny();
  }

  protected onZoneChange(value: string): void {
    this.zone.set(value);
    if (value.trim()) this.clearCircleIfAny();
  }

  /** "Tipo POI" select of the base-system panel (#143): unlike `onCityChange`/
   * `onZoneChange` it does not touch `circle`/the area — it is an optional filter, not an
   * area-selection mode. */
  protected onPoiTypeChange(value: string): void {
    this.poiType.set(value);
  }

  private clearCircleIfAny(): void {
    if (!this.circle()) return;
    this.circle.set(null);
    this.mapRef().clearCircle();
  }

  protected onPlaceQueryInput(event: Event): void {
    this.placeQuery.set((event.target as HTMLInputElement).value);
  }

  /**
   * "Go to a place" (#318, back to pure navigation with #335): geocodes the free text
   * (`ApiService.geocodePlace`, Nominatim) and moves the map (`MapComponent.flyTo`) — it does not touch
   * `circle` nor `city`/`zone`: it is ONLY a navigation aid, never the choice of the area to
   * analyze (that is chosen with the circle or the panel's fields, never from here).
   *
   * Sequence guard (review finding fix, race condition): without `seq`, a quick submit of
   * A then B with A's response arriving AFTER B's would apply A's effects last
   * — the map/error shown would no longer match the user's last request,
   * silently. Only the response of the request STILL the most recent (`seq === this.
   * placeRequestSeq` when it arrives) applies `flyTo`/`placeError`; the others are discarded.
   *
   * Error message (review finding fix): `placeSearchErrorMessage` (above) shows "Luogo non
   * trovato." ONLY for a real 404 (no result); for any other error — backend down, 500,
   * status 0, 422 with list `detail`, non-JSON response from the proxy — it shows the backend's `detail.messaggio`
   * when there is one (e.g. 503 "Servizio di geocoding non raggiungibile.") or a generic message
   * otherwise. Before this fix the literal "Luogo non trovato." appeared for ANY
   * error without `detail.messaggio`, hiding real failures (that is how the absence of `/geocode`
   * in `proxy.config.json` went unnoticed).
   *
   * No redundant requests (#344): the sequence guard discards stale responses but does not
   * avoid requests. So (1) the automatic key repeat (`event.repeat`, Enter held
   * down) is ignored and (2) an Enter on the same normalized (trim) text as the most
   * recent request still in flight reuses that one, without launching another (nor incrementing `seq`: the
   * request in progress stays the most recent and applies its own effects). A different text launches
   * a new request, which makes the previous ones obsolete as before.
   *
   * Composition (#375): the Enter that CONFIRMS a composition (accent dead keys, IME) is not
   * a user request — the text is still partial — so it is ignored (`isCompositionEnter`).
   * "+ Nuova richiesta" invalidates the in-flight request (see `onResetConfirmed`).
   */
  protected async onGoToPlace(event: Event): Promise<void> {
    if (event instanceof KeyboardEvent && (event.repeat || isCompositionEnter(event))) return;
    const q = this.placeQuery().trim();
    if (!q) return;
    if (q === this.placeInFlightQuery) return;
    const seq = ++this.placeRequestSeq;
    this.placeInFlightQuery = q;
    try {
      const { lat, lon } = await this.api.geocodePlace(q);
      if (seq !== this.placeRequestSeq) return;
      this.placeError.set(null);
      this.mapRef().flyTo(lat, lon);
    } catch (err) {
      if (seq !== this.placeRequestSeq) return;
      this.placeError.set(placeSearchErrorMessage(err));
    } finally {
      if (seq === this.placeRequestSeq) this.placeInFlightQuery = null;
    }
  }

  protected onAnalyze({ area, question }: AnalyzeRequestPayload): void {
    void this.store.startAnalysis(area, question);
  }

  protected onPoiClick(id: string): void {
    this.store.dispatch({ type: 'SELECT_POI', id });
    // Narrative specific to the point (#197): generated at selection, not in advance for all
    // POIs (it would be one LLM call per pin). The store skips the call if it is already cached.
    void this.store.loadPoiNarrative(id);
  }

  protected onCloseDetail(): void {
    this.store.dispatch({ type: 'DESELECT_POI' });
  }

  protected onSetFilter(level: Confidence): void {
    this.store.dispatch({ type: 'SET_FILTER', level });
  }

  protected onClearFilter(): void {
    this.store.dispatch({ type: 'CLEAR_FILTER' });
  }

  protected onToggleNarr(): void {
    this.store.dispatch({ type: 'TOGGLE_NARR' });
  }

  /** Collapse of the POI List/Detail dock (#199 decision 3): wires `TOGGLE_POI_PANEL`, dormant
   * in FSM+test until no UI control invoked it. */
  protected onTogglePoiPanel(): void {
    this.store.dispatch({ type: 'TOGGLE_POI_PANEL' });
  }

  /** "+ Nuova richiesta" (#199 decision 4): the dock (`cra-panel-dock`) already shows its own
   * light IN-APP confirmation before emitting this event — it arrives here only after the
   * user's confirmation, so it dispatches `RESET` directly (no `window.confirm`). */
  protected onResetConfirmed(): void {
    this.store.dispatch({ type: 'RESET' });
    // #318/#335: after "+ Nuova richiesta" the user must redraw the circle or retype
    // city/zone — they are not implicitly reused for the next analysis (MapComponent itself does not
    // unmount, so without this explicit reset the old circle would silently remain
    // valid).
    this.circle.set(null);
    this.city.set('');
    this.zone.set('');
    this.poiType.set('');
    this.placeQuery.set('');
    // #375: an in-flight geocoding must not survive the reset. Incrementing `placeRequestSeq` makes
    // its response (success or error) be discarded by the `seq !== placeRequestSeq` checks of
    // `onGoToPlace`; clearing the dedup marker makes the same text retyped after the reset start
    // as a new request (the `finally` of the overtaken request does not touch it: guard on `seq`).
    this.placeRequestSeq++;
    this.placeInFlightQuery = null;
    // The error of an already finished search must not stay on screen with the box emptied.
    this.placeError.set(null);
    // Resetting the local signal is not enough (review finding I5): MapComponent keeps its own
    // circleLayer drawn on the map independently of this signal, so without
    // clearCircle() the old circle would stay visible and clickable while the rest of the UI
    // (disabled button, "disegna un cerchio" instruction) says the opposite.
    this.mapRef().clearCircle();
  }

  /**
   * Guard (review #67-bis, blocker A): no mode change while a request is in
   * flight. Redundant with the `[disabled]` of `HeaderControlsComponent` during LOADING (which already
   * prevents the click) — defense in depth in case that level is bypassed; the primary
   * defense remains structural anyway (transition.ts routes on action.pipeline, never on
   * state.mode, so the correctness of the data does not depend on this guard).
   */
  protected onToggleMode(mode: Mode): void {
    if (this.store.screen() === 'LOADING') return;
    this.store.dispatch({ type: 'TOGGLE_MODE', mode });
  }

  protected onBaseSearch(params: BaselineParams): void {
    void this.store.startBaselineAnalysis(params);
  }

  /**
   * "Rigenera" (narrative panel): acts on the SCOPE shown (#197). In Detail view
   * it regenerates the selected POI's narrative (`force`, bypasses the session cache) — relaunching
   * the whole zone analysis here would cost geocoding + Overpass + a zone LLM to rewrite a
   * text the user is looking at on a single point, and on top of that it would unmount the selection.
   *
   * Otherwise the zone behavior remains: re-POST /analyze with the last full query
   * (spec-frontend.md §API — "no new endpoint"), reusing `startAnalysis` just as
   * `onAnalyze` does for the InputPanel. `LOAD_SUCCESS` replaces `fullData` as a whole (it does not
   * append it), so it does not duplicate the previous results; it never touches `baselineData`.
   */
  protected onRegenerate(): void {
    const id = this.store.screen() === 'DETAIL' ? this.store.selectedPoiId() : null;
    if (id) {
      void this.store.loadPoiNarrative(id, { force: true });
      return;
    }
    const query = this.store.lastQuery();
    if (!query) return;
    void this.store.startAnalysis(query.area, query.question);
  }
}
