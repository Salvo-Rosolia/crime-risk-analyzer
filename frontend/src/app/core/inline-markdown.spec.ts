import {
  MdSegment,
  parseInlineMarkdown,
  parseInlineMarkdownWithSlots,
} from '@core/inline-markdown';

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
});
