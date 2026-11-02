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
import { OntologyItem, Poi, RiskModel } from '@core/models/models';
import {
  IstatEntry,
  TagGroup,
  buildDetailModel,
  hazardDisplayLabel,
  istatOrderNote,
  ontologyDisplayLabel,
  orderGroupsByTag,
  orderRisksByIstat,
  poiNameDisplayLabel,
  withIstatIndicators,
} from '@core/ui-helpers';

/**
 * Note of the Stakeholder axis (#270): a list of actors next to hazards/vulnerabilities lends itself
 * to being read as "who to alert" — operational directives are forbidden (_project.md
 * §Constraints). It is a cited ontology datum, not an operational indication: the note says so.
 */
export const STAKEHOLDER_AXIS_NOTE =
  "Dato citato dall'ontologia: non è un'indicazione su chi contattare o allertare.";

/**
 * "Dettaglio POI" card (State C, spec-frontend.md §State C): linear SPARQL citation
 * (Class → property → entity) + risk factors grouped by source tag, in the order
 * ONTOLOGIA → CONTESTO → SPECULATIVO; within each group the risks linked to an ISTAT item
 * come first (#346). "Thin" component: it consumes the already tested pure helpers
 * (`buildDetailModel`, `orderGroupsByTag`) without reimplementing their logic.
 *
 * Focus management (a11y, required by frontend-dev.md/reviewer-frontend.md — review #67,
 * non-blocking #8): the panel itself is the target of the programmatic focus (`tabindex="-1"`,
 * not in the natural tab order) — no additional wrapper in the template. The `effect()` depends on
 * `poi()`, so it refocuses both on opening and when going from one POI to another without closing
 * (the shell's `@if` does not remount the component in that case, only the inputs change).
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
  /** Position of the POI in the `store.fullData()?.poi` array (+1): same number as the paired pin/card. */
  readonly number = input.required<number>();
  readonly riskModels = input<RiskModel[]>([]);

  readonly closeDetail = output<void>();

  private readonly elementRef = inject(ElementRef<HTMLElement>);

  /**
   * Defensive access to the confidence (story #207/#220, fix-review): an out-of-contract value
   * (migration mismatch, legacy data) or `null` (POI outside the ontology, #220) degrades to a
   * placeholder — neutral pin on `.cra-detail-pin` (always rendered) — instead of making
   * the view collapse into a change detection TypeError — `conf[level]` indexed
   * directly would be `undefined`. The header's text badge (`.cra-badge-confidence`)
   * is instead OMITTED altogether for a `null` POI (no badge, template), not degraded to the
   * "Sconosciuto" placeholder: that fallback remains for out-of-contract values only. `pinColor`
   * for the color, `confMeta` for dot/label: same defensive pattern already used elsewhere in
   * `core/confidence.ts`.
   */
  protected readonly pinColor = pinColor;
  protected readonly confMeta = confMeta;
  protected readonly hazardLabel = hazardDisplayLabel;

  protected readonly detailModel = computed(() => buildDetailModel(this.poi(), this.riskModels()));

  /**
   * Source groups in canonical order (`orderGroupsByTag`) and, within each, risks ordered with the
   * ISTAT datum of the POI's place (#346): first those with data, by local rate relative to the
   * Italian average, then the others. Order and ISTAT indicators (#347) come out of the same pass
   * (`orderRisksByIstat` + `withIstatIndicators`, same matching), once per POI and not at every
   * template refresh; the first occurrence of an item is decided here, on the final order.
   *
   * `lists` are the group's row lists: just one, or two when the group is mixed (#346
   * O9: risks with data, then the tail without; with all/none the tail does not exist) — the template
   * renders them with the same row markup and puts the label "Dato ISTAT assente o troppo
   * esiguo" before the second one. `istatNote` declares
   * where the order comes from — without it, an order that changes for no reason would read as a
   * dangerousness ranking of the POI. `null` if the group has no risks with data or the POI does not
   * carry `istat` (switch off).
   */
  protected readonly orderedGroups = computed<
    (TagGroup & { istatNote: string | null; lists: IstatEntry[][] })[]
  >(() => {
    const istat = this.poi().istat;
    const note = istat ? istatOrderNote(istat) : null;
    return orderGroupsByTag(this.detailModel().groups).map((group) => {
      const { risks, rankedCount } = orderRisksByIstat(group.risks, istat);
      const entries = withIstatIndicators(risks, istat);
      const mixed = rankedCount > 0 && rankedCount < risks.length;
      return {
        tag: group.tag,
        risks,
        lists: mixed ? [entries.slice(0, rankedCount), entries.slice(rankedCount)] : [entries],
        istatNote: rankedCount > 0 ? note : null,
      };
    });
  });

  protected readonly srcMeta = srcTagMeta;
  /** POI name with fallback on the class if missing on OSM (#261). */
  protected readonly poiName = computed(() => poiNameDisplayLabel(this.poi()));
  protected readonly panelAriaLabel = computed(() => `Dettaglio POI: ${this.poiName()}`);

  protected readonly axisLabel = ontologyDisplayLabel;

  /**
   * The TERMINUS axes beyond hazards (#256/#270), ready for the template: only the non-empty
   * ones, in the order in which the SPARQL executor queries them. They are qualitative lists with their
   * own citation: no count presented as a measure and no per-entry grading,
   * because the evidential strength is a bit derived from the POI name and holds identically for each of its
   * ontology assertions — the badge at the top of the panel declares it once for all.
   *
   * Declared edge case: a POI without hazards has `confidence: null` (#220 — "no risk to
   * qualify", not "unknown") and therefore NO badge, but it may have the other three axes populated,
   * because they come from independent OWL properties. There the entries stay bare: they are facts about the
   * TERMINUS class, as true as the POI's mapping, and there is no level to inherit.
   *
   * The Stakeholder axis additionally carries `note` (#270): only it lends itself to the misleading
   * reading "who to alert", so only it shows the clarification in the template.
   */
  protected readonly ontologyAxes = computed<
    { title: string; entries: OntologyItem[]; note?: string }[]
  >(() => {
    const poi = this.poi();
    return [
      { title: 'Eventi critici', entries: poi.critical_events ?? [] },
      { title: 'Vulnerabilità', entries: poi.vulnerabilities ?? [] },
      {
        title: 'Stakeholder',
        entries: poi.stakeholders ?? [],
        note: STAKEHOLDER_AXIS_NOTE,
      },
    ].filter((axis) => axis.entries.length > 0);
  });

  /**
   * Threshold of the adaptive accordion (UI rework): with few total factors the source groups start
   * all open (no friction); beyond the threshold only the most reliable group present stays open
   * (ONTOLOGIA is first in `orderGroupsByTag`) and the others collapse, but always with the count
   * visible — so the least certain is tucked away, not the verified one.
   */
  private static readonly ADAPTIVE_OPEN_THRESHOLD = 3;

  /**
   * Tags of the source groups currently expanded. `linkedSignal` (not `signal`) because the open
   * state must RESET to the adaptive default when the selected POI changes — the component
   * does not remount when navigating between POIs, only `poi()` changes (see the focus effect below) — while
   * remaining modifiable by the user's clicks on the same POI. The reset key is `poi().id`
   * (identity of the POI); note that `computation` also reads `orderedGroups()` (which depends on
   * `riskModels()`), so in theory even a change of reference of the risk_models for the same POI
   * would reset the toggles — today not reachable because `transition.ts` clears `selectedPoiId`
   * (unmounting this view) every time the data might change.
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
