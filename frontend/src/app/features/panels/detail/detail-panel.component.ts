import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  effect,
  inject,
  input,
  linkedSignal,
  output,
} from '@angular/core';
import { confMeta, pinColor, srcTagMeta } from '@core/confidence';
import { Poi, RiskModel } from '@core/models/models';
import {
  buildDetailModel,
  hazardDisplayLabel,
  ontologyDisplayLabel,
  orderGroupsByTag,
} from '@core/ui-helpers';

/**
 * Scheda "Dettaglio POI" (Stato C, spec-frontend.md §Stato C): citazione SPARQL lineare
 * (Classe → proprietà → entità) + fattori di rischio raggruppati per tag fonte, nell'ordine
 * ONTOLOGIA → CONTESTO → SPECULATIVO. Componente "thin": consuma gli helper puri già testati
 * (`buildDetailModel`, `orderGroupsByTag`) senza reimplementarne la logica.
 *
 * Focus management (a11y, richiesto da frontend-dev.md/reviewer-frontend.md — review #67,
 * non-bloccante #8): il pannello stesso è il target del focus programmatico (`tabindex="-1"`,
 * non nel tab order naturale) — niente wrapper aggiuntivo nel template. L'`effect()` dipende da
 * `poi()`, quindi rifocalizza sia all'apertura sia passando da un POI all'altro senza richiudere
 * (lo `@if` dello shell non rimonta il componente in quel caso, solo gli input cambiano).
 */
@Component({
  selector: 'cra-detail-panel',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './detail-panel.component.html',
  styleUrl: './detail-panel.component.css',
  host: {
    tabindex: '-1',
    role: 'region',
    '[attr.aria-label]': 'panelAriaLabel()',
  },
})
export class DetailPanelComponent {
  readonly poi = input.required<Poi>();
  /** Posizione del POI nell'array `store.completoData()?.poi` (+1): stesso numero del pin/card accoppiati. */
  readonly number = input.required<number>();
  readonly riskModels = input<RiskModel[]>([]);

  readonly closeDetail = output<void>();

  private readonly elementRef = inject(ElementRef<HTMLElement>);

  /**
   * Accesso difensivo alla confidence (story #207/#220, fix-review): un valore fuori contratto
   * (mismatch di migrazione, dato legacy) o `null` (POI fuori ontologia, #220) degrada a un
   * placeholder — pin neutro sul `.cra-detail-pin` (sempre renderizzato) — invece di far
   * collassare la vista in un TypeError di change detection — `conf[livello]` indicizzato
   * direttamente sarebbe `undefined`. Il badge testuale dell'header (`.cra-badge-confidence`)
   * viene invece OMESSO del tutto per un POI `null` (nessun badge, template), non degradato al
   * placeholder "Sconosciuto": quel fallback resta per i soli valori fuori contratto. `pinColor`
   * per il colore, `confMeta` per dot/label: stesso pattern difensivo già usato altrove in
   * `core/confidence.ts`.
   */
  protected readonly pinColor = pinColor;
  protected readonly confMeta = confMeta;
  protected readonly hazardLabel = hazardDisplayLabel;

  protected readonly detailModel = computed(() => buildDetailModel(this.poi(), this.riskModels()));
  protected readonly orderedGroups = computed(() => orderGroupsByTag(this.detailModel().groups));
  protected readonly srcMeta = srcTagMeta;
  protected readonly panelAriaLabel = computed(() => `Dettaglio POI: ${this.poi().name}`);

  protected readonly axisLabel = ontologyDisplayLabel;

  /**
   * Gli assi TERMINUS oltre agli hazard (#256), pronti per il template: solo quelli non vuoti,
   * nell'ordine in cui l'executor SPARQL li interroga. Sono elenchi qualitativi con la propria
   * citazione: nessun conteggio presentato come misura e nessuna gradazione per voce, perché la
   * forza probatoria è un bit derivato dal nome del POI e vale identica per ogni sua asserzione
   * ontologica — il badge in testa al pannello la dichiara una volta per tutte.
   *
   * Caso limite dichiarato: un POI senza hazard ha `confidence: null` (#220 — «nessun rischio da
   * qualificare», non «ignoto») e quindi NESSUN badge, ma può avere gli altri tre assi popolati,
   * perché vengono da property OWL indipendenti. Lì le voci restano nude: sono fatti sulla classe
   * TERMINUS, veri quanto il mapping del POI, e non c'è un livello da ereditare.
   */
  protected readonly ontologyAxes = computed(() => {
    const poi = this.poi();
    return [
      { titolo: 'Eventi critici', voci: poi.critical_events ?? [] },
      { titolo: 'Vulnerabilità', voci: poi.vulnerabilities ?? [] },
    ].filter((asse) => asse.voci.length > 0);
  });

  /**
   * Soglia dell'accordion adattivo (rework UI): con pochi fattori totali i gruppi-fonte partono
   * tutti aperti (nessun attrito); oltre soglia resta aperto solo il gruppo più affidabile presente
   * (ONTOLOGIA è primo in `orderGroupsByTag`) e gli altri si collassano, ma sempre col conteggio
   * visibile — così si tuck il meno-certo, non il verificato.
   */
  private static readonly ADAPTIVE_OPEN_THRESHOLD = 3;

  /**
   * Tag dei gruppi-fonte attualmente espansi. `linkedSignal` (non `signal`) perché lo stato di
   * apertura deve RESETTARSI al default adattivo quando cambia il POI selezionato — il componente
   * non si rimonta navigando tra POI, cambia solo `poi()` (vedi l'effect di focus sotto) — pur
   * restando modificabile dai click dell'utente sullo stesso POI. La chiave di reset è `poi().id`
   * (identità del POI); da notare che `computation` legge anche `orderedGroups()` (che dipende da
   * `riskModels()`), quindi in teoria pure un cambio di riferimento dei risk_models a parità di POI
   * resetterebbe i toggle — oggi non raggiungibile perché `transition.ts` azzera `selectedPoiId`
   * (smontando questa vista) ogni volta che i dati potrebbero cambiare.
   */
  protected readonly openTags = linkedSignal<string, Set<string>>({
    source: () => this.poi().id,
    computation: () => {
      const groups = this.orderedGroups();
      const total = groups.reduce((n, g) => n + g.risks.length, 0);
      const openAll = total <= DetailPanelComponent.ADAPTIVE_OPEN_THRESHOLD;
      return new Set((openAll ? groups : groups.slice(0, 1)).map((g) => g.tag));
    },
  });

  protected isOpen(tag: string): boolean {
    return this.openTags().has(tag);
  }

  protected toggleGroup(tag: string): void {
    const next = new Set(this.openTags());
    if (next.has(tag)) next.delete(tag);
    else next.add(tag);
    this.openTags.set(next);
  }

  constructor() {
    effect(() => {
      this.poi();
      this.elementRef.nativeElement.focus();
    });
  }
}
