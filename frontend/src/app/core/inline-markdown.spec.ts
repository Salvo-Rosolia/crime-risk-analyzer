import {
  MdPart,
  MdSegment,
  parseInlineMarkdown,
  parseInlineMarkdownWithSlots,
} from '@core/inline-markdown';
import { withIstatProseIndicators } from '@core/ui-helpers';

/** Compact shape: text, `b:` bold, `i:` italic, `bi:` both. */
const f = (s: string): string[] =>
  parseInlineMarkdown(s).map(
    (x: MdSegment) => `${x.bold ? 'b' : ''}${x.italic ? 'i' : ''}:${x.text}`,
  );
const plain = (s: string): string =>
  parseInlineMarkdown(s)
    .map((x) => x.text)
    .join('');

describe('parseInlineMarkdown', () => {
  it('bold with ** and __, italic with * and _', () => {
    expect(f('a **b** c')).toEqual([':a ', 'b:b', ': c']);
    expect(f('a __b__ c')).toEqual([':a ', 'b:b', ': c']);
    expect(f('a *b* c')).toEqual([':a ', 'i:b', ': c']);
    expect(f('a _b_ c')).toEqual([':a ', 'i:b', ': c']);
  });

  it('basic nesting', () => {
    expect(f('***x***')).toEqual(['bi:x']);
    expect(f('**_x_**')).toEqual(['bi:x']);
    expect(f('**a *b* c**')).toEqual(['b:a ', 'bi:b', 'b: c']);
    expect(f('*a **b** c*')).toEqual(['i:a ', 'bi:b', 'i: c']);
  });

  it('unpaired or isolated markers stay text', () => {
    expect(f('a * b')).toEqual([':a * b']);
    expect(f('a *b')).toEqual([':a *b']);
    expect(f('2 * 3 * 4')).toEqual([':2 * 3 * 4']);
    expect(f('**aperto')).toEqual([':**aperto']);
    expect(f('a_')).toEqual([':a_']);
  });

  it('_ inside a word (snake_case) is not italic', () => {
    expect(f('un nome_di_variabile qui')).toEqual([':un nome_di_variabile qui']);
    expect(f('a snake_case_ok e _vero_')).toEqual([':a snake_case_ok e ', 'i:vero']);
  });

  it('apostrophes and quotes intact', () => {
    expect(plain("l’**area** dell'“arte”")).toBe("l’area dell'“arte”");
    expect(f('l’**area**')).toEqual([':l’', 'b:area']);
  });

  it('lists: bullet in place of * and -, numbered ones kept, no italic', () => {
    expect(plain('* uno\n- due\n• tre\n1. quattro')).toBe('• uno\n• due\n• tre\n1. quattro');
    expect(f('* **Criminalità** – x')).toEqual([':• ', 'b:Criminalità', ': – x']);
    expect(f('* a\n* b')).toEqual([':• a\n• b']);
  });

  it('hard break (trailing spaces) without odd spaces', () => {
    expect(plain('riga uno  \nriga due')).toBe('riga uno\nriga due');
  });

  it('headings: # removed and line in bold', () => {
    expect(f('## Titolo\ntesto')).toEqual(['b:Titolo', ':\ntesto']);
  });

  it('real prose', () => {
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

  it('bold that closes right after an italic (final ***)', () => {
    expect(f('**Rischi: *Furto*, *Danno***')).toEqual([
      'b:Rischi: ',
      'bi:Furto',
      'b:, ',
      'bi:Danno',
    ]);
    expect(plain('**Rischi: *Furto*, *Danno***')).toBe('Rischi: Furto, Danno');
  });

  it('*** terminators in other nested combinations', () => {
    expect(f('***a** b*')).toEqual(['bi:a', 'i: b']);
    expect(f('***a* b**')).toEqual(['bi:a', 'b: b']);
    expect(f('*a **b***')).toEqual(['i:a ', 'bi:b']);
    expect(f('__a _b___')).toEqual(['b:a ', 'bi:b']);
    expect(f('x ***a*** y')).toEqual([':x ', 'bi:a', ': y']);
  });

  it('unpaired or isolated *** stay text', () => {
    expect(f('a *** b')).toEqual([':a *** b']);
    expect(f('***aperto')).toEqual([':***aperto']);
  });

  it('alternating markers in quantity: linear time, not quadratic', () => {
    const t0 = Date.now();
    const out = parseInlineMarkdown('*_'.repeat(40_000));
    expect(Date.now() - t0).toBeLessThan(2000);
    expect(out.length).toBeGreaterThan(0);
  });

  it('empty text: no segments', () => {
    expect(parseInlineMarkdown('')).toEqual([]);
  });
});

describe('parseInlineMarkdownWithSlots', () => {
  it('the slots return to their place, in the style in which they fall', () => {
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

  it('the slot after the closing does not split the pair', () => {
    const out = parseInlineMarkdownWithSlots<string>(['L’**impennata**', { slot: 'S' }, ', ok']);
    expect(out.some((p) => 'text' in p && p.text.includes('*'))).toBe(false);
    expect(out[1]).toEqual({ text: 'impennata', bold: true, italic: false });
    expect(out[2]).toEqual({ slot: 'S' });
  });

  describe('U+E000 in the model text (the internal placeholder must not pass)', () => {
    const PUA = '\uE000';
    const compact = (out: MdPart<string>[]): string[] =>
      out.map((p) => ('slot' in p ? `[${p.slot}]` : p.text));

    it('with two candidates the indicators stay in place, the character is removed', () => {
      const out = parseInlineMarkdownWithSlots<string>([
        `Il furto ${PUA} qui e il${PUA} danno`,
        { slot: 'S' },
        ' e ',
        { slot: 'T' },
      ]);
      expect(compact(out)).toEqual(['Il furto  qui e il danno', '[S]', ' e ', '[T]']);
    });

    it('with a single candidate no extra slot is born nor undefined', () => {
      const out = parseInlineMarkdownWithSlots<string>([`a${PUA}b${PUA}c`, { slot: 'S' }, 'd']);
      expect(compact(out)).toEqual(['abc', '[S]', 'd']);
    });

    it('without candidates the text comes out without the character and without slots', () => {
      const out = parseInlineMarkdownWithSlots<string>([`solo ${PUA}testo${PUA}`]);
      expect(compact(out)).toEqual(['solo testo']);
    });

    it('even inside a style, and never an undefined slot', () => {
      const out = parseInlineMarkdownWithSlots<string>([
        `**gras${PUA}setto${PUA}**`,
        { slot: 'S' },
        `${PUA}${PUA}`,
      ]);
      expect(out).toEqual([{ text: 'grassetto', bold: true, italic: false }, { slot: 'S' }]);
    });
  });

  describe('the slot is transparent to the flanking of the closing markers (#387)', () => {
    const compact = (out: MdPart<string>[]): string[] =>
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
    ])(
      '%s followed by a slot renders the style and keeps the slot in its place',
      (md, expected) => {
        expect(
          compact(parseInlineMarkdownWithSlots<string>([md, { slot: 'S' }, ' è alto'])),
        ).toEqual(expected);
      },
    );

    it('slot at the end of the text and slot before the closing marker', () => {
      expect(compact(parseInlineMarkdownWithSlots<string>(['_Furto_', { slot: 'S' }]))).toEqual([
        'i:Furto',
        '[S]',
      ]);
      expect(
        compact(parseInlineMarkdownWithSlots<string>(['**Furto', { slot: 'S' }, '** x'])),
      ).toEqual(['b:Furto', '[S]', ': x']);
    });

    it('integration with withIstatProseIndicators: no slot lost or moved', () => {
      const ind = { data: 'D', arrow: null, trend: 't', note: null };
      const cand = [{ hazardLabel: 'Furto di rame', item: 'THEFT', indicator: ind }];
      const cases: [string, string[]][] = [
        ['Il _Furto di rame_ è alto.', [':Il ', 'i:Furto di rame', '[S]', ': è alto.']],
        ['Il __Furto di rame__ è alto.', [':Il ', 'b:Furto di rame', '[S]', ': è alto.']],
        ['Il **“Furto di rame”** è alto.', [':Il ', 'b:“Furto di rame”', '[S]', ': è alto.']],
        ['Il *“Furto di rame”* è alto.', [':Il ', 'i:“Furto di rame”', '[S]', ': è alto.']],
        ['x _Furto di rame_', [':x ', 'i:Furto di rame', '[S]']],
      ];
      for (const [prose, expected] of cases) {
        const parts = withIstatProseIndicators(prose, cand).map((s) =>
          s.kind === 'text' ? s.text : { slot: 'S' },
        );
        expect(compact(parseInlineMarkdownWithSlots<string>(parts))).toEqual(expected);
      }
    });
  });
});
