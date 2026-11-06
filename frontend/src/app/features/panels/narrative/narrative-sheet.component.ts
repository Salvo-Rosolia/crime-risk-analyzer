import { NgTemplateOutlet } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  input,
  output,
  signal,
  viewChildren,
} from '@angular/core';
import { ISTAT_TAG_COLOR, srcTagMeta } from '@core/confidence';
import { parseInlineMarkdownWithSlots } from '@core/inline-markdown';
import { NarrativeSourceTag, SourceProse } from '@core/models/models';
import {
  IstatHazardOccurrence,
  IstatProseIndicator,
  ProseSegment,
  SourceTab,
  buildIstatProseCandidates,
  buildSourceTabs,
  withIstatProseIndicators,
} from '@core/ui-helpers';

/** Prose node rendered by the template: styled text (inline markdown) or ISTAT indicator. */
export type ProseNode =
  | { kind: 'text'; text: string; bold: boolean; italic: boolean }
  | { kind: 'istat'; indicator: IstatProseIndicator };

/** Inline markdown → nodes (no innerHTML); the ISTAT indicators are slots inside the text. */
function toNodes(segments: ProseSegment[]): ProseNode[] {
  const parts = segments.map((s) => (s.kind === 'text' ? s.text : { slot: s.indicator }));
  return parseInlineMarkdownWithSlots(parts).map((p) =>
    'slot' in p ? { kind: 'istat', indicator: p.slot } : { kind: 'text', ...p },
  );
}

/**
 * "Narrativa generata" (State B): on a wide layout it is a full-height RIGHT-HAND PANEL (#218),
 * below 1100px it goes back to a full-width bottom sheet (positioning in `narrative-sheet.component.css`).
 * Content: discursive overview + one tab per source (ONTOLOGIA → CONTESTO → ISTAT → SPECULATIVO,
 * via `buildSourceTabs`) with the prose alone (`narrativa_fonti`), anti-hallucination banner ALWAYS
 * visible (even when collapsed — it lives in the header, not in the collapsible body) and
 * "Rigenera" button (re-POST `/analyze`, no new endpoint). "Thin" component: no direct
 * store/http call, only outputs towards the shell; the collapse is driven by `open()` (host class
 * `cra-narr-collapsed`).
 */
@Component({
  selector: 'cra-narrative-sheet',
  imports: [NgTemplateOutlet],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './narrative-sheet.component.html',
  styleUrl: './narrative-sheet.component.css',
  host: {
    // Right-panel layout (#218): host class when collapsed, so the CSS reduces the height
    // to the header alone (the body is already removed via `@if(open())`) without stretching the panel to
    // full height. The safety banner stays in the header anyway, always visible.
    '[class.cra-narr-collapsed]': '!open()',
  },
})
export class NarrativeSheetComponent {
  readonly city = input<string | null>(null);
  readonly zone = input<string | null>(null);
  readonly narrative = input<string>('');
  readonly narrativeSources = input<SourceProse | null>(null);
  readonly open = input<boolean>(true);
  /** Generation in progress (#197): the body declares it, the previous content stays visible. */
  readonly loading = input<boolean>(false);
  /** Error of the last generation (#197); `null` when there is nothing to report. */
  readonly error = input<string | null>(null);
  /** Name of the point when the panel shows the narrative of ONE POI (#197); `null` in zone scope. */
  readonly poiName = input<string | null>(null);
  /** The displayed point has no risks anchored to the ontology (#197): the prose is all inference. */
  readonly ungrounded = input<boolean>(false);
  /** The LLM failed on the displayed point (#197): only the structured data remain. */
  readonly fallback = input<boolean>(false);

  /**
   * Risks of the displayed scope with the ISTAT datum of their POI (#365): zone → all POIs, point → the
   * selected POI. Feeds the inline indicators of the ONTOLOGIA tab.
   */
  readonly istatOccurrences = input<IstatHazardOccurrence[]>([]);

  readonly toggleNarrative = output<void>();
  readonly regenerate = output<void>();

  protected readonly model = computed(() => buildSourceTabs(this.narrativeSources()));
  protected readonly activeTag = signal<NarrativeSourceTag | null>(null);
  protected readonly activeTab = computed<SourceTab | null>(() => {
    const tabs = this.model().tabs;
    if (tabs.length === 0) return null;
    return tabs.find((t) => t.tag === this.activeTag()) ?? tabs[0];
  });
  /**
   * Discursive lead above the tabs: shows `overview` when present; if `overview` is empty but
   * there are tabs, it shows nothing (the prose is already in the panels — avoids duplicating `narrative()`
   * in full above the tabs, review Task 4 FIX 3); falls back to the legacy `narrative()` only when there
   * are no tabs (no structured source to show).
   */
  protected readonly leadText = computed(() => {
    const m = this.model();
    return m.overview || (m.tabs.length === 0 ? this.narrative() : '');
  });
  /** Lead as nodes (inline markdown). */
  protected readonly leadNodes = computed(() => toNodes([{ kind: 'text', text: this.leadText() }]));
  /**
   * Prose of each tab as nodes: inline markdown everywhere; in the ONTOLOGIA tab also the inline
   * ISTAT indicators (#365). The indicator is inserted FIRST on the text with the markers (after the closing `**`/`*`)
   * and the markdown is interpreted on the whole text with the indicators as slots: a
   * `**…**` pair is never split.
   */
  protected readonly tabNodes = computed(() => {
    const occurrences = this.istatOccurrences();
    return this.model().tabs.map((t) => {
      const segments: ProseSegment[] =
        t.tag === 'ONTOLOGIA'
          ? withIstatProseIndicators(
              t.prose,
              buildIstatProseCandidates(occurrences),
              occurrences.map((o) => o.hazardLabel),
            )
          : [{ kind: 'text', text: t.prose }];
      return { tag: t.tag, nodes: toNodes(segments) };
    });
  });
  protected readonly hasIstatIndicator = computed(() =>
    this.tabNodes().some((t) => t.tag === 'ONTOLOGIA' && t.nodes.some((n) => n.kind === 'istat')),
  );
  protected readonly srcMeta = srcTagMeta;
  protected readonly istatColor = ISTAT_TAG_COLOR;
  private readonly tabButtons = viewChildren<ElementRef<HTMLButtonElement>>('tabBtn');

  protected selectTab(tag: NarrativeSourceTag): void {
    this.activeTag.set(tag);
  }

  protected onTabKeydown(event: KeyboardEvent, index: number): void {
    const tabs = this.model().tabs;
    if (tabs.length === 0) return;
    let next: number | null = null;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    if (next === null) return;
    event.preventDefault();
    this.activeTag.set(tabs[next].tag);
    this.tabButtons()[next]?.nativeElement.focus();
  }

  protected onRegenerate(event: Event): void {
    event.stopPropagation();
    this.regenerate.emit();
  }
}
