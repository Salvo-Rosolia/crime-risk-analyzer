import { DOCUMENT, NgTemplateOutlet } from '@angular/common';
import {
  afterNextRender,
  ChangeDetectionStrategy,
  Component,
  computed,
  DestroyRef,
  ElementRef,
  inject,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { ApiService } from '@core/api/api.service';
import { SourcesStore } from '@core/state/sources.store';
import type { SourceFile, SourceProblem, SourceTemplate } from '@core/models/models';

interface Slot {
  key: SourceFile;
  label: string;
  hint: string;
  required: boolean;
  accept: string;
  template?: SourceTemplate;
}

const ONTOLOGY_SLOTS: readonly Slot[] = [
  {
    key: 'ontology',
    label: 'Ontologia',
    hint: 'File Turtle (.ttl) oppure OWL/RDF-XML.',
    required: true,
    accept: '.ttl,.owl,.rdf,.xml',
  },
];

const DATA_SLOTS: readonly Slot[] = [
  {
    key: 'osm_table',
    label: 'Tabella OSM → classe',
    hint: 'CSV con le colonne osm_tag e classe.',
    required: true,
    accept: '.csv',
    template: 'osm_table',
  },
  {
    key: 'data',
    label: 'Dati statistici',
    hint: 'CSV con i dati per territorio, voce e anno.',
    required: true,
    accept: '.csv',
    template: 'data',
  },
  {
    key: 'hazard_table',
    label: 'Tabella hazard → voce',
    hint: 'CSV che collega ogni hazard a una voce dei dati.',
    required: true,
    accept: '.csv',
    template: 'hazard_table',
  },
  {
    key: 'boundaries',
    label: 'Confini dei luoghi',
    hint: 'GeoJSON, facoltativo.',
    required: false,
    accept: '.geojson,.json',
  },
];

const SLOT_KEYS: readonly SourceFile[] = [...ONTOLOGY_SLOTS, ...DATA_SLOTS].map((s) => s.key);

const REQUIRED: readonly SourceFile[] = ['ontology', 'osm_table', 'data', 'hazard_table'];

const VOCABULARY_FIELDS = [
  { key: 'namespace', label: 'Namespace', placeholder: 'predefinito: TERMINUS' },
  { key: 'hazard', label: 'Proprietà hazard', placeholder: 'predefinita: TERMINUS' },
  {
    key: 'critical_event',
    label: 'Proprietà evento critico',
    placeholder: 'predefinita: TERMINUS',
  },
  { key: 'performer', label: 'Proprietà autore', placeholder: 'predefinita: TERMINUS' },
  {
    key: 'vulnerability',
    label: 'Proprietà vulnerabilità',
    placeholder: 'più nomi separati da virgola',
  },
] as const;

type VocabularyKey = (typeof VOCABULARY_FIELDS)[number]['key'];

/** Lunghezza massima di un messaggio del controllo mostrato in pagina. */
const MAX_MESSAGE = 320;

/**
 * Rende leggibile un messaggio del controllo: toglie il frammento di file che il parser include
 * dopo `in: "b'…` (illeggibile e inutile all'utente) e accorcia i testi troppo lunghi. La riga e la
 * causa restano; il messaggio completo resta nella risposta del server.
 */
function shortMessage(message: string): string {
  const text = message
    .replace(/\s+in:\s*"?b'[\s\S]*$/, '')
    .replace(/\s+at \^$/, '')
    .trim();
  return text.length > MAX_MESSAGE ? `${text.slice(0, MAX_MESSAGE).trimEnd()}…` : text;
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/**
 * Pagina Fonti (#419): carica i file dell'ontologia e dei dati, mostra gli errori e gli avvisi del
 * controllo agganciati al file a cui si riferiscono, scarica i modelli CSV, attiva l'esempio o
 * torna al default. Si apre sopra la mappa (dialog modale) da qualunque schermata. Lo stato vive in
 * `SourcesStore`; qui restano solo i file scelti e i campi del vocabolario, che sono del modulo.
 */
@Component({
  selector: 'cra-sources-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgTemplateOutlet],
  // Tastiera a livello di documento: un pulsante disabilitato durante l'operazione fa perdere il
  // focus al body, e un handler sul solo dialog non riceverebbe più Esc né Tab.
  host: { '(document:keydown)': 'onKeydown($event)' },
  templateUrl: './sources-page.component.html',
  styleUrl: './sources-page.component.css',
})
export class SourcesPageComponent {
  protected readonly store = inject(SourcesStore);
  private readonly api = inject(ApiService);
  private readonly doc = inject(DOCUMENT);
  /** Chi aveva il focus all'apertura (di solito l'indicatore): gli si rende il focus alla chiusura. */
  private readonly opener = this.doc.activeElement as HTMLElement | null;

  /** Richiesta di chiusura (Chiudi o Esc): mai emessa mentre un'operazione è in volo. */
  readonly closed = output<void>();

  protected readonly ontologySlots = ONTOLOGY_SLOTS;
  protected readonly dataSlots = DATA_SLOTS;
  protected readonly vocabularyFields = VOCABULARY_FIELDS;

  private readonly dialog = viewChild.required<ElementRef<HTMLElement>>('dialog');
  private readonly files = signal<Partial<Record<SourceFile, File>>>({});
  private readonly vocabulary = signal<Partial<Record<VocabularyKey, string>>>({});

  protected readonly canUpload = computed(
    () => REQUIRED.every((key) => this.files()[key]) && this.store.busy() === null,
  );

  /** Errori e avvisi da mostrare: quelli dell'ultimo rifiuto, altrimenti gli avvisi del set attivo. */
  private readonly problems = computed(() => {
    const report = this.store.report();
    return {
      errors: report?.errors ?? [],
      warnings: report ? report.warnings : this.store.activeWarnings(),
    };
  });

  protected readonly busyText = computed(() => {
    switch (this.store.busy()) {
      case 'upload':
        return 'Controllo in corso…';
      case 'example':
      case 'reset':
        return 'Operazione in corso…';
      default:
        return '';
    }
  });

  /** Problemi che non si agganciano a nessun file visibile: non devono sparire. */
  protected readonly generalProblems = computed(() => {
    const known = new Set<string>(SLOT_KEYS);
    const { errors, warnings } = this.problems();
    return [
      ...errors.filter((p) => !known.has(p.file)).map((p) => ({ kind: 'error' as const, p })),
      ...warnings.filter((p) => !known.has(p.file)).map((p) => ({ kind: 'warning' as const, p })),
    ];
  });

  private readonly errorsByFile = computed(() => this.group(this.problems().errors));
  private readonly warningsByFile = computed(() => this.group(this.problems().warnings));

  protected readonly summary = computed(() => {
    const set = this.store.status()?.set;
    if (!set) return null;
    const parts = [
      plural(set.classi, 'classe', 'classi'),
      plural(set.selettori_osm, 'selettore OSM', 'selettori OSM'),
    ];
    if (set.versione_dati) parts.push(`versione dei dati ${set.versione_dati}`);
    if (set.luoghi.length) parts.push(`luoghi: ${set.luoghi.join(', ')}`);
    return parts.join(' · ');
  });

  /** Tanti errori sui nomi dell'ontologia: quasi sempre il vocabolario non è quello TERMINUS. */
  protected readonly vocabularyHint = computed(() => {
    const errors = this.store.report()?.errors ?? [];
    return (
      errors.some((e) => e.code === 'ontologia_senza_restrizioni') ||
      errors.filter((e) => e.code === 'classe_assente_dall_ontologia').length >= 3
    );
  });

  protected readonly expiry = computed(() => {
    const secs = this.store.status()?.scade_tra_secondi;
    if (secs == null) return null;
    return `Scadono tra ${plural(Math.max(1, Math.round(secs / 60)), 'minuto', 'minuti')}.`;
  });

  constructor() {
    // Il focus va al dialog all'apertura: da tastiera si prosegue da lì, e Esc lo chiude.
    afterNextRender(() => this.dialog().nativeElement.focus());
    inject(DestroyRef).onDestroy(() => {
      if (this.opener && this.opener !== this.doc.body && this.opener.isConnected) {
        this.opener.focus();
      }
    });
  }

  protected onClose(): void {
    if (this.store.busy() === null) this.closed.emit();
  }

  protected onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') this.onClose();
    else if (event.key === 'Tab') this.trapTab(event);
  }

  /** Focus trap: Tab non esce dal dialog (aria-modal da solo non lo impedisce). */
  private trapTab(event: KeyboardEvent): void {
    const root = this.dialog().nativeElement;
    const items = Array.from(
      root.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), summary, a[href]',
      ),
    ).filter((el) => el.tagName === 'SUMMARY' || !el.closest('details:not([open])'));
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    const active = this.doc.activeElement;
    if (!root.contains(active) || active === root) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
    } else if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  protected templateUrl(name: SourceTemplate): string {
    return this.api.templateUrl(name);
  }

  protected onFile(key: SourceFile, event: Event): void {
    const file = (event.target as HTMLInputElement).files?.[0];
    this.files.update((current) => {
      const next = { ...current };
      if (file) next[key] = file;
      else delete next[key];
      return next;
    });
  }

  protected onVocabulary(key: VocabularyKey, event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.vocabulary.update((current) => ({ ...current, [key]: value }));
  }

  protected async onSubmit(event: Event): Promise<void> {
    event.preventDefault();
    const f = this.files();
    if (!this.canUpload() || !f.ontology || !f.osm_table || !f.data || !f.hazard_table) return;
    const v = this.vocabulary();
    await this.store.upload({
      ontology: f.ontology,
      osm_table: f.osm_table,
      data: f.data,
      hazard_table: f.hazard_table,
      boundaries: f.boundaries ?? null,
      vocabulary: {
        namespace: v.namespace,
        hazard: v.hazard,
        critical_event: v.critical_event,
        performer: v.performer,
        vulnerability: v.vulnerability?.split(','),
      },
    });
  }

  protected async onUseExample(): Promise<void> {
    await this.store.useExample();
  }

  protected async onReset(): Promise<void> {
    await this.store.reset();
  }

  protected errorsFor(key: SourceFile): SourceProblem[] | undefined {
    return this.errorsByFile()[key];
  }

  protected warningsFor(key: SourceFile): SourceProblem[] | undefined {
    return this.warningsByFile()[key];
  }

  protected messageText(problem: SourceProblem): string {
    return shortMessage(problem.message);
  }

  protected lineText(problem: SourceProblem): string {
    return problem.line == null ? '' : `riga ${problem.line}: `;
  }

  private group(problems: SourceProblem[]): Partial<Record<SourceFile, SourceProblem[]>> {
    const out: Partial<Record<SourceFile, SourceProblem[]>> = {};
    for (const p of problems) (out[p.file] ??= []).push(p);
    return out;
  }
}
