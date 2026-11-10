import {
  afterNextRender,
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  ElementRef,
  input,
  OnDestroy,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import * as L from 'leaflet';
import type { AnalyzeResponse, Confidence, GeoZone, Poi } from '@core/models/models';
import { pinHTML } from '@core/confidence';
import { matchesFilter, poiPopupHTML } from '@core/ui-helpers';

const DEFAULT_RADIUS_M = 300;
const MIN_RADIUS_M = 150;
const MAX_RADIUS_M = 3000;

type DrawState = 'idle' | 'drawing-radius' | 'ready';

@Component({
  selector: 'cra-map',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div #mapEl class="cra-map"></div>
    @if (zeroPoiMessage(); as message) {
      <p class="cra-map-notice" role="status">{{ message }}</p>
    }
    <div class="cra-radius-control">
      @if (showRadiusInput()) {
        <label for="cra-radius-input">Raggio (m)</label>
        <input
          id="cra-radius-input"
          type="number"
          [min]="MIN_RADIUS_M"
          [max]="MAX_RADIUS_M"
          [value]="radiusM()"
          (input)="onRadiusInput($event)"
          (change)="onRadiusChange($event)"
        />
      }
      <!-- Keyboard / screen-reader way to draw the circle (#493): the map click flow alone
           excludes them. The circle is placed at the map centre (pannable with the arrow keys). -->
      <button
        type="button"
        class="cra-draw-btn"
        [disabled]="!drawingEnabled()"
        (click)="drawAtCenter()"
      >
        {{ drawState() === 'idle' ? 'Disegna cerchio al centro' : 'Ridisegna al centro' }}
      </button>
      @if (drawState() === 'drawing-radius') {
        <button type="button" class="cra-confirm-btn" (click)="confirmCircle()">
          Conferma area
        </button>
      }
    </div>
  `,
  styles: [
    `
      .cra-map {
        position: absolute;
        inset: 0;
        height: 100%;
        width: 100%;
      }

      /*
       * Numeric radius input (#318, D2/§5.1 design doc): the only KEYBOARD/screen-reader way
       * to set the radius, dragging alone excludes it. It floats above the map instead of
       * sitting in a side panel because it must stay visible in drawing-radius/ready
       * regardless of which search panel (full/base) is mounted next to the
       * map.
       *
       * Position (review finding fix: no longer top left, it was invisible/unclickable
       * everywhere). .cra-panels (app.css) is z-index:500 in the ROOT stacking context, so it always sits
       * above cra-map (z-index:0): any panel inside .cra-panels covers this
       * control, regardless of LOCAL z-index/position in here. Corner by corner:
       *  - (wide layouts; see the narrow-screen override below) top-left: ALWAYS occupied - .cra-panel in INPUT/ERROR (app.css, margin:16px) and
       *    the POI dock in RESULTS/FILTER/DETAIL (panel-dock.component.css, top/left:
       *    var(--space-4), fixed width var(--panel-max-width)) both start from there.
       *  - bottom-right: ALWAYS occupied by the Leaflet zoom control - zoomControl:false in
       *    L.map(...) (this file) disables only the default one, but shortly after it is
       *    added back by hand with L.control.zoom({ position: 'bottomright' }), so a
       *    zoom control really exists at that corner; moreover, on a wide layout, the narrative panel
       *    also lands on top of it (narrative-sheet.component.css, top/right/bottom:
       *    var(--space-4), hence full height).
       *  - bottom-left: NOT safe even though it looks free - the POI dock has only a
       *    max-height (not a fixed height) and with a full list it reaches almost the bottom; below
       *    1100px the narrative becomes a full-width bottom sheet (same
       *    narrative-sheet.component.css) and also occupies that corner when open.
       *  - top, right next to the dock/panel: free from 768px up (below, see the override). The dock/.cra-panel
       *    have a FIXED width (var(--panel-max-width), never more even with a full list - only
       *    the height grows with the content), and the narrative (when present, on a wide layout) starts
       *    from the right with its own fixed width: a free vertical corridor therefore remains
       *    between the two, where the horizontal anchoring below reuses var(--panel-max-width) instead of a
       *    fixed px value to stay correct if that constant changes.
       */
      /* Zero-POI explanation (#488): same free corridor as the radius control, one row below. */
      .cra-map-notice {
        position: absolute;
        top: calc(var(--space-4, 16px) + 3rem);
        left: calc(var(--panel-max-width, 340px) + var(--space-4, 16px) * 2);
        z-index: 500;
        max-width: 28rem;
        margin: 0;
        padding: 6px 10px;
        background: var(--paper, #fff);
        border: 1px solid var(--ink, #1a1a1a);
        border-radius: 3px;
        font-family: var(--font-sans, sans-serif);
        font-size: 0.78rem;
      }

      .cra-radius-control {
        position: absolute;
        top: var(--space-4, 16px);
        left: calc(var(--panel-max-width, 340px) + var(--space-4, 16px) * 2);
        z-index: 500;
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 6px 10px;
        background: var(--paper, #fff);
        border: 1px solid var(--ink, #1a1a1a);
        border-radius: 3px;
        font-family: var(--font-sans, sans-serif);
        font-size: 0.78rem;
      }

      /*
       * Narrow screens (#511): there is no free corridor next to the panels (the corridor
       * anchor above lands past the right edge of the viewport) and the bottom corners are taken
       * by the narrative bottom sheet, the dock and the zoom control. Below 768px the control
       * therefore spans the top of the map, wrapping if needed, and the panels and the dock start
       * below it: --map-control-reserve (styles.css) is the band they leave free for it.
       */
      @media (max-width: 767px) {
        .cra-radius-control {
          left: var(--space-4, 16px);
          right: var(--space-4, 16px);
          flex-wrap: wrap;
          box-sizing: border-box;
        }
      }

      .cra-radius-control button {
        font-family: var(--font-sans, sans-serif);
        font-size: 0.78rem;
        padding: 2px 8px;
        cursor: pointer;
      }

      .cra-radius-control input {
        width: 5.5em;
        font-family: var(--font-mono, monospace);
        font-size: 0.8rem;
        padding: 2px 4px;
        border: 1px solid var(--ink-2, #555);
        border-radius: 3px;
      }
    `,
  ],
})
export class MapComponent implements OnDestroy {
  /** Response whose POIs are drawn as markers (always the full pipeline). */
  readonly data = input<AnalyzeResponse | null>(null);
  /** Response of the pipeline currently shown (full or base): used only to explain and recentre
   * on a zero-POI result, which must work in Base mode too (#488). */
  readonly activeResponse = input<AnalyzeResponse | null>(null);
  /** False outside the search-form states (results/loading/error): a map click must not start a
   * new circle there (#492). Bound by the shell. */
  readonly drawingEnabled = input(true);
  readonly filter = input<Confidence | null>(null);
  readonly selectedId = input<string | null>(null);
  readonly poiClick = output<string>();
  readonly circleChange = output<{ lat: number; lon: number; radiusM: number } | null>();

  protected readonly MIN_RADIUS_M = MIN_RADIUS_M;
  protected readonly MAX_RADIUS_M = MAX_RADIUS_M;

  private readonly mapEl = viewChild.required<ElementRef<HTMLElement>>('mapEl');
  private map: L.Map | null = null;
  private markers: L.LayerGroup | null = null;
  private readonly poiMarkers = new Map<
    string,
    { marker: L.Marker; poi: Poi; n: number; label: string; key: string }
  >();

  /**
   * Signals (not plain fields) on purpose: `drawState`/`radiusM` are read by the template
   * (`showRadiusInput`/`[value]` of the input, #318) and updates come from native Leaflet
   * handlers (`map.on(...)`), not from `(event)` bindings in the template — only a signal, not a private
   * field, redraws the OnPush view in that case.
   */
  /**
   * Derived from the response so the effects below depend on the POI list / zone, NOT on the whole
   * response object (#492): the zone narrative arriving replaces `fullData` with a new object that
   * carries the same `poi` array, and that must not make the map flyTo/redraw again.
   */
  private readonly pois = computed<Poi[]>(() => this.data()?.poi ?? []);
  private readonly zeroPoiZone = computed<GeoZone | null>(() => {
    const r = this.activeResponse();
    return r && r.poi.length === 0 ? (r.zona_geo ?? null) : null;
  });
  protected readonly zeroPoiMessage = computed<string | null>(() => {
    const r = this.activeResponse();
    return r && r.poi.length === 0 ? (r.messaggio ?? null) : null;
  });

  protected readonly drawState = signal<DrawState>('idle');
  private circleLayer: L.Circle | null = null;
  private centerLatLng: { lat: number; lon: number } | null = null;

  /** Current radius of the circle being drawn/confirmed, for the two-way synchronization with
   * the numeric input (#318 D2): dragging updates it (and reflects it in the field), typing
   * updates it only on confirmation (`change` event: blur/enter, see {@link onRadiusChange}) — not on
   * every keystroke (see {@link onRadiusInput}), otherwise the `[value]` bound to this signal
   * would rewrite the field while the user is still composing a number. */
  protected readonly radiusM = signal<number>(DEFAULT_RADIUS_M);
  /** The numeric input is useful only while a circle exists (`drawing-radius`/`ready`): in `idle`
   * there is no center yet to apply a radius to. */
  protected readonly showRadiusInput = computed(() => this.drawState() !== 'idle');

  constructor() {
    afterNextRender(() => {
      // doubleClickZoom:false (review finding fix): Leaflet emits TWO native `click` events
      // before the `dblclick` on every double click. The draw FSM of this component (see
      // {@link onMapClick}) reads every `click` as a step idle->drawing-radius->ready (or
      // ready->new center): without disabling the default double-click zoom here, a
      // double click made to zoom (no intention of redrawing) was silently
      // interpreted as two FSM clicks, discarding an already confirmed circle
      // (`circleChange(null)`) and replacing it with a new one at default radius at the point where
      // the user only wanted to zoom.
      const map = L.map(this.mapEl().nativeElement, {
        zoomControl: false,
        doubleClickZoom: false,
      }).setView([41.9028, 12.4964], 12);
      // Basemap: standard OpenStreetMap tiles, no key.
      //
      // We came from CARTO (`basemaps.cartocdn.com/rastertiles/voyager`), which started
      // requiring an API key: the request keeps answering HTTP 200 with `image/png`, but the
      // body is an "API KEY REQUIRED" placeholder of ~2 KB instead of a real tile of ~14 KB. Since
      // it is not a 4xx, Leaflet does not emit `tileerror` and the console stays clean: the map ends up
      // empty without a single error signal. It holds for all the styles of their CDN, not just
      // Voyager, so it was not a matter of style but of access.
      //
      // No `{s}`: OSM has deprecated the subdomains (a single host over HTTP/2 is the recommended way, and
      // passing them makes Leaflet log a warning). No `{r}`: the standard tiles have no
      // retina @2x variant, and asking for it would give 404.
      //
      // DECLARED LIMIT: OSM's tile usage policy covers light uses — development, demo, thesis —
      // not a high-volume service. A real deployment requires a dedicated provider (or self-hosted
      // tiles), not this endpoint.
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution:
          'Dati e tile © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors (<a href="https://opendatacommons.org/licenses/odbl/1-0/" target="_blank" rel="noopener noreferrer">ODbL</a>) · ' +
          'Geocoding: <a href="https://nominatim.org/" target="_blank" rel="noopener noreferrer">Nominatim</a>',
      }).addTo(map);
      L.control.zoom({ position: 'bottomright' }).addTo(map);
      this.markers = L.layerGroup().addTo(map);
      map.on('click', (e: L.LeafletMouseEvent) => this.onMapClick(e));
      map.on('mousemove', (e: L.LeafletMouseEvent) => this.onMapMouseMove(e));
      this.map = map;
    });

    effect(() => {
      const pois = this.pois();
      const map = this.map;
      if (!map || pois.length === 0) return;
      const bounds = L.latLngBounds(pois.map((p) => [p.lat, p.lon] as [number, number]));
      map.flyToBounds(bounds, { padding: [40, 40] });
    });

    // Zero POI (#488): without this the map stayed still and the user could not tell an empty
    // zone from a mistyped one. Recentre on the geocoded zone.
    effect(() => {
      const zone = this.zeroPoiZone();
      const map = this.map;
      if (!map || !zone) return;
      const bounds = L.latLngBounds([
        [zone.bbox_min_lat, zone.bbox_min_lon],
        [zone.bbox_max_lat, zone.bbox_max_lon],
      ]);
      map.flyToBounds(bounds, { padding: [40, 40] });
    });

    // Structure effect: (re)creates the markers only when the POI list changes (#492). Filter and
    // selection are read untracked here; the restyle effect below applies them.
    effect(() => {
      const pois = this.pois();
      const layer = this.markers;
      if (!layer) return;
      const filter = untracked(() => this.filter());
      const selectedId = untracked(() => this.selectedId());

      layer.clearLayers();
      this.poiMarkers.clear();

      pois.forEach((poi, index) => {
        const n = index + 1;
        // title+alt give the marker its accessible name (#493): Leaflet makes divIcon markers
        // focusable (keyboard:true) and Enter fires `click`, but without a name they read as an
        // unlabeled button.
        const label = `${n}. ${poi.name || poi.ontology_label_it}`;
        const marker = L.marker([poi.lat, poi.lon], {
          icon: this.pinIcon(poi, n, filter, selectedId),
          title: label,
        }).addTo(layer);
        this.labelMarker(marker, label);
        marker.bindPopup(poiPopupHTML(poi, n));
        marker.on('click', () => this.poiClick.emit(poi.id));
        this.poiMarkers.set(poi.id, {
          marker,
          poi,
          n,
          label,
          key: this.styleKey(poi, filter, selectedId),
        });
      });
    });

    // Restyle effect (#492): a selection/filter change only swaps the icon of the markers whose
    // style actually changed, instead of recreating every marker.
    effect(() => {
      const filter = this.filter();
      const selectedId = this.selectedId();
      for (const entry of this.poiMarkers.values()) {
        const key = this.styleKey(entry.poi, filter, selectedId);
        if (key === entry.key) continue;
        entry.key = key;
        // setIcon recreates the marker DOM element: restore the accessible name and, if the old
        // element held the keyboard focus, move it to the new one (#493).
        const hadFocus =
          !!entry.marker.getElement() && document.activeElement === entry.marker.getElement();
        entry.marker.setIcon(this.pinIcon(entry.poi, entry.n, filter, selectedId));
        this.labelMarker(entry.marker, entry.label);
        if (hadFocus) entry.marker.getElement()?.focus();
      }
    });
  }

  /** Leaflet ignores `alt` on divIcons and the visible number would otherwise be the name, so the
   * accessible name is set explicitly as `aria-label` on the marker element (#493). */
  private labelMarker(marker: L.Marker, label: string): void {
    marker.getElement()?.setAttribute('aria-label', label);
  }

  private styleKey(poi: Poi, filter: Confidence | null, selectedId: string | null): string {
    return `${matchesFilter(poi.confidence, filter)}|${poi.id === selectedId}`;
  }

  private pinIcon(
    poi: Poi,
    n: number,
    filter: Confidence | null,
    selectedId: string | null,
  ): L.DivIcon {
    const dim = !matchesFilter(poi.confidence, filter);
    const focus = poi.id === selectedId;
    const size = focus ? 34 : 26;
    return L.divIcon({
      html: pinHTML(n, poi.confidence, { focus, dim }),
      className: 'cra-poi-pin',
      iconSize: [size, size],
      iconAnchor: [size / 2, size],
    });
  }

  private onMapClick(e: L.LeafletMouseEvent): void {
    if (!this.drawingEnabled()) return;
    const { lat, lng } = e.latlng;
    if (this.drawState() === 'drawing-radius') {
      this.confirmCircle();
      return;
    }
    this.startCircle(lat, lng);
  }

  /** idle/ready -> drawing-radius on a new center. */
  private startCircle(lat: number, lon: number): void {
    // ready -> new center: the previously confirmed circle is no longer valid.
    if (this.drawState() === 'ready') this.circleChange.emit(null);
    this.centerLatLng = { lat, lon };
    this.circleLayer?.remove();
    this.circleLayer = L.circle([lat, lon], { radius: DEFAULT_RADIUS_M }).addTo(this.map!);
    this.radiusM.set(DEFAULT_RADIUS_M);
    this.drawState.set('drawing-radius');
  }

  /** Keyboard equivalent of the first map click: the circle is centered on the map view. */
  protected drawAtCenter(): void {
    if (!this.map || !this.drawingEnabled()) return;
    const { lat, lng } = this.map.getCenter();
    this.startCircle(lat, lng);
  }

  /** drawing-radius -> ready: confirms the current radius (second click, or the confirm button). */
  protected confirmCircle(): void {
    if (!this.centerLatLng || !this.circleLayer) return;
    this.drawState.set('ready');
    this.circleChange.emit({
      lat: this.centerLatLng.lat,
      lon: this.centerLatLng.lon,
      radiusM: this.circleLayer.getRadius(),
    });
  }

  private onMapMouseMove(e: L.LeafletMouseEvent): void {
    if (!this.drawingEnabled()) return;
    if (this.drawState() !== 'drawing-radius' || !this.centerLatLng || !this.circleLayer) return;
    const radius = this.map!.distance(
      [this.centerLatLng.lat, this.centerLatLng.lon],
      [e.latlng.lat, e.latlng.lng],
    );
    const clamped = this.clampRadius(radius);
    this.circleLayer.setRadius(clamped);
    this.radiusM.set(clamped);
  }

  /**
   * Keyboard synchronization, TYPING phase (#318 D2, review finding fix "clamps and rewrites
   * at every keystroke"): with `[value]="radiusM()"` in the template, calling `radiusM.set(...)` here
   * would rewrite the field at every character — "8" would be clamped to "150" before the
   * user can even type "800", which would therefore NEVER be reachable. For this reason here
   * `radiusM` is never touched (nor is the field rewritten): only the map/circle-side PREVIEW is
   * updated (same clamp as the drag, via {@link clampRadius}) when the typed text is
   * already a number — an out-of-range value still immediately updates the map/`circleChange` (if
   * `ready`), but with the DISPLAYED one unchanged. The empty field (user in the middle of a
   * rewrite) does not even touch the preview. The authoritative clamp, which also rewrites the
   * field, happens only on confirmation: see {@link onRadiusChange}.
   */
  protected onRadiusInput(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    if (value.trim() === '') return;
    const raw = Number(value);
    if (!Number.isFinite(raw)) return;
    const clamped = this.clampRadius(raw);
    this.circleLayer?.setRadius(clamped);
    if (this.drawState() === 'ready' && this.centerLatLng) {
      this.circleChange.emit({
        lat: this.centerLatLng.lat,
        lon: this.centerLatLng.lon,
        radiusM: clamped,
      });
    }
  }

  /**
   * Keyboard synchronization, CONFIRMATION phase (`change` event: blur or enter, #318 D2 fix): here,
   * and only here, the value is clamped AND rewritten into the field (`radiusM.set(...)`, which through
   * `[value]` overwrites the typed text) — the user has finished composing the number, so
   * aligning the view to the effective value no longer prevents them from reaching an
   * intermediate value as during typing (see {@link onRadiusInput}).
   *
   * Field emptied completely on confirmation (review finding fix): `Number('') === 0`, which is
   * finite (not `NaN`), so without this guard `clampRadius(0)` would silently jump
   * to the minimum (150m) — discarding a valid radius already confirmed (e.g. 800m) instead of restoring it.
   * Same guard already present in {@link onRadiusInput} for the identical case during typing
   * (`value.trim() === ''`): here we start again from `this.radiusM()`, the last known-good value, instead of
   * letting `raw` (0) fall into the clamp.
   *
   * `target.value` is rewritten here explicitly, not only via `radiusM.set(...)` + `[value]`:
   * Angular signals skip the notification if the new value equals the previous one (`Object.is`),
   * so when the restoration above brings `clamped` back to the same value already in `radiusM()` (common
   * case: an already-800 field is emptied and confirmed) `[value]` alone would not redraw the
   * field, which would stay visually empty despite having the correct logical state.
   */
  protected onRadiusChange(event: Event): void {
    const target = event.target as HTMLInputElement;
    const value = target.value;
    const raw = Number(value);
    const clamped =
      value.trim() === ''
        ? this.radiusM()
        : this.clampRadius(Number.isFinite(raw) ? raw : this.radiusM());
    this.radiusM.set(clamped);
    target.value = String(clamped);
    this.circleLayer?.setRadius(clamped);
    if (this.drawState() === 'ready' && this.centerLatLng) {
      this.circleChange.emit({
        lat: this.centerLatLng.lat,
        lon: this.centerLatLng.lon,
        radiusM: clamped,
      });
    }
  }

  private clampRadius(value: number): number {
    return Math.min(Math.max(value, MIN_RADIUS_M), MAX_RADIUS_M);
  }

  /** Called by the "go to a place" box (#318): moves the map, does not touch the drawn circle. */
  flyTo(lat: number, lon: number): void {
    this.map?.flyTo([lat, lon], 14);
  }

  /**
   * Clears the drawn circle (#318, review finding I5): called by `App.onResetConfirmed()`
   * after "+ Nuova richiesta". Without this method `MapComponent` had no way to know that the
   * shell cleared its own `circle` signal — the circle stayed drawn on the map
   * (`circleLayer` untouched) while the rest of the UI (disabled button, instruction
   * "disegna un cerchio") implied there was none. It brings the state back to `idle` (not
   * `ready` with a `null` emitted): the next click must restart from a new center, not
   * reconfirm/discard the one just removed.
   */
  clearCircle(): void {
    this.circleLayer?.remove();
    this.circleLayer = null;
    this.centerLatLng = null;
    this.drawState.set('idle');
    this.radiusM.set(DEFAULT_RADIUS_M);
  }

  ngOnDestroy(): void {
    this.markers?.clearLayers();
    this.circleLayer?.remove();
    this.map?.remove();
    this.map = null;
    this.markers = null;
    this.circleLayer = null;
  }
}
