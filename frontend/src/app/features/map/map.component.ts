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
          (change)="onRadiusChange($event)"
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
       * per impostare il raggio, il drag da solo la esclude. Fluttua sopra la mappa invece di
       * stare in un pannello laterale perché deve restare visibile in drawing-radius/ready
       * indipendentemente da quale pannello di ricerca (completo/base) è montato accanto alla
       * mappa.
       *
       * Posizione (fix reperto review: non più in alto a sinistra, era invisibile/incliccabile
       * ovunque). .cra-panels (app.css) è z-index:500 nello stacking context ROOT, quindi sta
       * sempre sopra cra-map (z-index:0): qualunque pannello dentro .cra-panels copre questo
       * controllo, indipendentemente da z-index/posizione LOCALI qui dentro. Angolo per angolo:
       *  - alto-sinistra: SEMPRE occupato - .cra-panel in INPUT/ERROR (app.css, margin:16px) e
       *    il dock POI in RESULTS/FILTER/DETAIL (panel-dock.component.css, top/left:
       *    var(--space-4), width fissa var(--panel-max-width)) partono entrambi da lì.
       *  - basso-destra: SEMPRE occupato dal controllo zoom di Leaflet - zoomControl:false in
       *    L.map(...) (questo file) disattiva solo quello di default, ma poco dopo viene
       *    riaggiunto a mano con L.control.zoom({ position: 'bottomright' }), quindi un
       *    controllo zoom esiste per davvero a quell'angolo; in più, a layout largo, ci finisce
       *    sopra anche il pannello narrativa (narrative-sheet.component.css, top/right/bottom:
       *    var(--space-4), quindi a tutta altezza).
       *  - basso-sinistra: NON sicuro nonostante sembri libero - il dock POI ha solo un
       *    max-height (non un'altezza fissa) e con una lista piena arriva quasi in fondo; sotto
       *    i 1100px la narrativa diventa un bottom-sheet a piena larghezza (stessa
       *    narrative-sheet.component.css) e occupa anche quell'angolo quando aperta.
       *  - alto, subito a destra del dock/pannello: libero in ogni schermata. Il dock/.cra-panel
       *    hanno larghezza FISSA (var(--panel-max-width), mai di più anche a lista piena - solo
       *    l'altezza cresce col contenuto), e la narrativa (quando presente, a layout largo) parte
       *    da destra con la sua stessa larghezza fissa: resta quindi un corridoio verticale libero
       *    fra i due, dove l'ancoraggio orizzontale sotto riusa var(--panel-max-width) invece di un
       *    valore fisso in px per restare corretto se quella costante cambia.
       */
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
   * l'input numerico (#318 D2): il drag lo aggiorna (e lo riflette nel campo), la digitazione lo
   * aggiorna solo alla conferma (evento `change`: blur/invio, vedi {@link onRadiusChange}) — non ad
   * ogni tasto (vedi {@link onRadiusInput}), altrimenti il `[value]` legato a questo segnale
   * riscriverebbe il campo mentre l'utente sta ancora componendo un numero. */
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
    const clamped = this.clampRadius(radius);
    this.circleLayer.setRadius(clamped);
    this.radiusM.set(clamped);
  }

  /**
   * Sincronizzazione da tastiera, fase DIGITAZIONE (#318 D2, fix reperto review "clampa e riscrive
   * ad ogni tasto"): con `[value]="radiusM()"` nel template, chiamare `radiusM.set(...)` qui
   * riscriverebbe il campo ad ogni carattere — "8" verrebbe clampato a "150" prima ancora che
   * l'utente possa scrivere "800", che quindi non sarebbe MAI raggiungibile. Per questo qui non si
   * tocca mai `radiusM` (né si riscrive il campo): si aggiorna solo l'ANTEPRIMA lato
   * mappa/cerchio (stesso clamp del drag, tramite {@link clampRadius}) quando il testo digitato è
   * già un numero — un valore fuori range aggiorna comunque subito mappa/`circleChange` (se
   * `ready`), ma con quello VISUALIZZATO invariato. Il campo vuoto (utente a metà di una
   * riscrittura) non tocca nemmeno l'anteprima. Il clamp autoritativo, che riscrive anche il
   * campo, avviene solo alla conferma: vedi {@link onRadiusChange}.
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
   * Sincronizzazione da tastiera, fase CONFERMA (evento `change`: blur o invio, #318 D2 fix): qui,
   * e solo qui, il valore viene clampato E riscritto nel campo (`radiusM.set(...)`, che tramite
   * `[value]` sovrascrive il testo digitato) — l'utente ha finito di comporre il numero, quindi
   * allineare la vista al valore effettivo non gli impedisce più di raggiungere un valore
   * intermedio come durante la digitazione (vedi {@link onRadiusInput}).
   */
  protected onRadiusChange(event: Event): void {
    const raw = Number((event.target as HTMLInputElement).value);
    const clamped = this.clampRadius(Number.isFinite(raw) ? raw : this.radiusM());
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

  private clampRadius(value: number): number {
    return Math.min(Math.max(value, MIN_RADIUS_M), MAX_RADIUS_M);
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
