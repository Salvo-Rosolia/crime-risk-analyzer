/**
 * Markdown INLINE della prosa della narrativa, reso come segmenti (niente HTML, niente librerie):
 * `**x**`/`__x__` grassetto, `*x*`/`_x_` corsivo, `***x***` entrambi, annidamento base. Per riga:
 * elenchi («* », «- », «• », «1. ») con un pallino, titoli `#` in grassetto, spazi finali (hard
 * break markdown) tolti. Un marcatore non accoppiato resta testo; `_` dentro una parola
 * (snake_case) non è corsivo; apostrofi e virgolette non sono toccati.
 */
export interface MdSegment {
  text: string;
  bold: boolean;
  italic: boolean;
}

const isSpace = (c: string | undefined): boolean => c === undefined || /\s/.test(c);
const isWordChar = (c: string | undefined): boolean => c !== undefined && /[\p{L}\p{N}]/u.test(c);

/** Indice del marcatore di chiusura valido a partire da `from`, o -1. */
function findCloser(s: string, from: number, marker: string): number {
  for (let j = from; j <= s.length - marker.length; j++) {
    if (!s.startsWith(marker, j)) continue;
    if (j === from || isSpace(s[j - 1])) continue; // contenuto vuoto o spazio prima della chiusura
    const next = s[j + marker.length];
    if (marker[0] === '*') {
      // `*` singolo: non fa parte di un `**`; `**`: non è l'inizio di un `***` dentro il contenuto.
      if (marker.length === 1 && (s[j - 1] === '*' || next === '*')) continue;
      if (marker.length === 2 && next === '*' && s[j + 2] !== '*') continue;
    } else if (isWordChar(next) || next === marker[0]) {
      continue; // `_`/`__` chiudono solo a fine parola
    }
    return j;
  }
  return -1;
}

function pushText(out: MdSegment[], text: string, bold: boolean, italic: boolean): void {
  if (!text) return;
  const last = out[out.length - 1];
  if (last && last.bold === bold && last.italic === italic) last.text += text;
  else out.push({ text, bold, italic });
}

function parseInline(s: string, bold: boolean, italic: boolean, out: MdSegment[]): void {
  let buf = '';
  let i = 0;
  while (i < s.length) {
    const c = s[i];
    if (c === '*' || c === '_') {
      const run = s.startsWith(c.repeat(3), i) && c === '*' ? 3 : s.startsWith(c + c, i) ? 2 : 1;
      const marker = c.repeat(run);
      const after = s[i + run];
      const canOpen = !isSpace(after) && after !== c && (c === '*' || !isWordChar(s[i - 1]));
      const close = canOpen ? findCloser(s, i + run, marker) : -1;
      if (close >= 0) {
        pushText(out, buf, bold, italic);
        buf = '';
        const inner = s.slice(i + run, close);
        parseInline(inner, bold || run >= 2, italic || run === 1 || run === 3, out);
        i = close + run;
        continue;
      }
      buf += marker; // non accoppiato: resta testo
      i += run;
      continue;
    }
    buf += c;
    i++;
  }
  pushText(out, buf, bold, italic);
}

const HEADING = /^\s{0,3}#{1,6}\s+(.*)$/;
const BULLET = /^(\s*)([*\-•]|\d{1,2}[.)])\s+(.*)$/;

/** Parsa il testo (più righe) in segmenti stilati; gli a-capo restano nei segmenti di testo. */
export function parseInlineMarkdown(text: string): MdSegment[] {
  const out: MdSegment[] = [];
  const lines = text.split('\n');
  lines.forEach((raw, n) => {
    const line = raw.replace(/\s+$/, '');
    const heading = HEADING.exec(line);
    const bullet = heading ? null : BULLET.exec(line);
    if (heading) {
      parseInline(heading[1], true, false, out);
    } else if (bullet) {
      const marker = /^\d/.test(bullet[2]) ? bullet[2] : '•';
      pushText(out, `${bullet[1]}${marker} `, false, false);
      parseInline(bullet[3], false, false, out);
    } else {
      parseInline(line, false, false, out);
    }
    if (n < lines.length - 1) pushText(out, '\n', false, false);
  });
  return out;
}

/** Segmento di una prosa con «slot» (es. gli indicatori ISTAT) inseriti fra i pezzi di testo. */
export type MdPart<T> = MdSegment | { slot: T };

const SLOT = '';

/**
 * Come `parseInlineMarkdown` ma su una sequenza di testi e slot: il markdown è interpretato
 * sull'intero testo (una coppia `**…**` che contiene uno slot resta una coppia) e poi gli slot
 * vengono rimessi al loro posto, dentro lo stile in cui cadono.
 */
export function parseInlineMarkdownWithSlots<T>(parts: (string | { slot: T })[]): MdPart<T>[] {
  const slots: T[] = [];
  const joined = parts
    .map((p) => {
      if (typeof p === 'string') return p;
      slots.push(p.slot);
      return SLOT;
    })
    .join('');
  const out: MdPart<T>[] = [];
  let k = 0;
  for (const seg of parseInlineMarkdown(joined)) {
    seg.text.split(SLOT).forEach((piece, idx) => {
      if (idx > 0) out.push({ slot: slots[k++] });
      if (piece) out.push({ text: piece, bold: seg.bold, italic: seg.italic });
    });
  }
  return out;
}
