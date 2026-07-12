import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NarrativeSheetComponent } from './narrative-sheet.component';
import type { RiskModel } from '@core/models/models';

const riskModels: RiskModel[] = [
  {
    poi: 'Colosseo',
    risks: [
      { hazard: 'h-spec', confidence: 'speculativo', tag: 'SPECULATIVO', hazard_label_it: 'Ipotesi', hazard_label_en: 'Hypothesis' },
      { hazard: 'h-onto', confidence: 'confermato', tag: 'ONTOLOGIA', hazard_label_it: 'Borseggio', hazard_label_en: 'Pickpocketing' },
      { hazard: 'h-ctx', confidence: 'plausibile', tag: 'CONTESTO', hazard_label_it: 'Contesto', hazard_label_en: 'Context' },
    ],
  },
];

const ANTI_HALLUCINATION_TEXT = 'supporto decisionale · valuta con fonti primarie';

describe('NarrativeSheetComponent', () => {
  let fixture: ComponentFixture<NarrativeSheetComponent>;

  function setup(inputs: {
    citta?: string; zona?: string; narrativa?: string; riskModels?: RiskModel[]; open?: boolean;
  } = {}): void {
    fixture = TestBed.createComponent(NarrativeSheetComponent);
    fixture.componentRef.setInput('citta', inputs.citta ?? 'Roma');
    fixture.componentRef.setInput('zona', inputs.zona ?? 'Colosseo');
    fixture.componentRef.setInput('narrativa', inputs.narrativa ?? 'Testo narrativo di prova.');
    fixture.componentRef.setInput('riskModels', inputs.riskModels ?? riskModels);
    fixture.componentRef.setInput('open', inputs.open ?? true);
    fixture.detectChanges();
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [NarrativeSheetComponent] }).compileComponents();
  });

  it('mostra il titolo con città e zona', () => {
    setup({ citta: 'Milano', zona: 'Duomo' });
    expect(fixture.nativeElement.textContent).toContain('Milano · Duomo');
  });

  it('ACCEPTANCE: il banner anti-hallucination è presente quando aperto', () => {
    setup({ open: true });
    expect(fixture.nativeElement.textContent).toContain(ANTI_HALLUCINATION_TEXT);
  });

  it('ACCEPTANCE (fail-if-removed): il banner anti-hallucination resta presente anche da collassato — non deve mai sparire', () => {
    setup({ open: false });
    expect(fixture.nativeElement.textContent).toContain(ANTI_HALLUCINATION_TEXT);
  });

  it('click sull\'header emette toggleNarrative', () => {
    setup();
    const spy = jest.fn();
    fixture.componentInstance.toggleNarrative.subscribe(spy);
    (fixture.nativeElement.querySelector('.cra-narr-header') as HTMLElement).click();
    expect(spy).toHaveBeenCalled();
  });

  it('click su Rigenera emette regenerate e NON anche toggleNarrative (stopPropagation)', () => {
    setup();
    const toggleSpy = jest.fn();
    const regenSpy = jest.fn();
    fixture.componentInstance.toggleNarrative.subscribe(toggleSpy);
    fixture.componentInstance.regenerate.subscribe(regenSpy);
    (fixture.nativeElement.querySelector('.cra-btn-regen') as HTMLElement).click();
    expect(regenSpy).toHaveBeenCalled();
    expect(toggleSpy).not.toHaveBeenCalled();
  });

  it('da aperto mostra il lead narrativo e le sezioni per fonte in ordine ONTOLOGIA→CONTESTO→SPECULATIVO', () => {
    setup({ open: true, narrativa: 'Il Colosseo presenta rischi noti.' });
    expect(fixture.nativeElement.textContent).toContain('Il Colosseo presenta rischi noti.');
    const tags = fixture.nativeElement.querySelectorAll('.cra-source-tag');
    expect(Array.from(tags).map(t => (t as HTMLElement).textContent?.trim())).toEqual([
      '[ONTOLOGIA]', '[CONTESTO]', '[SPECULATIVO]',
    ]);
    expect(fixture.nativeElement.textContent).toContain('Borseggio');
  });

  it('da collassato non rende il corpo (lead/sezioni nascosti, altezza ridotta)', () => {
    setup({ open: false });
    expect(fixture.nativeElement.querySelector('.cra-narr-body')).toBeNull();
  });

  it('senza risk_models non fallisce e non mostra sezioni', () => {
    expect(() => setup({ riskModels: [] })).not.toThrow();
    expect(fixture.nativeElement.querySelectorAll('.cra-source-tag').length).toBe(0);
  });
});
