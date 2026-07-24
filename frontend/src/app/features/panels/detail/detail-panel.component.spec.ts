import { ComponentFixture, TestBed } from '@angular/core/testing';
import { DetailPanelComponent } from './detail-panel.component';
import type { Poi, RiskModel } from '@core/models/models';

function makePoi(overrides: Partial<Poi> = {}): Poi {
  return {
    id: '1',
    name: 'Colosseo',
    terminus_class: 'Archaeological_site',
    lat: 41.89,
    lon: 12.49,
    confidence: 'verificato',
    sparql_path: 'Archaeological_site → havingHazard → Pickpocketing',
    terminus_label_it: 'Sito archeologico',
    terminus_label_en: 'Archaeological site',
    ...overrides,
  };
}

const riskModels: RiskModel[] = [
  {
    poi: 'Colosseo',
    risks: [
      {
        hazard: 'h-spec',
        confidence: 'ipotesi',
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
    // in document.body: senza essere connesso al DOM reale, jsdom non aggiorna
    // document.activeElement quando si chiama .focus() (necessario per i test di focus management).
    document.body.appendChild(fixture.nativeElement);
    fixture.detectChanges();
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [DetailPanelComponent] }).compileComponents();
  });

  afterEach(() => {
    fixture?.nativeElement.remove();
  });

  it('mostra nome POI, terminus class con prefisso tc: + etichetta IT, e il numero del pin', () => {
    setup(makePoi(), riskModels, 3);
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Colosseo');
    expect(text).toContain('tc:Archaeological_site · Sito archeologico');
    expect(fixture.nativeElement.querySelector('.cra-detail-pin').textContent.trim()).toBe('3');
  });

  it("mostra il badge di confidence del POI nell'header", () => {
    setup(makePoi({ confidence: 'da_confermare' }));
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Da confermare');
  });

  it('mostra il pulsante "‹ indietro" (Vista Dettaglio del dock, #199) e il click emette closeDetail', () => {
    setup(makePoi());
    const spy = jest.fn();
    fixture.componentInstance.closeDetail.subscribe(spy);
    const back: HTMLElement = fixture.nativeElement.querySelector('.cra-detail-back');
    expect(back.textContent?.trim()).toBe('‹ indietro');
    back.click();
    expect(spy).toHaveBeenCalled();
  });

  it('rende la citazione SPARQL come catena lineare Classe → proprietà → entità', () => {
    setup(makePoi());
    const parts = fixture.nativeElement.querySelectorAll('.cra-citation-part');
    expect(Array.from(parts).map((p) => (p as HTMLElement).textContent)).toEqual([
      'Archaeological_site',
      'havingHazard',
      'Pickpocketing',
    ]);
    expect(fixture.nativeElement.querySelector('.cra-citation-line').textContent).toContain('→');
  });

  it('senza sparql_path mostra un fallback esplicito (nessuna citazione), non un crash', () => {
    expect(() => setup(makePoi({ sparql_path: null }))).not.toThrow();
    expect(fixture.nativeElement.textContent).toContain('Nessuna citazione');
    expect(fixture.nativeElement.querySelector('.cra-citation-part')).toBeNull();
  });

  it("acceptance: raggruppa i fattori di rischio per tag fonte nell'ordine ONTOLOGIA → CONTESTO → SPECULATIVO", () => {
    setup(makePoi());
    const headers = fixture.nativeElement.querySelectorAll('.cra-source-tag');
    expect(Array.from(headers).map((h) => (h as HTMLElement).textContent?.trim())).toEqual([
      '[ONTOLOGIA]',
      '[CONTESTO]',
      '[SPECULATIVO]',
    ]);
  });

  it('ogni fattore mostra la propria etichetta IT (fallback a hazard) e badge di confidence', () => {
    setup(makePoi());
    const rows = fixture.nativeElement.querySelectorAll('.cra-factor-row');
    expect(rows.length).toBe(3);
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Borseggio');
    expect(text).toContain('Rischio da contesto');
    expect(text).toContain('Ipotesi speculativa');
  });

  it('omette i gruppi senza fattori e non fallisce se il POI non ha risk_models corrispondenti', () => {
    setup(makePoi({ name: 'Sconosciuto' }), riskModels);
    expect(fixture.nativeElement.querySelectorAll('.cra-source-tag').length).toBe(0);
    expect(fixture.nativeElement.querySelectorAll('.cra-factor-row').length).toBe(0);
  });

  it("a11y (focus management, Stato C): all'apertura sposta il focus sul pannello per utenti da tastiera/screen reader", () => {
    setup(makePoi());
    expect(document.activeElement).toBe(fixture.nativeElement);
  });

  it('a11y: il pannello è una region etichettata col nome del POI corrente (annuncio screen reader)', () => {
    setup(makePoi({ name: 'Colosseo' }));
    expect(fixture.nativeElement.getAttribute('role')).toBe('region');
    expect(fixture.nativeElement.getAttribute('aria-label')).toContain('Colosseo');
  });

  it('a11y: rifocalizza il pannello quando cambia il POI selezionato, anche se nel frattempo il focus era altrove (navigazione fra POI senza richiudere)', () => {
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

  it('difesa: confidence fuori-contratto (POI o rischio) non fa collassare la vista, mostra un fallback placeholder', () => {
    const outOfContractPoi = makePoi({ confidence: 'boh' as unknown as Poi['confidence'] });
    const outOfContractRiskModels: RiskModel[] = [
      {
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

  it('rework UI: il footer con le azioni non operative è stato rimosso (niente placeholder disabilitati)', () => {
    setup(makePoi());
    expect(fixture.nativeElement.querySelector('.cra-detail-footer')).toBeNull();
    const text = fixture.nativeElement.textContent;
    expect(text).not.toContain('Segnala errore');
    expect(text).not.toContain('Esporta scheda');
  });

  it('rework UI: la Provenienza (citazione SPARQL) è mostrata DOPO i Fattori di rischio', () => {
    setup(makePoi());
    const eyebrows = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-detail-body .cra-detail-section .cra-eyebrow'),
    ).map((h) => (h as HTMLElement).textContent?.trim());
    expect(eyebrows[0]).toContain('Fattori di rischio');
    expect(eyebrows[1]).toContain('Provenienza');
  });

  it('accordion (default adattivo): con ≤3 fattori totali tutti i gruppi partono aperti', () => {
    setup(makePoi()); // riskModels: 3 rischi, 1 per gruppo → total 3
    expect(fixture.nativeElement.querySelectorAll('.cra-source-group').length).toBe(3);
    expect(fixture.nativeElement.querySelectorAll('.cra-factor-row').length).toBe(3);
    const headers = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-source-header'),
    ) as HTMLElement[];
    headers.forEach((h) => expect(h.getAttribute('aria-expanded')).toBe('true'));
  });

  it('accordion (default adattivo): con >3 fattori resta aperto solo il primo gruppo (ONTOLOGIA), gli altri collassati ma col conteggio', () => {
    const richModels: RiskModel[] = [
      {
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
            confidence: 'ipotesi',
            tag: 'SPECULATIVO',
            hazard_label_it: 'Spec 1',
            hazard_label_en: '',
          },
          {
            hazard: 's2',
            confidence: 'ipotesi',
            tag: 'SPECULATIVO',
            hazard_label_it: 'Spec 2',
            hazard_label_en: '',
          },
        ],
      },
    ];
    setup(makePoi(), richModels);
    expect(fixture.nativeElement.querySelectorAll('.cra-source-group').length).toBe(3);
    expect(fixture.nativeElement.querySelectorAll('.cra-factor-row').length).toBe(2); // solo ONTOLOGIA
    const headers = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-source-header'),
    ) as HTMLElement[];
    expect(headers.map((h) => h.getAttribute('aria-expanded'))).toEqual(['true', 'false', 'false']);
    const counts = Array.from(fixture.nativeElement.querySelectorAll('.cra-source-count')).map(
      (c) => (c as HTMLElement).textContent?.trim(),
    );
    expect(counts).toEqual(['2', '1', '2']);
  });

  it("accordion: cliccando un'intestazione-fonte si collassa/espande il suo elenco di fattori", () => {
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

  it('accordion: cambiando POI lo stato di apertura si resetta al default adattivo del nuovo POI (nessuno stato residuo)', () => {
    const r = (
      hazard: string,
      tag: RiskModel['risks'][number]['tag'],
      confidence: Poi['confidence'],
    ) => ({ hazard, confidence, tag, hazard_label_it: hazard, hazard_label_en: '' });
    const models: RiskModel[] = [
      {
        poi: 'Colosseo',
        risks: [
          r('o1', 'ONTOLOGIA', 'verificato'),
          r('o2', 'ONTOLOGIA', 'verificato'),
          r('c1', 'CONTESTO', 'da_confermare'),
          r('s1', 'SPECULATIVO', 'ipotesi'),
          r('s2', 'SPECULATIVO', 'ipotesi'),
        ],
      },
      {
        poi: 'Duomo',
        risks: [
          r('do1', 'ONTOLOGIA', 'verificato'),
          r('dc1', 'CONTESTO', 'da_confermare'),
          r('ds1', 'SPECULATIVO', 'ipotesi'),
          r('ds2', 'SPECULATIVO', 'ipotesi'),
        ],
      },
    ];
    const aria = (el: Element) => el.getAttribute('aria-expanded');

    setup(makePoi({ id: '1', name: 'Colosseo' }), models);
    // POI A (>3 fattori): default adattivo → solo ONTOLOGIA aperto
    expect(
      Array.from(fixture.nativeElement.querySelectorAll('.cra-source-header')).map(aria),
    ).toEqual(['true', 'false', 'false']);
    // l'utente espande manualmente SPECULATIVO (stato divergente dal default)
    (fixture.nativeElement.querySelectorAll('.cra-source-header')[2] as HTMLElement).click();
    fixture.detectChanges();
    expect(aria(fixture.nativeElement.querySelectorAll('.cra-source-header')[2])).toBe('true');

    // cambio POI SENZA rimontare il componente (come la navigazione reale tra POI)
    fixture.componentRef.setInput('poi', makePoi({ id: '2', name: 'Duomo' }));
    fixture.detectChanges();

    // POI B segue il SUO default adattivo (>3 → solo ONTOLOGIA): SPECULATIVO di nuovo chiuso,
    // nessuno stato residuo del POI precedente.
    expect(
      Array.from(fixture.nativeElement.querySelectorAll('.cra-source-header')).map(aria),
    ).toEqual(['true', 'false', 'false']);
  });
});
