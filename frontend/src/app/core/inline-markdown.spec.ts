import {
  MdPart,
  MdSegment,
  parseInlineMarkdown,
  parseInlineMarkdownWithSlots,
} from '@core/inline-markdown';
import { withIstatProseIndicators } from '@core/ui-helpers';

/** Forma compatta: testo, `b:` grassetto, `i:` corsivo, `bi:` entrambi. */
const f = (s: string): string[] =>
  parseInlineMarkdown(s).map(
    (x: MdSegment) => `${x.bold ? 'b' : ''}${x.italic ? 'i' : ''}:${x.text}`,
  );
const plain = (s: string): string =>
  parseInlineMarkdown(s)
    .map((x) => x.text)
    .join('');

describe('parseInlineMarkdown', () => {
  it('grassetto con ** e __, corsivo con * e _', () => {
    expect(f('a **b** c')).toEqual([':a ', 'b:b', ': c']);
    expect(f('a __b__ c')).toEqual([':a ', 'b:b', ': c']);
    expect(f('a *b* c')).toEqual([':a ', 'i:b', ': c']);
    expect(f('a _b_ c')).toEqual([':a ', 'i:b', ': c']);
  });

  it('annidamento base', () => {
    expect(f('***x***')).toEqual(['bi:x']);
    expect(f('**_x_**')).toEqual(['bi:x']);
    expect(f('**a *b* c**')).toEqual(['b:a ', 'bi:b', 'b: c']);
    expect(f('*a **b** c*')).toEqual(['i:a ', 'bi:b', 'i: c']);
  });

  it('marcatori non accoppiati o isolati restano testo', () => {
    expect(f('a * b')).toEqual([':a * b']);
    expect(f('a *b')).toEqual([':a *b']);
    expect(f('2 * 3 * 4')).toEqual([':2 * 3 * 4']);
    expect(f('**aperto')).toEqual([':**aperto']);
    expect(f('a_')).toEqual([':a_']);
  });

  it('_ dentro una parola (snake_case) non è corsivo', () => {
    expect(f('un nome_di_variabile qui')).toEqual([':un nome_di_variabile qui']);
    expect(f('a snake_case_ok e _vero_')).toEqual([':a snake_case_ok e ', 'i:vero']);
  });

  it('apostrofi e virgolette intatti', () => {
    expect(plain("l’**area** dell'“arte”")).toBe("l’area dell'“arte”");
    expect(f('l’**area**')).toEqual([':l’', 'b:area']);
  });

  it('elenchi: pallino al posto di * e -, numerati conservati, niente corsivo', () => {
    expect(plain('* uno\n- due\n• tre\n1. quattro')).toBe('• uno\n• due\n• tre\n1. quattro');
    expect(f('* **Criminalità** – x')).toEqual([':• ', 'b:Criminalità', ': – x']);
    expect(f('* a\n* b')).toEqual([':• a\n• b']);
  });

  it('hard break (spazi finali) senza spazi strani', () => {
    expect(plain('riga uno  \nriga due')).toBe('riga uno\nriga due');
  });

  it('titoli: # tolti e riga in grassetto', () => {
    expect(f('## Titolo\ntesto')).toEqual(['b:Titolo', ':\ntesto']);
  });

  it('prosa reale', () => {
    const p =
      'L’**impennata della criminalità** è evidente, con *Aggressione a scopo di furto* e altro.';
    expect(f(p)).toEqual([
      ':L’',
      'b:impennata della criminalità',
      ': è evidente, con ',
      'i:Aggressione a scopo di furto',
      ': e altro.',
    ]);
    expect(plain(p)).not.toContain('*');
  });

  it('grassetto che si chiude subito dopo un corsivo (*** finale)', () => {
    expect(f('**Rischi: *Furto*, *Danno***')).toEqual([
      'b:Rischi: ',
      'bi:Furto',
      'b:, ',
      'bi:Danno',
    ]);
    expect(plain('**Rischi: *Furto*, *Danno***')).toBe('Rischi: Furto, Danno');
  });

  it('terminatori *** in altre combinazioni annidate', () => {
    expect(f('***a** b*')).toEqual(['bi:a', 'i: b']);
    expect(f('***a* b**')).toEqual(['bi:a', 'b: b']);
    expect(f('*a **b***')).toEqual(['i:a ', 'bi:b']);
    expect(f('__a _b___')).toEqual(['b:a ', 'bi:b']);
    expect(f('x ***a*** y')).toEqual([':x ', 'bi:a', ': y']);
  });

  it('*** senza chiusura o isolati restano testo', () => {
    expect(f('a *** b')).toEqual([':a *** b']);
    expect(f('***aperto')).toEqual([':***aperto']);
  });

  it('marcatori alternati in quantità: tempo lineare, niente quadratico', () => {
    const t0 = Date.now();
    const out = parseInlineMarkdown('*_'.repeat(40_000));
    expect(Date.now() - t0).toBeLessThan(2000);
    expect(out.length).toBeGreaterThan(0);
  });

  it('testo vuoto: nessun segmento', () => {
    expect(parseInlineMarkdown('')).toEqual([]);
  });
});

describe('parseInlineMarkdownWithSlots', () => {
  it('gli slot tornano al loro posto, nello stile in cui cadono', () => {
    const out = parseInlineMarkdownWithSlots<string>([
      'il **furto',
      { slot: 'S' },
      ' qui** e *x*',
      { slot: 'T' },
      ' fine',
    ]);
    expect(out).toEqual([
      { text: 'il ', bold: false, italic: false },
      { text: 'furto', bold: true, italic: false },
      { slot: 'S' },
      { text: ' qui', bold: true, italic: false },
      { text: ' e ', bold: false, italic: false },
      { text: 'x', bold: false, italic: true },
      { slot: 'T' },
      { text: ' fine', bold: false, italic: false },
    ]);
  });

  it('lo slot dopo la chiusura non spezza la coppia', () => {
    const out = parseInlineMarkdownWithSlots<string>(['L’**impennata**', { slot: 'S' }, ', ok']);
    expect(out.some((p) => 'text' in p && p.text.includes('*'))).toBe(false);
    expect(out[1]).toEqual({ text: 'impennata', bold: true, italic: false });
    expect(out[2]).toEqual({ slot: 'S' });
  });

  describe('U+E000 nel testo del modello (il segnaposto interno non deve passare)', () => {
    const PUA = '\uE000';
    const forma = (out: MdPart<string>[]): string[] =>
      out.map((p) => ('slot' in p ? `[${p.slot}]` : p.text));

    it('con due candidati gli indicatori restano al loro posto, il carattere è tolto', () => {
      const out = parseInlineMarkdownWithSlots<string>([
        `Il furto ${PUA} qui e il${PUA} danno`,
        { slot: 'S' },
        ' e ',
        { slot: 'T' },
      ]);
      expect(forma(out)).toEqual(['Il furto  qui e il danno', '[S]', ' e ', '[T]']);
    });

    it('con un solo candidato non nasce nessuno slot in eccesso né undefined', () => {
      const out = parseInlineMarkdownWithSlots<string>([`a${PUA}b${PUA}c`, { slot: 'S' }, 'd']);
      expect(forma(out)).toEqual(['abc', '[S]', 'd']);
    });

    it('senza candidati il testo esce senza il carattere e senza slot', () => {
      const out = parseInlineMarkdownWithSlots<string>([`solo ${PUA}testo${PUA}`]);
      expect(forma(out)).toEqual(['solo testo']);
    });

    it('anche dentro uno stile, e mai uno slot undefined', () => {
      const out = parseInlineMarkdownWithSlots<string>([
        `**gras${PUA}setto${PUA}**`,
        { slot: 'S' },
        `${PUA}${PUA}`,
      ]);
      expect(out).toEqual([{ text: 'grassetto', bold: true, italic: false }, { slot: 'S' }]);
    });
  });

  describe('lo slot è trasparente al flanking dei marcatori di chiusura (#387)', () => {
    const forma = (out: MdPart<string>[]): string[] =>
      out.map((p) =>
        'slot' in p ? `[${p.slot}]` : `${p.bold ? 'b' : ''}${p.italic ? 'i' : ''}:${p.text}`,
      );

    it.each([
      ['_Furto di rame_', ['i:Furto di rame', '[S]', ': è alto']],
      ['__Furto di rame__', ['b:Furto di rame', '[S]', ': è alto']],
      ['**“Furto di rame”**', ['b:“Furto di rame”', '[S]', ': è alto']],
      ['*“Furto di rame”*', ['i:“Furto di rame”', '[S]', ': è alto']],
      ['**Furto di rame (rame)**', ['b:Furto di rame (rame)', '[S]', ': è alto']],
      ['x _Furto di rame_', [':x ', 'i:Furto di rame', '[S]', ': è alto']],
    ])('%s seguito da uno slot rende lo stile e tiene lo slot al suo posto', (md, atteso) => {
      expect(forma(parseInlineMarkdownWithSlots<string>([md, { slot: 'S' }, ' è alto']))).toEqual(
        atteso,
      );
    });

    it('slot a fine testo e slot prima del marcatore di chiusura', () => {
      expect(forma(parseInlineMarkdownWithSlots<string>(['_Furto_', { slot: 'S' }]))).toEqual([
        'i:Furto',
        '[S]',
      ]);
      expect(
        forma(parseInlineMarkdownWithSlots<string>(['**Furto', { slot: 'S' }, '** x'])),
      ).toEqual(['b:Furto', '[S]', ': x']);
    });

    it('integrazione con withIstatProseIndicators: nessuno slot perso o spostato', () => {
      const ind = { dati: 'D', freccia: null, tendenza: 't', nota: null };
      const cand = [{ hazardLabel: 'Furto di rame', voce: 'THEFT', indicator: ind }];
      const casi: [string, string[]][] = [
        ['Il _Furto di rame_ è alto.', [':Il ', 'i:Furto di rame', '[S]', ': è alto.']],
        ['Il __Furto di rame__ è alto.', [':Il ', 'b:Furto di rame', '[S]', ': è alto.']],
        ['Il **“Furto di rame”** è alto.', [':Il ', 'b:“Furto di rame”', '[S]', ': è alto.']],
        ['Il *“Furto di rame”* è alto.', [':Il ', 'i:“Furto di rame”', '[S]', ': è alto.']],
        ['x _Furto di rame_', [':x ', 'i:Furto di rame', '[S]']],
      ];
      for (const [prosa, atteso] of casi) {
        const parts = withIstatProseIndicators(prosa, cand).map((s) =>
          s.kind === 'text' ? s.text : { slot: 'S' },
        );
        expect(forma(parseInlineMarkdownWithSlots<string>(parts))).toEqual(atteso);
      }
    });
  });
});
