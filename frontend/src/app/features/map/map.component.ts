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
  viewChild,
} from '@angular/core';
import * as L from 'leaflet';
import type { AnalyzeResponse, Confidence } from '@core/models/models';
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
    @if (showRadiusInput()) {
      <div class="cra-radius-control">
        <label for="cra-radius-input">Raggio (m)</label>
        <input
          id="cra-radius-input"
          type="number"
          [min]="MIN_RADIUS_M"
          [max]="MAX_RADIUS_M"
          [value]="radiusM()"
          (input)="onRadiusInput($event)"
        />
      </div>
    }
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
       * Input numerico del raggio (#318, D2/§5.1 design doc): l'unica via KEYBOARD/screen-reader
       * per impostare il raggio, il drag da solo la esclude. Fluttua sopra la mappa (in alto a
       * sinistra, lontano dal controllo zoom in basso a destra) invece di stare in un pannello
       * laterale perché deve restare visibile in drawing-radius/ready indipendentemente da quale
       * pannello di ricerca (completo/base) è montato accanto alla mappa.
       */
      .cra-radius-control {
        position: absolute;
        top: 12px;
        left: 12px;
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
  readonly data = input<AnalyzeResponse | null>(null);
  readonly filter = input<Confidence | null>(null);
  readonly selectedId = input<string | null>(null);
  readonly poiClick = output<string>();
  readonly circleChange = output<{ lat: number; lon: number; radiusM: number } | null>();

  protected readonly MIN_RADIUS_M = MIN_RADIUS_M;
  protected readonly MAX_RADIUS_M = MAX_RADIUS_M;

  private readonly mapEl = viewChild.required<ElementRef<HTMLElement>>('mapEl');
  private map: L.Map | null = null;
  private markers: L.LayerGroup | null = null;

  /**
   * Segnali (non semplici campi) apposta: `drawState`/`radiusM` sono letti dal template
   * (`showRadiusInput`/`[value]` dell'input, #318) e gli aggiornamenti arrivano da handler Leaflet
   * nativi (`map.on(...)`), non da binding `(evento)` del template — solo un segnale, non un campo
   * privato, ridisegna la vista OnPush in quel caso.
   */
  private readonly drawState = signal<DrawState>('idle');
  private circleLayer: L.Circle | null = null;
  private centerLatLng: { lat: number; lon: number } | null = null;

  /** Raggio corrente del cerchio in disegno/confermato, per la sincronizzazione bidirezionale con
   * l'input numerico (#318 D2): il drag lo aggiorna, digitare un valore aggiorna a sua volta il
   * cerchio disegnato (vedi {@link onRadiusInput}). */
  protected readonly radiusM = signal<number>(DEFAULT_RADIUS_M);
  /** L'input numerico è utile solo mentre un cerchio esiste (`drawing-radius`/`ready`): in `idle`
   * non c'è ancora un centro su cui applicare un raggio. */
  protected readonly showRadiusInput = computed(() => this.drawState() !== 'idle');

  constructor() {
    afterNextRender(() => {
      const map = L.map(this.mapEl().nativeElement, { zoomControl: false }).setView(
        [41.9028, 12.4964],
        12,
      );
      L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
        subdomains: 'abcd',
        maxZoom: 19,
        attribution:
          'Dati © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors (<a href="https://opendatacommons.org/licenses/odbl/1-0/" target="_blank" rel="noopener noreferrer">ODbL</a>) · ' +
          'Tile © <a href="https://carto.com/attributions" target="_blank" rel="noopener noreferrer">CARTO</a> · ' +
          'Geocoding: <a href="https://nominatim.org/" target="_blank" rel="noopener noreferrer">Nominatim</a>',
      }).addTo(map);
      L.control.zoom({ position: 'bottomright' }).addTo(map);
      this.markers = L.layerGroup().addTo(map);
      map.on('click', (e: L.LeafletMouseEvent) => this.onMapClick(e));
      map.on('mousemove', (e: L.LeafletMouseEvent) => this.onMapMouseMove(e));
      this.map = map;
    });

    effect(() => {
      const d = this.data();
      const map = this.map;
      if (!map || !d || d.poi.length === 0) return;
      const bounds = L.latLngBounds(d.poi.map((p) => [p.lat, p.lon] as [number, number]));
      map.flyToBounds(bounds, { padding: [40, 40] });
    });

    effect(() => {
      const d = this.data();
      const filter = this.filter();
      const selectedId = this.selectedId();
      const layer = this.markers;
      if (!layer) return;

      layer.clearLayers();
      if (!d) return;

      d.poi.forEach((poi, index) => {
        const n = index + 1;
        const dim = !matchesFilter(poi.confidence, filter);
        const focus = poi.id === selectedId;
        const size = focus ? 34 : 26;
        const icon = L.divIcon({
          html: pinHTML(n, poi.confidence, { focus, dim }),
          className: 'cra-poi-pin',
          iconSize: [size, size],
          iconAnchor: [size / 2, size],
        });
        const marker = L.marker([poi.lat, poi.lon], { icon }).addTo(layer);
        marker.bindPopup(poiPopupHTML(poi, n));
        marker.on('click', () => this.poiClick.emit(poi.id));
      });
    });
  }

  private onMapClick(e: L.LeafletMouseEvent): void {
    const { lat, lng } = e.latlng;
    if (this.drawState() === 'idle' || this.drawState() === 'ready') {
      // ready -> nuovo centro: il cerchio confermato in precedenza non è più valido.
      if (this.drawState() === 'ready') this.circleChange.emit(null);
      this.centerLatLng = { lat, lon: lng };
      this.circleLayer?.remove();
      this.circleLayer = L.circle([lat, lng], { radius: DEFAULT_RADIUS_M }).addTo(this.map!);
      this.radiusM.set(DEFAULT_RADIUS_M);
      this.drawState.set('drawing-radius');
      return;
    }
    // drawing-radius -> ready: conferma il raggio corrente.
    if (this.centerLatLng && this.circleLayer) {
      this.drawState.set('ready');
      this.circleChange.emit({
        lat: this.centerLatLng.lat,
        lon: this.centerLatLng.lon,
        radiusM: this.circleLayer.getRadius(),
      });
    }
  }

  private onMapMouseMove(e: L.LeafletMouseEvent): void {
    if (this.drawState() !== 'drawing-radius' || !this.centerLatLng || !this.circleLayer) return;
    const radius = this.map!.distance(
      [this.centerLatLng.lat, this.centerLatLng.lon],
      [e.latlng.lat, e.latlng.lng],
    );
    const clamped = Math.min(Math.max(radius, MIN_RADIUS_M), MAX_RADIUS_M);
    this.circleLayer.setRadius(clamped);
    this.radiusM.set(clamped);
  }

  /**
   * Sincronizzazione bidirezionale lato tastiera (#318 D2): un valore digitato aggiorna subito il
   * cerchio disegnato (stesso clamp del drag, stesse costanti `MIN_RADIUS_M`/`MAX_RADIUS_M`) e, se
   * il cerchio è già `ready` (confermato), ri-emette `circleChange` — altrimenti un aggiustamento
   * manuale del raggio dopo la conferma non raggiungerebbe mai il segnale `circle` dello shell.
   * In `drawing-radius` (non ancora confermato) basta aggiornare il layer: la conferma successiva
   * (secondo clic) leggerà il nuovo raggio da `circleLayer.getRadius()`.
   */
  protected onRadiusInput(event: Event): void {
    const raw = Number((event.target as HTMLInputElement).value);
    if (Number.isNaN(raw)) return;
    const clamped = Math.min(Math.max(raw, MIN_RADIUS_M), MAX_RADIUS_M);
    this.radiusM.set(clamped);
    this.circleLayer?.setRadius(clamped);
    if (this.drawState() === 'ready' && this.centerLatLng) {
      this.circleChange.emit({
        lat: this.centerLatLng.lat,
        lon: this.centerLatLng.lon,
        radiusM: clamped,
      });
    }
  }

  /** Chiamato dalla casella "vai a un luogo" (#318): sposta la mappa, non tocca il cerchio disegnato. */
  flyTo(lat: number, lon: number): void {
    this.map?.flyTo([lat, lon], 14);
  }

  /**
   * Azzera il cerchio disegnato (#318, reperto review I5): chiamato da `App.onResetConfirmed()`
   * dopo "+ Nuova richiesta". Senza questo metodo `MapComponent` non aveva modo di sapere che lo
   * shell ha azzerato il proprio segnale `circle` — il cerchio restava disegnato sulla mappa
   * (`circleLayer` non toccato) mentre il resto della UI (bottone disabilitato, istruzione
   * "disegna un cerchio") lasciava intendere che non ce n'era uno. Riporta lo stato a `idle` (non
   * `ready` con un `null` emesso): il prossimo clic deve ripartire da un centro nuovo, non
   * riconfermare/scartare quello appena rimosso.
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
