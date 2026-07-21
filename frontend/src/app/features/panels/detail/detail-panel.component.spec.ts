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
    confidence: 'confermato',
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
        confidence: 'speculativo',
        tag: 'SPECULATIVO',
        hazard_label_it: 'Ipotesi speculativa',
        hazard_label_en: 'Speculative hypothesis',
      },
      {
        hazard: 'h-onto',
        confidence: 'confermato',
        tag: 'ONTOLOGIA',
        hazard_label_it: 'Borseggio',
        hazard_label_en: 'Pickpocketing',
      },
      {
        hazard: 'h-ctx',
        confidence: 'plausibile',
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
    setup(makePoi({ confidence: 'plausibile' }));
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Plausibile');
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

  it('footer: azioni non operative presenti ("Segnala errore" / "Esporta scheda"), disabilitate in questa iterazione', () => {
    setup(makePoi());
    const buttons: HTMLButtonElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('.cra-detail-footer button'),
    );
    expect(buttons).toHaveLength(2);
    expect(buttons.every((b) => b.disabled)).toBe(true);
    const text = fixture.nativeElement.textContent;
    expect(text).toContain('Segnala errore');
    expect(text).toContain('Esporta scheda');
    expect(text).not.toContain('Assegna pattuglia');
  });
});
