import { ComponentFixture, TestBed } from '@angular/core/testing';
import { DetailPanelComponent, STAKEHOLDER_AXIS_NOTE } from './detail-panel.component';
import type { Poi, RiskModel } from '@core/models/models';
import { istatOrderNote } from '@core/ui-helpers';
import { istatPoi, istatRow } from '@core/testing/istat-fixtures';

function makePoi(overrides: Partial<Poi> = {}): Poi {
  return {
    id: '1',
    name: 'Colosseo',
    ontology_class: 'Archaeological_site',
    lat: 41.89,
    lon: 12.49,
    confidence: 'verificato',
    sparql_path: 'Archaeological_site → havingHazard → Pickpocketing',
    ontology_label_it: 'Sito archeologico',
    ontology_label_en: 'Archaeological site',
    ...overrides,
  };
}

const riskModels: RiskModel[] = [
  {
    poi_id: '1',
    poi: 'Colosseo',
    risks: [
      {
        hazard: 'h-spec',
        confidence: 'da_confermare',
        tag: 'SPECULATIVO',
        hazard_label_it: 'Ipotesi speculativa',
        hazard_label_en: 'Speculative hypothesis',
      },
      {
        hazard: 'h-onto',
        confidence: 'verificato',
        tag: 'ONTOLOGIA',
        hazard_label_it: 'Borseggio',
        hazard_label_en: 'Pickpocketing',
      },
      {
        hazard: 'h-ctx',
        confidence: 'da_confermare',
        tag: 'CONTESTO',
        hazard_label_it: 'Rischio da contesto',
        hazard_label_en: 'Context risk',
      },
    ],
  },
];

describe('DetailPanelComponent', () => {
  let fixture: ComponentFixture<DetailPanelComponent>;

  function setup(poi: Poi, models: RiskModel[] = riskModels, number = 1): void {
    fixture = TestBed.createComponent(DetailPanelComponent);
    fixture.componentRef.setInput('poi', poi);
    fixture.componentRef.setInput('number', number);
    fixture.componentRef.setInput('riskModels', models);
    // in document.body: without being connected to the real DOM, jsdom does not update
    // document.activeElement when .focus() is called (needed for the focus management tests).
    document.body.appendChild(fixture.nativeElement);
    fixture.detectChanges();
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [DetailPanelComponent] }).compileComponents();
  });

  afterEach(() => {
    fixture?.nativeElement.remove();
  });

  it('shows POI name, ontology class without prefix + IT label, and the pin number', () => {
    setup(makePoi(), riskModels, 3);
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Colosseo');
    expect(text).toContain('Archaeological_site · Sito archeologico');
    expect(fixture.nativeElement.querySelector('.cra-detail-pin').textContent.trim()).toBe('3');
  });

  it('does not repeat the class when the IT label falls back to it', () => {
    setup(makePoi({ ontology_class: 'Bank', ontology_label_it: undefined }));
    const cls = fixture.nativeElement.querySelector('.cra-detail-class').textContent;
    expect(cls.trim()).toBe('Bank');
  });

  it('shows the POI confidence badge in the header', () => {
    setup(makePoi({ confidence: 'da_confermare' }));
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Anonimo');
  });

  it('#220: a POI outside the ontology (confidence null) does not show the confidence badge in the header, but the pin stays neutral', () => {
    setup(makePoi({ confidence: null, sparql_path: null }), []);
    expect(fixture.nativeElement.querySelector('.cra-badge-confidence')).toBeNull();
    expect(fixture.nativeElement.querySelector('.cra-detail-pin')).not.toBeNull();
  });

  it('shows the "‹ indietro" button (Detail view of the dock, #199) and the click emits closeDetail', () => {
    setup(makePoi());
    const spy = jest.fn();
    fixture.componentInstance.closeDetail.subscribe(spy);
    const back: HTMLElement = fixture.nativeElement.querySelector('.cra-detail-back');
    expect(back.textContent?.trim()).toBe('‹ indietro');
    back.click();
    expect(spy).toHaveBeenCalled();
  });

  it('renders the SPARQL citation as a linear chain Class → property → entity', () => {
    setup(makePoi());
    const parts = fixture.nativeElement.querySelectorAll('.cra-citation-part');
    expect(Array.from(parts).map((p) => (p as HTMLElement).textContent)).toEqual([
      'Archaeological_site',
      'havingHazard',
      'Pickpocketing',
    ]);
    expect(fixture.nativeElement.querySelector('.cra-citation-line').textContent).toContain('→');
  });

  it('without sparql_path it shows an explicit fallback (no citation), not a crash', () => {
    expect(() => setup(makePoi({ sparql_path: null }))).not.toThrow();
    expect(fixture.nativeElement.textContent).toContain('Nessuna citazione');
    expect(fixture.nativeElement.querySelector('.cra-citation-part')).toBeNull();
  });

  it('acceptance: groups the risk factors by source tag in the order ONTOLOGIA → CONTESTO → SPECULATIVO', () => {
    setup(makePoi());
    const headers = fixture.nativeElement.querySelectorAll('.cra-source-tag');
    expect(Array.from(headers).map((h) => (h as HTMLElement).textContent?.trim())).toEqual([
      '[ONTOLOGIA]',
      '[CONTESTO]',
      '[SPECULATIVO]',
    ]);
  });

  it('each factor shows its own IT label (fallback to hazard) and confidence badge', () => {
    setup(makePoi());
    const rows = fixture.nativeElement.querySelectorAll('.cra-factor-row');
    expect(rows.length).toBe(3);
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Borseggio');
    expect(text).toContain('Rischio da contesto');
    expect(text).toContain('Ipotesi speculativa');
  });

  it('shows the ontology axes beyond hazards, each with its own citation', () => {
    // #256: the ontology gives four axes and the panel showed one. Critical events and
    // stakeholders were read by nobody, the vulnerabilities only ended up in the prompt.
    setup(
      makePoi({
        critical_events: [
          {
            name: 'Heist',
            source: 'Bank → havingCriticalEvent → Heist',
            label_it: 'Colpo in banca',
            label_en: 'Heist',
          },
        ],
        vulnerabilities: [
          {
            name: 'Poor_surveillance',
            source: 'Bank → isVulnerableTo → Poor_surveillance',
            label_it: 'Sorveglianza scarsa',
            label_en: 'Poor surveillance',
          },
        ],
      }),
    );

    const text = fixture.nativeElement.textContent;
    expect(fixture.nativeElement.querySelectorAll('.cra-axis-group').length).toBe(2);
    expect(text).toContain('Colpo in banca');
    expect(text).toContain('Sorveglianza scarsa');
    // the citation accompanies the entry: without it, the axis is not verifiable
    expect(text).toContain('havingCriticalEvent');
  });

  it('does not show any ontology axis if the POI has none', () => {
    setup(makePoi());
    expect(fixture.nativeElement.querySelectorAll('.cra-axis-group').length).toBe(0);
  });

  it('shows only the populated axes, not all or none', () => {
    // The filter is PER AXIS: a test with all three populated would not tell this
    // behavior apart from an all-or-nothing on the union.
    setup(
      makePoi({
        vulnerabilities: [
          {
            name: 'Poor_surveillance',
            source: 'Bank → isVulnerableTo → Poor_surveillance',
            label_it: 'Sorveglianza scarsa',
            label_en: 'Poor surveillance',
          },
        ],
      }),
    );

    expect(fixture.nativeElement.querySelectorAll('.cra-axis-group').length).toBe(1);
    expect(fixture.nativeElement.textContent).toContain('Vulnerabilità');
    expect(fixture.nativeElement.textContent).not.toContain('Eventi critici');
    expect(fixture.nativeElement.textContent).not.toContain('Stakeholder');
  });

  it('ACCEPTANCE (fail-if-removed): the Stakeholder axis shows the note that distinguishes it from an operational indication (#270)', () => {
    setup(
      makePoi({
        stakeholders: [
          {
            name: 'Mayor',
            source: 'Archaeological_site → havingPerformer → Mayor',
            label_it: 'Sindaco',
            label_en: 'Mayor',
          },
        ],
      }),
    );

    const text = fixture.nativeElement.textContent;
    expect(fixture.nativeElement.querySelectorAll('.cra-axis-group').length).toBe(1);
    expect(text).toContain('Stakeholder');
    expect(text).toContain('Sindaco');
    expect(text).toContain(STAKEHOLDER_AXIS_NOTE);
  });

  it('does not show the Stakeholder note on the other axes', () => {
    setup(
      makePoi({
        vulnerabilities: [
          {
            name: 'Poor_surveillance',
            source: 'Bank → isVulnerableTo → Poor_surveillance',
            label_it: 'Sorveglianza scarsa',
            label_en: 'Poor surveillance',
          },
        ],
      }),
    );

    expect(fixture.nativeElement.textContent).not.toContain(STAKEHOLDER_AXIS_NOTE);
  });

  it('a POI outside the ontology with populated axes shows them, without a badge from which to inherit a level', () => {
    // #220: `confidence: null` means "no risk to qualify", not "unknown", so the
    // badge at the top is not there. The other three axes come from OWL properties independent of the hazards,
    // so they may be there anyway: the entries stay bare, they are facts about the TERMINUS class.
    setup(
      makePoi({
        confidence: null,
        critical_events: [
          {
            name: 'Heritage_damage',
            source: 'Archaeological_site → havingCriticalEvent → Heritage_damage',
            label_it: 'Danneggiamento del patrimonio',
            label_en: 'Heritage damage',
          },
        ],
      }),
    );

    expect(fixture.nativeElement.querySelectorAll('.cra-axis-group').length).toBe(1);
    expect(fixture.nativeElement.textContent).toContain('Danneggiamento del patrimonio');
    // The badge from which the entries would "inherit" the qualification is the HEADER one:
    // `.cra-badge-confidence` also appears on the risk factor rows, so the query
    // must be narrowed or it would pass (or fail) for the wrong reason.
    expect(
      fixture.nativeElement.querySelector('.cra-detail-name-row .cra-badge-confidence'),
    ).toBeNull();
  });

  it('uses the raw identifier when the IT label is missing', () => {
    setup(
      makePoi({
        critical_events: [
          {
            name: 'Bank_robbery',
            source: 'Bank → havingCriticalEvent → Bank_robbery',
            label_it: '',
            label_en: 'Bank robbery',
          },
        ],
      }),
    );

    expect(fixture.nativeElement.querySelector('.cra-axis-label').textContent).toContain(
      'Bank_robbery',
    );
  });

  it('omits the groups without factors and does not fail if the POI has no matching risk_models', () => {
    // The non-match is built on the id, which is the join key: a different name
    // is no longer enough (and it should not have been, it was the defect).
    setup(makePoi({ id: 'id-senza-rischi' }), riskModels);
    expect(fixture.nativeElement.querySelectorAll('.cra-source-tag').length).toBe(0);
    expect(fixture.nativeElement.querySelectorAll('.cra-factor-row').length).toBe(0);
  });

  it('a11y (focus management, State C): on opening it moves the focus to the panel for keyboard/screen reader users', () => {
    setup(makePoi());
    expect(document.activeElement).toBe(fixture.nativeElement);
  });

  it('a11y: the panel is a region labelled with the current POI name (screen reader announcement)', () => {
    setup(makePoi({ name: 'Colosseo' }));
    expect(fixture.nativeElement.getAttribute('role')).toBe('region');
    expect(fixture.nativeElement.getAttribute('aria-label')).toContain('Colosseo');
  });

  it('a11y: refocuses the panel when the selected POI changes, even if the focus was elsewhere in the meantime (navigation between POIs without closing)', () => {
    setup(makePoi({ id: '1', name: 'Colosseo' }));
    const dummy = document.createElement('input');
    document.body.appendChild(dummy);
    dummy.focus();
    expect(document.activeElement).toBe(dummy);

    fixture.componentRef.setInput('poi', makePoi({ id: '2', name: 'Duomo' }));
    fixture.detectChanges();

    expect(document.activeElement).toBe(fixture.nativeElement);
    dummy.remove();
  });

  it('defense: out-of-contract confidence (POI or risk) does not collapse the view, shows a placeholder fallback', () => {
    const outOfContractPoi = makePoi({ confidence: 'boh' as unknown as Poi['confidence'] });
    const outOfContractRiskModels: RiskModel[] = [
      {
        poi_id: '1',
        poi: 'Colosseo',
        risks: [
          {
            hazard: 'h-boh',
            confidence: 'boh' as unknown as RiskModel['risks'][number]['confidence'],
            tag: 'ONTOLOGIA',
            hazard_label_it: 'Fattore ignoto',
            hazard_label_en: 'Unknown factor',
          },
        ],
      },
    ];

    expect(() => setup(outOfContractPoi, outOfContractRiskModels)).not.toThrow();
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Sconosciuto');
    expect(text).toContain('Fattore ignoto');
  });

  it('UI rework: the footer with the non-operational actions has been removed (no disabled placeholders)', () => {
    setup(makePoi());
    expect(fixture.nativeElement.querySelector('.cra-detail-footer')).toBeNull();
    const text = fixture.nativeElement.textContent;
    expect(text).not.toContain('Segnala errore');
    expect(text).not.toContain('Esporta scheda');
  });

  it('#261: a POI without a name (anonymous OSM feature) shows the class fallback in the header and in the aria-label, not a blank row', () => {
    setup(makePoi({ name: '', ontology_class: 'Bank', ontology_label_it: 'Banca' }));
    expect(fixture.nativeElement.querySelector('.cra-detail-name').textContent.trim()).toBe(
      'Banca (senza nome su OSM)',
    );
    expect(fixture.nativeElement.getAttribute('aria-label')).toContain('Banca (senza nome su OSM)');
  });

  it('UI rework: the Provenienza (SPARQL citation) is shown AFTER the Risk factors', () => {
    setup(makePoi());
    const eyebrows = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-detail-body .cra-detail-section .cra-eyebrow'),
    ).map((h) => (h as HTMLElement).textContent?.trim());
    expect(eyebrows[0]).toContain('Fattori di rischio');
    expect(eyebrows[1]).toContain('Provenienza');
  });

  it('accordion (adaptive default): with ≤3 total factors all the groups start open', () => {
    setup(makePoi()); // riskModels: 3 risks, 1 per group → total 3
    expect(fixture.nativeElement.querySelectorAll('.cra-source-group').length).toBe(3);
    expect(fixture.nativeElement.querySelectorAll('.cra-factor-row').length).toBe(3);
    const headers = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-source-header'),
    ) as HTMLElement[];
    headers.forEach((h) => expect(h.getAttribute('aria-expanded')).toBe('true'));
  });

  it('accordion (adaptive default): with >3 factors only the first group (ONTOLOGIA) stays open, the others collapsed but with the count', () => {
    const richModels: RiskModel[] = [
      {
        poi_id: '1',
        poi: 'Colosseo',
        risks: [
          {
            hazard: 'o1',
            confidence: 'verificato',
            tag: 'ONTOLOGIA',
            hazard_label_it: 'Onto 1',
            hazard_label_en: '',
          },
          {
            hazard: 'o2',
            confidence: 'verificato',
            tag: 'ONTOLOGIA',
            hazard_label_it: 'Onto 2',
            hazard_label_en: '',
          },
          {
            hazard: 'c1',
            confidence: 'da_confermare',
            tag: 'CONTESTO',
            hazard_label_it: 'Ctx 1',
            hazard_label_en: '',
          },
          {
            hazard: 's1',
            confidence: 'da_confermare',
            tag: 'SPECULATIVO',
            hazard_label_it: 'Spec 1',
            hazard_label_en: '',
          },
          {
            hazard: 's2',
            confidence: 'da_confermare',
            tag: 'SPECULATIVO',
            hazard_label_it: 'Spec 2',
            hazard_label_en: '',
          },
        ],
      },
    ];
    setup(makePoi(), richModels);
    expect(fixture.nativeElement.querySelectorAll('.cra-source-group').length).toBe(3);
    expect(fixture.nativeElement.querySelectorAll('.cra-factor-row').length).toBe(2); // ONTOLOGIA only
    const headers = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-source-header'),
    ) as HTMLElement[];
    expect(headers.map((h) => h.getAttribute('aria-expanded'))).toEqual(['true', 'false', 'false']);
    const counts = Array.from(fixture.nativeElement.querySelectorAll('.cra-source-count')).map(
      (c) => (c as HTMLElement).textContent?.trim(),
    );
    expect(counts).toEqual(['2', '1', '2']);
  });

  it('accordion: clicking a source heading collapses/expands its list of factors', () => {
    setup(makePoi());
    expect(fixture.nativeElement.querySelectorAll('.cra-factor-row').length).toBe(3);
    const first = fixture.nativeElement.querySelector('.cra-source-header') as HTMLElement;
    first.click();
    fixture.detectChanges();
    expect(first.getAttribute('aria-expanded')).toBe('false');
    expect(fixture.nativeElement.querySelectorAll('.cra-factor-row').length).toBe(2);
    first.click();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelectorAll('.cra-factor-row').length).toBe(3);
  });

  it('accordion: changing POI the open state resets to the adaptive default of the new POI (no leftover state)', () => {
    const r = (
      hazard: string,
      tag: RiskModel['risks'][number]['tag'],
      confidence: Poi['confidence'],
    ) => ({ hazard, confidence, tag, hazard_label_it: hazard, hazard_label_en: '' });
    const models: RiskModel[] = [
      {
        poi_id: '1',
        poi: 'Colosseo',
        risks: [
          r('o1', 'ONTOLOGIA', 'verificato'),
          r('o2', 'ONTOLOGIA', 'verificato'),
          r('c1', 'CONTESTO', 'da_confermare'),
          r('s1', 'SPECULATIVO', 'da_confermare'),
          r('s2', 'SPECULATIVO', 'da_confermare'),
        ],
      },
      {
        poi_id: '2',
        poi: 'Duomo',
        risks: [
          r('do1', 'ONTOLOGIA', 'verificato'),
          r('dc1', 'CONTESTO', 'da_confermare'),
          r('ds1', 'SPECULATIVO', 'da_confermare'),
          r('ds2', 'SPECULATIVO', 'da_confermare'),
        ],
      },
    ];
    const aria = (el: Element) => el.getAttribute('aria-expanded');

    setup(makePoi({ id: '1', name: 'Colosseo' }), models);
    // POI A (>3 factors): adaptive default → only ONTOLOGIA open
    expect(
      Array.from(fixture.nativeElement.querySelectorAll('.cra-source-header')).map(aria),
    ).toEqual(['true', 'false', 'false']);
    // the user manually expands SPECULATIVO (state diverging from the default)
    (fixture.nativeElement.querySelectorAll('.cra-source-header')[2] as HTMLElement).click();
    fixture.detectChanges();
    expect(aria(fixture.nativeElement.querySelectorAll('.cra-source-header')[2])).toBe('true');

    // POI change WITHOUT remounting the component (like real navigation between POIs)
    fixture.componentRef.setInput('poi', makePoi({ id: '2', name: 'Duomo' }));
    fixture.detectChanges();

    // POI B follows ITS adaptive default (>3 → only ONTOLOGIA): SPECULATIVO closed again,
    // no leftover state of the previous POI.
    expect(
      Array.from(fixture.nativeElement.querySelectorAll('.cra-source-header')).map(aria),
    ).toEqual(['true', 'false', 'false']);
  });

  const ontoModels: RiskModel[] = [
    {
      poi_id: '1',
      poi: 'Colosseo',
      risks: ['h-a', 'h-b', 'h-c'].map((hazard) => ({
        hazard,
        confidence: 'verificato' as const,
        tag: 'ONTOLOGIA' as const,
        hazard_label_it: hazard.toUpperCase(),
        hazard_label_en: hazard,
      })),
    },
  ];

  function labels(): string[] {
    return Array.from(
      fixture.nativeElement.querySelectorAll('.cra-factor-label') as NodeListOf<HTMLElement>,
    ).map((el) => el.textContent?.trim() ?? '');
  }

  /** The two `<ul class="cra-factor-list">` of the first source group (#346, O9: with data/without data). */
  function factorLists(): HTMLUListElement[] {
    return Array.from(
      fixture.nativeElement.querySelectorAll(
        '.cra-source-group .cra-factor-list',
      ) as NodeListOf<HTMLUListElement>,
    );
  }

  function listLabels(list: HTMLUListElement): string[] {
    return Array.from(list.querySelectorAll('.cra-factor-label') as NodeListOf<HTMLElement>).map(
      (el) => el.textContent?.trim() ?? '',
    );
  }

  it('#346: orders the group risks with the ISTAT datum and shows the note with place and year', () => {
    const data = istatPoi(
      istatRow('LOW', ['h-b'], { tasso: 50 }),
      istatRow('HIGH', ['h-c'], { tasso: 300 }),
    );
    setup(makePoi({ istat: data }), ontoModels);
    expect(labels()).toEqual(['H-C', 'H-B', 'H-A']);
    const note = fixture.nativeElement.querySelector('.cra-istat-order-note');
    expect(note?.textContent?.trim()).toBe(istatOrderNote(data));
  });

  it("#346: without istat (absent or null) today's order and no note, no ISTAT tail", () => {
    for (const poi of [makePoi(), makePoi({ istat: null })]) {
      setup(poi, ontoModels);
      expect(labels()).toEqual(['H-A', 'H-B', 'H-C']);
      expect(fixture.nativeElement.querySelector('.cra-istat-order-note')).toBeNull();
      expect(fixture.nativeElement.querySelector('.cra-istat-tail-label')).toBeNull();
      expect(factorLists().length).toBe(1); // ontoModels: a single source group (ONTOLOGIA), not mixed
      fixture.nativeElement.remove();
    }
  });

  it('#346: note only on the groups that have at least one risk with data', () => {
    setup(makePoi({ istat: istatPoi(istatRow('HIGH', ['h-onto'], { tasso: 300 })) }), riskModels);
    const groups = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-source-group') as NodeListOf<HTMLElement>,
    );
    const withNote = groups.map((g) => g.querySelector('.cra-istat-order-note') !== null);
    // riskModels: one risk per group (ONTOLOGIA, CONTESTO, SPECULATIVO), only h-onto has data.
    expect(withNote).toEqual([true, false, false]);
  });

  it('#346 (O9): mixed group (data + no data) shows "Dato ISTAT assente o troppo esiguo" between two distinct lists, the tail in arrival order', () => {
    // Only h-c has an ISTAT item: h-a and h-b stay "without data", in the order in which they arrive
    // from ontoModels (h-a before h-b).
    setup(makePoi({ istat: istatPoi(istatRow('HIGH', ['h-c'], { tasso: 300 })) }), ontoModels);

    const lists = factorLists();
    expect(lists.length).toBe(2);
    expect(listLabels(lists[0])).toEqual(['H-C']);
    expect(listLabels(lists[1])).toEqual(['H-A', 'H-B']);

    const tailLabel = fixture.nativeElement.querySelector('.cra-istat-tail-label');
    expect(tailLabel?.textContent?.trim()).toBe('Dato ISTAT assente o troppo esiguo');
    // The label sits BETWEEN the two lists (accessible structure required by O9).
    expect(tailLabel.previousElementSibling).toBe(lists[0]);
    expect(tailLabel.nextElementSibling).toBe(lists[1]);
  });

  it('#346 (O9): group entirely with ISTAT data → a single list, no "Dato ISTAT assente o troppo esiguo" label', () => {
    setup(
      makePoi({
        istat: istatPoi(
          istatRow('A', ['h-a'], { tasso: 50 }),
          istatRow('B', ['h-b'], { tasso: 80 }),
          istatRow('C', ['h-c'], { tasso: 300 }),
        ),
      }),
      ontoModels,
    );

    expect(factorLists().length).toBe(1);
    expect(fixture.nativeElement.querySelector('.cra-istat-tail-label')).toBeNull();
    // #347: fully ordered group → an indicator on every row.
    expect(indicators(factorLists()[0]).every((t) => t !== null)).toBe(true);
  });

  function indicators(list: HTMLElement): (string | null)[] {
    return Array.from(list.querySelectorAll('.cra-factor-row') as NodeListOf<HTMLElement>).map(
      (row) =>
        row.querySelector('.cra-istat-indicator')?.textContent?.replace(/\s+/g, ' ').trim() ?? null,
    );
  }

  /** Classes of the direct children of a row, in DOM order (reading order). */
  function rowStructure(row: Element): string[] {
    return Array.from(row.children).map((el) => el.className.split(' ')[0]);
  }

  it('#347: full row — whole indicator text, decorative arrow', () => {
    const data = istatPoi(
      istatRow('THEFT', ['h-c'], {
        voce_label: 'furti',
        delitti: 134169,
        delitti_confronto: 22,
        tasso: 4876.4,
        tasso_italia: 1673.26,
        variazione_pct: 2114,
      }),
    );
    setup(makePoi({ istat: data }), ontoModels);

    const lists = factorLists();
    expect(indicators(lists[0])).toEqual([
      'furti (voce ISTAT più ampia del rischio) · 134.169 delitti denunciati nel 2024 · 4.876,4 ogni 100.000 ab. (Italia: 1.673,3) · ▲ in crescita (+2114% dal 2014, erano 22)',
    ]);
    const freccia = lists[0].querySelector('.cra-istat-indicator [aria-hidden="true"]');
    expect(freccia?.textContent?.trim()).toBe('▲');
  });

  it('#347 (a11y): in the DOM the badge comes right after the label and before the indicator; the tail has the same structure without an indicator', () => {
    setup(makePoi({ istat: istatPoi(istatRow('HIGH', ['h-c'], { tasso: 300 })) }), ontoModels);

    const [ranked, tail] = factorLists();
    expect(rowStructure(ranked.querySelector('.cra-factor-row')!)).toEqual([
      'cra-factor-label',
      'cra-badge-confidence',
      'cra-istat-indicator',
    ]);
    for (const row of Array.from(tail.querySelectorAll('.cra-factor-row'))) {
      expect(rowStructure(row)).toEqual(['cra-factor-label', 'cra-badge-confidence']);
    }
  });

  it('#347: two risks on the same ISTAT item → the first full, the second "stessa voce ISTAT: …"', () => {
    const data = istatPoi(
      istatRow('DAMAGE', ['h-a', 'h-b'], {
        voce_label: 'danneggiamenti',
        collegamenti: [
          { hazard: 'h-a', hazard_label_it: 'A', corrispondenza: 'esatta' },
          { hazard: 'h-b', hazard_label_it: 'B', corrispondenza: 'piu_larga' },
        ],
      }),
    );
    setup(makePoi({ istat: data }), ontoModels);

    const [ranked] = factorLists();
    expect(listLabels(ranked)).toEqual(['H-A', 'H-B']);
    const [first, second] = indicators(ranked);
    expect(first).toBe(
      'danneggiamenti · 100 delitti denunciati nel 2024 · 100,0 ogni 100.000 ab. (Italia: 100,0) · stabile (0% dal 2014, erano 100)',
    );
    expect(second).toBe('stessa voce ISTAT: danneggiamenti (voce ISTAT più ampia del rischio)');
  });

  it('#347: istat present but no risk with weight (all items under 20 crimes) → no indicator, note or tail', () => {
    const data = istatPoi(
      istatRow('A', ['h-a'], { delitti: 19 }),
      istatRow('C', ['h-c'], { delitti: 3 }),
    );
    setup(makePoi({ istat: data }), ontoModels);

    expect(labels()).toEqual(['H-A', 'H-B', 'H-C']);
    expect(factorLists().length).toBe(1);
    expect(fixture.nativeElement.querySelector('.cra-istat-indicator')).toBeNull();
    expect(fixture.nativeElement.querySelector('.cra-istat-order-note')).toBeNull();
    expect(fixture.nativeElement.querySelector('.cra-istat-tail-label')).toBeNull();
  });

  it('#347: without istat no indicator', () => {
    setup(makePoi(), ontoModels);
    expect(fixture.nativeElement.querySelector('.cra-istat-indicator')).toBeNull();
  });
});
