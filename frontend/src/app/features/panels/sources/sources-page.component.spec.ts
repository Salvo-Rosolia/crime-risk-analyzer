import { ComponentFixture, TestBed } from '@angular/core/testing';
import { computed, signal } from '@angular/core';
import { ApiService } from '@core/api/api.service';
import { SourcesBusy, SourcesReport, SourcesStore } from '@core/state/sources.store';
import type { SourceProblem, SourcesStatus } from '@core/models/models';
import { SourcesPageComponent } from './sources-page.component';

const status = (kind: 'example' | 'custom', avvisi: SourceProblem[] = []): SourcesStatus => ({
  stato: 'attivo',
  source_set_id: kind === 'example' ? 'example' : 'custom-aaaaaaaaaaaaaaaa',
  scade_tra_secondi: 900,
  set: { kind, classi: 7, selettori_osm: 12, versione_dati: '2024', luoghi: ['Roma'], avvisi },
});

describe('SourcesPageComponent', () => {
  let fixture: ComponentFixture<SourcesPageComponent>;
  let el: HTMLElement;
  const report = signal<SourcesReport | null>(null);
  const message = signal<string | null>(null);
  const busy = signal<SourcesBusy | null>(null);
  const current = signal<SourcesStatus | null>(null);
  const upload = jest.fn();
  const useExample = jest.fn();
  const reset = jest.fn();

  const q = <T extends HTMLElement>(sel: string) => el.querySelector<T>(sel);
  const qa = (sel: string) => Array.from(el.querySelectorAll<HTMLElement>(sel));
  const pick = (id: string, name: string) => {
    const input = q<HTMLInputElement>(`#${id}`)!;
    Object.defineProperty(input, 'files', { value: [new File(['x'], name)], configurable: true });
    input.dispatchEvent(new Event('change'));
    fixture.detectChanges();
  };
  const pickRequired = () => {
    pick('cra-src-ontology', 'o.ttl');
    pick('cra-src-osm_table', 'osm.csv');
    pick('cra-src-data', 'd.csv');
    pick('cra-src-hazard_table', 'h.csv');
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [SourcesPageComponent],
      providers: [
        { provide: ApiService, useValue: { templateUrl: (n: string) => `/t/${n}` } },
        {
          provide: SourcesStore,
          useValue: {
            report,
            message,
            busy,
            status: current,
            indicator: computed(() =>
              current()
                ? { label: 'Personalizzate', kind: 'custom' }
                : { label: 'Predefinite', kind: 'default' },
            ),
            activeWarnings: computed(() => current()?.set?.avvisi ?? []),
            upload,
            useExample,
            reset,
          },
        },
      ],
    });
    report.set(null);
    message.set(null);
    busy.set(null);
    current.set(null);
    upload.mockReset().mockResolvedValue(true);
    useExample.mockReset().mockResolvedValue(true);
    reset.mockReset().mockResolvedValue(true);
    fixture = TestBed.createComponent(SourcesPageComponent);
    el = fixture.nativeElement;
    fixture.detectChanges();
  });

  it('has the Ontologia and Dati sections and the four templates to download', () => {
    expect(qa('h3').map((h) => h.textContent?.trim())).toEqual(['Ontologia', 'Dati']);
    const links = qa('a[download]');
    expect(links.map((a) => a.getAttribute('href'))).toEqual([
      '/t/ontology',
      '/t/osm_table',
      '/t/data',
      '/t/hazard_table',
    ]);
  });

  it('every file has its own legend, closed by default', () => {
    for (const key of ['ontology', 'osm_table', 'data', 'hazard_table', 'boundaries']) {
      const details = q<HTMLDetailsElement>(`[data-slot=${key}] details.cra-legend`);
      expect(details).not.toBeNull();
      expect(details!.open).toBe(false);
      expect(details!.querySelector('summary')).not.toBeNull();
    }
  });

  it('the legends list the columns and the allowed values', () => {
    const hazard = q(`[data-slot=hazard_table] details.cra-legend`)!;
    expect(hazard.textContent).toContain('corrispondenza');
    for (const value of ['esatta', 'piu_larga', 'piu_stretta']) {
      expect(hazard.textContent).toContain(value);
    }
    expect(q('[data-slot=data] details.cra-legend')!.textContent).toContain('tasso_sotto_soglia');
    expect(q('[data-slot=osm_table] details.cra-legend')!.textContent).toContain('amenity=bank');
    expect(q('[data-slot=boundaries] details.cra-legend')!.textContent).toContain('nome_breve');
    expect(q('[data-slot=ontology] details.cra-legend')!.textContent).toContain('havingHazard');
  });

  it('under Usa l esempio it says what the example loads', () => {
    const note = q('.cra-example-note')!;
    expect(note.textContent).toContain('non TERMINUS');
    expect(note.textContent).toContain('Roma, Milano e Napoli');
    expect(note.previousElementSibling?.classList).toContain('cra-sources-quick');
  });

  it('explains how the files link to each other', () => {
    const chain = q('.cra-chain')!;
    expect(chain.textContent).toMatch(/OSM[\s\S]*classe[\s\S]*hazard[\s\S]*voce[\s\S]*dati/);
  });

  it('Carica stays disabled until the mandatory files are there', () => {
    const btn = q<HTMLButtonElement>('button[type=submit]')!;
    expect(btn.disabled).toBe(true);
    pick('cra-src-ontology', 'o.ttl');
    expect(btn.disabled).toBe(true);
    pickRequired();
    expect(btn.disabled).toBe(false);
  });

  it('the upload sends the files to the store', async () => {
    pickRequired();
    q<HTMLInputElement>('#cra-src-namespace')!.value = 'http://x/#';
    q<HTMLInputElement>('#cra-src-namespace')!.dispatchEvent(new Event('input'));
    q<HTMLFormElement>('form')!.dispatchEvent(new Event('submit'));
    await fixture.whenStable();
    const arg = upload.mock.calls[0][0];
    expect(arg.ontology.name).toBe('o.ttl');
    expect(arg.hazard_table.name).toBe('h.csv');
    expect(arg.boundaries).toBeNull();
    expect(arg.vocabulary.namespace).toBe('http://x/#');
  });

  it('Usa l esempio and Torna al default call the store', async () => {
    qa('button')
      .find((b) => b.textContent?.includes("Usa l'esempio"))!
      .click();
    await fixture.whenStable();
    qa('button')
      .find((b) => b.textContent?.includes('Torna al default'))!
      .click();
    await fixture.whenStable();
    expect(useExample).toHaveBeenCalled();
    expect(reset).toHaveBeenCalled();
  });

  it('with mass vocabulary errors it suggests the Impostazioni avanzate without hiding the errors', () => {
    report.set({
      errors: [
        { code: 'ontologia_senza_restrizioni', file: 'ontology', message: 'nessuna', line: null },
        ...[2, 3, 4].map((line) => ({
          code: 'classe_assente_dall_ontologia',
          file: 'osm_table' as const,
          message: `la classe ${line} non esiste`,
          line,
        })),
      ],
      warnings: [],
    });
    fixture.detectChanges();
    const hint = q('.cra-sources-hint')!;
    expect(hint.textContent).toContain("Impostazioni avanzate dell'ontologia");
    expect(hint.textContent).toContain('namespace');
    expect(qa('.cra-problem-error').length).toBe(4);
  });

  it('an error of another kind does not show the vocabulary hint', () => {
    report.set({
      errors: [{ code: 'colonna_mancante', file: 'data', message: 'manca anno', line: 1 }],
      warnings: [],
    });
    fixture.detectChanges();
    expect(q('.cra-sources-hint')).toBeNull();
  });

  it('shortens the technical dump of the unreadable ontology, keeping line and cause', () => {
    const dump =
      "ontologia non leggibile come turtle: at line 2 of <>: Bad syntax (Keyword 'this' was ancient N3.) at ^ in:\n\"b'@prefix : <x> .\\n '^b'this is not turtle ;;;\\n'\"";
    report.set({
      errors: [{ code: 'ontologia_illeggibile', file: 'ontology', message: dump, line: null }],
      warnings: [],
    });
    fixture.detectChanges();
    const text = q('[data-slot=ontology] .cra-problem-error')!.textContent!;
    expect(text).toContain('at line 2');
    expect(text).toContain('Bad syntax');
    expect(text).not.toContain("b'@prefix");
  });

  it('truncates a very long message', () => {
    report.set({
      errors: [{ code: 'x', file: 'data', message: 'a'.repeat(900), line: 1 }],
      warnings: [],
    });
    fixture.detectChanges();
    expect(q('[data-slot=data] .cra-problem-error')!.textContent!.length).toBeLessThan(400);
  });

  it('the summary labels the data version', () => {
    current.set(status('custom'));
    fixture.detectChanges();
    expect(q('.cra-active-summary')?.textContent).toContain('versione dei dati 2024');
  });

  it('shows the check errors and warnings under the right file, with the line', () => {
    report.set({
      errors: [{ code: 'c', file: 'data', message: 'Colonna mancante: anno', line: 1 }],
      warnings: [{ code: 'w', file: 'osm_table', message: 'Selettore duplicato', line: 4 }],
    });
    fixture.detectChanges();
    const dataSlot = q('[data-slot=data]')!;
    expect(dataSlot.textContent).toContain('Colonna mancante: anno');
    expect(dataSlot.textContent).toContain('riga 1');
    expect(dataSlot.querySelector('.cra-problem-error')).not.toBeNull();
    const osm = q('[data-slot=osm_table]')!;
    expect(osm.querySelector('.cra-problem-warning')?.textContent).toContain('riga 4');
    expect(q('[role=alert]')?.textContent).toContain('non sono stati accettati');
  });

  it('shows the warnings of the active set and its summary', () => {
    current.set(
      status('custom', [
        { code: 'w', file: 'ontology', message: 'Classe senza etichetta', line: null },
      ]),
    );
    fixture.detectChanges();
    expect(q('.cra-active-summary')?.textContent).toContain('Personalizzate');
    expect(q('.cra-active-summary')?.textContent).toContain('7 classi');
    expect(q('[data-slot=ontology]')?.textContent).toContain('Classe senza etichetta');
  });

  it('shows the generic error message of the backend', () => {
    message.set('troppi caricamenti');
    fixture.detectChanges();
    expect(q('[role=alert]')?.textContent).toContain('troppi caricamenti');
  });

  it('Chiudi emits closed', () => {
    const closed = jest.fn();
    fixture.componentInstance.closed.subscribe(closed);
    q<HTMLButtonElement>('button[aria-label="Chiudi"]')!.click();
    expect(closed).toHaveBeenCalledTimes(1);
  });

  it('Esc on the document emits closed (even with the focus on the body)', () => {
    const closed = jest.fn();
    fixture.componentInstance.closed.subscribe(closed);
    (document.activeElement as HTMLElement | null)?.blur();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(closed).toHaveBeenCalledTimes(1);
  });

  it('during an operation Chiudi is disabled and Esc is ignored', () => {
    const closed = jest.fn();
    fixture.componentInstance.closed.subscribe(closed);
    busy.set('upload');
    fixture.detectChanges();
    expect(q<HTMLButtonElement>('button[aria-label="Chiudi"]')!.disabled).toBe(true);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(closed).not.toHaveBeenCalled();
  });

  it('warns that changing the sources clears the analyses', () => {
    expect(el.textContent).toContain('Cambiando le fonti le analisi in corso verranno azzerate');
  });

  it('announces the operation in progress (aria-busy + live region)', () => {
    expect(q('[role=status]')!.textContent!.trim()).toBe('');
    busy.set('upload');
    fixture.detectChanges();
    expect(q('[role=dialog]')!.getAttribute('aria-busy')).toBe('true');
    expect(q('[role=status]')!.textContent).toContain('Controllo in corso');
  });

  it('a problem without a visible slot ends up in the general list', () => {
    report.set({
      errors: [{ code: 'x', file: 'altro' as never, message: 'File non previsto', line: null }],
      warnings: [],
    });
    fixture.detectChanges();
    expect(q('.cra-problems-general')!.textContent).toContain('File non previsto');
  });

  it('a rejection with only warnings (empty errors) still shows the outcome', () => {
    report.set({
      errors: [],
      warnings: [{ code: 'w', file: 'data', message: 'Riga vuota', line: 2 }],
    });
    fixture.detectChanges();
    expect(q('[role=alert]')).not.toBeNull();
    expect(q('[data-slot=data]')!.textContent).toContain('Riga vuota');
  });

  describe('focus', () => {
    it('the focus enters the dialog on opening', async () => {
      await fixture.whenStable();
      expect(document.activeElement).toBe(q('[role=dialog]'));
    });

    it('Tab from the last element goes back to the first, Shift+Tab from the first goes to the last', () => {
      const focusables = qa('button:not([disabled]), input, summary, a[href]') as HTMLElement[];
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      last.focus();
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', cancelable: true }));
      expect(document.activeElement).toBe(first);
      first.focus();
      document.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, cancelable: true }),
      );
      expect(document.activeElement).toBe(last);
    });

    it('Tab with the focus outside the dialog brings it back in', () => {
      (document.activeElement as HTMLElement | null)?.blur();
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', cancelable: true }));
      expect(el.contains(document.activeElement)).toBe(true);
    });

    it('on closing the focus goes back to whoever opened the page', () => {
      const opener = document.createElement('button');
      document.body.appendChild(opener);
      fixture.destroy();
      opener.focus();
      const again = TestBed.createComponent(SourcesPageComponent);
      again.detectChanges();
      again.destroy();
      expect(document.activeElement).toBe(opener);
      opener.remove();
    });
  });

  it('during an operation the buttons are disabled', () => {
    busy.set('example');
    fixture.detectChanges();
    expect(qa('button').filter((b) => b.textContent?.includes("Usa l'esempio"))[0]).toHaveProperty(
      'disabled',
      true,
    );
  });
});
