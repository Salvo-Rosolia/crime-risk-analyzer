import {
  afterNextRender,
  ChangeDetectionStrategy,
  Component,
  effect,
  ElementRef,
  input,
  OnDestroy,
  viewChild,
} from '@angular/core';
import * as L from 'leaflet';
import type { AnalyzeResponse } from '@core/models/models';

@Component({
  selector: 'cra-map',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<div #mapEl class="cra-map"></div>`,
  styles: [`.cra-map { position: absolute; inset: 0; height: 100%; width: 100%; }`],
})
export class MapComponent implements OnDestroy {
  readonly data = input<AnalyzeResponse | null>(null);

  private readonly mapEl = viewChild.required<ElementRef<HTMLElement>>('mapEl');
  private map: L.Map | null = null;

  constructor() {
    afterNextRender(() => {
      const map = L.map(this.mapEl().nativeElement, { zoomControl: false }).setView(
        [41.9028, 12.4964],
        12,
      );
      L.tileLayer(
        'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
        { subdomains: 'abcd', maxZoom: 19, attribution: '© OpenStreetMap © CARTO' },
      ).addTo(map);
      L.control.zoom({ position: 'bottomright' }).addTo(map);
      this.map = map;
    });

    effect(() => {
      const d = this.data();
      const map = this.map;
      if (!map || !d || d.poi.length === 0) return;
      const bounds = L.latLngBounds(d.poi.map((p) => [p.lat, p.lon] as [number, number]));
      map.flyToBounds(bounds, { padding: [40, 40] });
    });
  }

  ngOnDestroy(): void {
    this.map?.remove();
    this.map = null;
  }
}
