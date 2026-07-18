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

  private readonly mapEl = viewChild.required<ElementRef<HTMLElement>>('mapEl');
  private map: L.Map | null = null;
  private markers: L.LayerGroup | null = null;

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

  ngOnDestroy(): void {
    this.markers?.clearLayers();
    this.map?.remove();
    this.map = null;
    this.markers = null;
  }
}
