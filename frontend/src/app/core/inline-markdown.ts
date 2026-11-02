/**
 * INLINE markdown of the narrative prose, rendered as segments (no HTML, no libraries):
 * `**x**`/`__x__` bold, `*x*`/`_x_` italic, `***x***` both, nesting and combined
 * terminators (`**a *b***`, `***a** b*`), with the CommonMark "opening/closing" rules on
 * sequences of `*` and `_`. Per line: lists ("* ", "- ", "• ", "1. ") with a bullet, `#` headings in
 * bold, trailing spaces (markdown hard break) removed. An unpaired marker stays text;
 * `_` inside a word (snake_case) is not italic; apostrophes and quotes are not touched.
 */
export interface MdSegment {
  text: string;
  bold: boolean;
  italic: boolean;
}

/** A run of text or of markers (consecutive `*`/`_`) with the style accumulated on it. */
interface Token {
  /** Text (if `delim` is false) or just the marker character. */
  text: string;
  delim: boolean;
  /** Markers still free; goes down as they get paired. */
  len: number;
  /** Original length of the run (needed by the "rule of 3"). */
  origLen: number;
  canOpen: boolean;
  canClose: boolean;
  bold: boolean;
  italic: boolean;
}

const isWhitespace = (c: string | undefined): boolean => c === undefined || /\s/u.test(c);
const isPunctuation = (c: string | undefined): boolean =>
  c !== undefined && /[\p{P}\p{S}]/u.test(c);

/** Character (whole code point) preceding index `i`, or `undefined` at the start of the text. */
function charBefore(s: string, i: number): string | undefined {
  if (i <= 0) return undefined;
  const low = s.charCodeAt(i - 1);
  return low >= 0xdc00 && low <= 0xdfff && i >= 2 ? s.slice(i - 2, i) : s[i - 1];
}

/** Character (whole code point) starting at index `i`, or `undefined` at the end of the text. */
function charAt(s: string, i: number): string | undefined {
  const cp = s.codePointAt(i);
  return cp === undefined ? undefined : String.fromCodePoint(cp);
}

/** Splits the line into text and marker runs, with who can open/close (CommonMark). */
function tokenize(s: string, bold: boolean, italic: boolean): Token[] {
  const toks: Token[] = [];
  let buf = '';
  const flush = (): void => {
    if (buf) {
      toks.push({
        text: buf,
        delim: false,
        len: 0,
        origLen: 0,
        canOpen: false,
        canClose: false,
        bold,
        italic,
      });
    }
    buf = '';
  };
  let i = 0;
  while (i < s.length) {
    const c = s[i];
    if (c !== '*' && c !== '_') {
      buf += c;
      i++;
      continue;
    }
    let j = i;
    while (s[j] === c) j++;
    flush();
    // The slots (ISTAT indicators) follow the closing markers (`**“x”**<slot>`): to decide
    // who opens/closes they are transparent, as if they were not there.
    let bi = i;
    while (bi > 0 && s[bi - 1] === SLOT) bi--;
    let aj = j;
    while (s[aj] === SLOT) aj++;
    const before = charBefore(s, bi);
    const after = charAt(s, aj);
    const leftFlanking =
      !isWhitespace(after) &&
      (!isPunctuation(after) || isWhitespace(before) || isPunctuation(before));
    const rightFlanking =
      !isWhitespace(before) &&
      (!isPunctuation(before) || isWhitespace(after) || isPunctuation(after));
    toks.push({
      text: c,
      delim: true,
      len: j - i,
      origLen: j - i,
      // `_` does not open/close inside a word (snake_case): it counts only at the edges or with punctuation.
      canOpen: c === '*' ? leftFlanking : leftFlanking && (!rightFlanking || isPunctuation(before)),
      canClose:
        c === '*' ? rightFlanking : rightFlanking && (!leftFlanking || isPunctuation(after)),
      bold,
      italic,
    });
    i = j;
  }
  flush();
  return toks;
}

/**
 * Pairs the marker runs (CommonMark algorithm): for each closer it searches backwards
 * for the compatible opener; each pair consumes 2 markers (bold) if both have at least
 * 2, otherwise 1 (italic), and applies the style to everything in between. What is left of
 * a run can still pair (`***x***`, `**a *b***`). Markers never paired
 * stay text.
 */
function pairEmphasis(toks: Token[]): void {
  // Like CommonMark's `openers_bottom`: for each closer class (character, can open, length
  // mod 3) the index below which it has already been seen that there is no opener, to avoid rescanning.
  const floors = new Map<string, number>();
  for (let c = 0; c < toks.length; c++) {
    const closer = toks[c];
    if (!closer.delim || !closer.canClose) continue;
    while (closer.len > 0) {
      const key = `${closer.text}${closer.canOpen ? 1 : 0}${closer.origLen % 3}`;
      const floor = floors.get(key) ?? -1;
      let o = c - 1;
      for (; o > floor; o--) {
        const cand = toks[o];
        if (!cand.delim || cand.text !== closer.text || cand.len === 0 || !cand.canOpen) continue;
        // Rule of 3: if one of the two can also play the other role, the sum of the original
        // lengths cannot be a multiple of 3 (unless both are).
        const ambiguous = cand.canClose || closer.canOpen;
        const sum = cand.origLen + closer.origLen;
        if (ambiguous && sum % 3 === 0 && !(cand.origLen % 3 === 0 && closer.origLen % 3 === 0)) {
          continue;
        }
        break;
      }
      if (o <= floor) {
        floors.set(key, c - 1);
        break;
      }
      const opener = toks[o];
      const used = opener.len >= 2 && closer.len >= 2 ? 2 : 1;
      for (let k = o + 1; k < c; k++) {
        if (used === 2) toks[k].bold = true;
        else toks[k].italic = true;
        if (toks[k].delim) toks[k].canOpen = false; // inside an already closed pair: it no longer opens
      }
      opener.len -= used;
      closer.len -= used;
    }
  }
}

function pushText(out: MdSegment[], text: string, bold: boolean, italic: boolean): void {
  if (!text) return;
  const last = out[out.length - 1];
  if (last && last.bold === bold && last.italic === italic) last.text += text;
  else out.push({ text, bold, italic });
}

function parseInline(s: string, bold: boolean, italic: boolean, out: MdSegment[]): void {
  const toks = tokenize(s, bold, italic);
  pairEmphasis(toks);
  for (const t of toks) {
    pushText(out, t.delim ? t.text.repeat(t.len) : t.text, t.bold, t.italic);
  }
}

const HEADING = /^\s{0,3}#{1,6}\s+(.*)$/;
const BULLET = /^(\s*)([*\-•]|\d{1,2}[.)])\s+(.*)$/;

/** Parses the text (multiple lines) into styled segments; newlines stay in the text segments. */
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

/** Segment of prose with "slots" (e.g. the ISTAT indicators) inserted between the text pieces. */
export type MdPart<T> = MdSegment | { slot: T };

/**
 * Internal placeholder of a slot: a Unicode private-use character, written as an escape
 * (an editor or a formatter cannot lose it, and `split('')` would not split everything). The
 * input text is cleaned of the character, so the slots found always match the ones given.
 */
const SLOT = '\uE000';

/**
 * Like `parseInlineMarkdown` but on a sequence of texts and slots: the markdown is interpreted
 * on the whole text (a `**…**` pair that contains a slot stays a pair) and then the slots
 * are put back in their place, inside the style in which they fall.
 */
export function parseInlineMarkdownWithSlots<T>(parts: (string | { slot: T })[]): MdPart<T>[] {
  const slots: T[] = [];
  const joined = parts
    .map((p) => {
      if (typeof p === 'string') return p.split(SLOT).join('');
      slots.push(p.slot);
      return SLOT;
    })
    .join('');
  const out: MdPart<T>[] = [];
  let k = 0;
  for (const seg of parseInlineMarkdown(joined)) {
    seg.text.split(SLOT).forEach((piece, idx) => {
      if (idx > 0 && k < slots.length) out.push({ slot: slots[k++] });
      if (piece) out.push({ text: piece, bold: seg.bold, italic: seg.italic });
    });
  }
  return out;
}
