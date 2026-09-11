import {
  afterNextRender,
  ChangeDetectionStrategy,
  Component,
  effect,
  ElementRef,
  input,
  OnDestroy,
  output,
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
  template: `<div #mapEl class="cra-map"></div>`,
  styles: [
    `
      .cra-map {
        position: absolute;
        inset: 0;
        height: 100%;
        width: 100%;
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

  private readonly mapEl = viewChild.required<ElementRef<HTMLElement>>('mapEl');
  private map: L.Map | null = null;
  private markers: L.LayerGroup | null = null;

  private drawState: DrawState = 'idle';
  private circleLayer: L.Circle | null = null;
  private centerLatLng: { lat: number; lon: number } | null = null;

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
    if (this.drawState === 'idle' || this.drawState === 'ready') {
      // ready -> nuovo centro: il cerchio confermato in precedenza non è più valido.
      if (this.drawState === 'ready') this.circleChange.emit(null);
      this.centerLatLng = { lat, lon: lng };
      this.circleLayer?.remove();
      this.circleLayer = L.circle([lat, lng], { radius: DEFAULT_RADIUS_M }).addTo(this.map!);
      this.drawState = 'drawing-radius';
      return;
    }
    // drawing-radius -> ready: conferma il raggio corrente.
    if (this.centerLatLng && this.circleLayer) {
      this.drawState = 'ready';
      this.circleChange.emit({
        lat: this.centerLatLng.lat,
        lon: this.centerLatLng.lon,
        radiusM: this.circleLayer.getRadius(),
      });
    }
  }

  private onMapMouseMove(e: L.LeafletMouseEvent): void {
    if (this.drawState !== 'drawing-radius' || !this.centerLatLng || !this.circleLayer) return;
    const radius = this.map!.distance(
      [this.centerLatLng.lat, this.centerLatLng.lon],
      [e.latlng.lat, e.latlng.lng],
    );
    const clamped = Math.min(Math.max(radius, MIN_RADIUS_M), MAX_RADIUS_M);
    this.circleLayer.setRadius(clamped);
  }

  /** Chiamato dalla casella "vai a un luogo" (#318): sposta la mappa, non tocca il cerchio disegnato. */
  flyTo(lat: number, lon: number): void {
    this.map?.flyTo([lat, lon], 14);
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
