/**
 * Markdown INLINE della prosa della narrativa, reso come segmenti (niente HTML, niente librerie):
 * `**x**`/`__x__` grassetto, `*x*`/`_x_` corsivo, `***x***` entrambi, annidamento e terminatori
 * combinati (`**a *b***`, `***a** b*`), con le regole di «apertura/chiusura» di CommonMark sulle
 * sequenze di `*` e `_`. Per riga: elenchi («* », «- », «• », «1. ») con un pallino, titoli `#` in
 * grassetto, spazi finali (hard break markdown) tolti. Un marcatore non accoppiato resta testo;
 * `_` dentro una parola (snake_case) non è corsivo; apostrofi e virgolette non sono toccati.
 */
export interface MdSegment {
  text: string;
  bold: boolean;
  italic: boolean;
}

/** Una sequenza di testo o di marcatori (`*`/`_` consecutivi) con lo stile che le si accumula. */
interface Token {
  /** Testo (se `delim` è falso) oppure il solo carattere del marcatore. */
  text: string;
  delim: boolean;
  /** Marcatori ancora liberi; scende man mano che vengono accoppiati. */
  len: number;
  /** Lunghezza originale della sequenza (serve alla «regola del 3»). */
  origLen: number;
  canOpen: boolean;
  canClose: boolean;
  bold: boolean;
  italic: boolean;
}

const isWhitespace = (c: string | undefined): boolean => c === undefined || /\s/u.test(c);
const isPunctuation = (c: string | undefined): boolean =>
  c !== undefined && /[\p{P}\p{S}]/u.test(c);

/** Carattere (code point intero) che precede l'indice `i`, o `undefined` a inizio testo. */
function charBefore(s: string, i: number): string | undefined {
  if (i <= 0) return undefined;
  const low = s.charCodeAt(i - 1);
  return low >= 0xdc00 && low <= 0xdfff && i >= 2 ? s.slice(i - 2, i) : s[i - 1];
}

/** Carattere (code point intero) che inizia all'indice `i`, o `undefined` a fine testo. */
function charAt(s: string, i: number): string | undefined {
  const cp = s.codePointAt(i);
  return cp === undefined ? undefined : String.fromCodePoint(cp);
}

/** Spezza la riga in testo e sequenze di marcatori, con chi può aprire/chiudere (CommonMark). */
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
    // Gli slot (indicatori ISTAT) seguono i marcatori di chiusura (`**“x”**<slot>`): per decidere
    // chi apre/chiude sono trasparenti, come se non ci fossero.
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
      // `_` non apre/chiude dentro una parola (snake_case): vale solo ai bordi o con punteggiatura.
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
 * Accoppia le sequenze di marcatori (algoritmo di CommonMark): per ogni chiusura cerca a ritroso
 * l'apertura compatibile; ogni coppia consuma 2 marcatori (grassetto) se entrambe ne hanno almeno
 * 2, altrimenti 1 (corsivo), e applica lo stile a tutto ciò che sta in mezzo. Quel che avanza di
 * una sequenza continua a poter accoppiarsi (`***x***`, `**a *b***`). I marcatori mai accoppiati
 * restano testo.
 */
function pairEmphasis(toks: Token[]): void {
  // Come `openers_bottom` di CommonMark: per ogni classe di chiusura (carattere, può aprire, lunghezza
  // mod 3) l'indice sotto cui si è già visto che non c'è alcuna apertura, per non riscansionare.
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
        // Regola del 3: se uno dei due può anche fare l'altro ruolo, la somma delle lunghezze
        // originali non può essere multipla di 3 (salvo lo siano entrambe).
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
        if (toks[k].delim) toks[k].canOpen = false; // dentro una coppia già chiusa: non apre più
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

/**
 * Segnaposto interno di uno slot: un carattere dell'area privata Unicode, scritto come escape
 * (un editor o un formatter non può perderlo, e `split('')` non spezzerebbe tutto). Il testo in
 * ingresso viene ripulito dal carattere, così gli slot trovati corrispondono sempre a quelli dati.
 */
const SLOT = '\uE000';

/**
 * Come `parseInlineMarkdown` ma su una sequenza di testi e slot: il markdown è interpretato
 * sull'intero testo (una coppia `**…**` che contiene uno slot resta una coppia) e poi gli slot
 * vengono rimessi al loro posto, dentro lo stile in cui cadono.
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
