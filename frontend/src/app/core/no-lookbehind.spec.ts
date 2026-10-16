import { readdirSync, readFileSync } from 'fs';
import { join, sep } from 'path';

/**
 * Il lookbehind regex (`(?<=` / `(?<!`) non esiste su Safari 16.0-16.3 (e iOS equivalente), che
 * Angular 20 dichiara ancora supportati. Costruita con `new RegExp(stringa)` la build non
 * avverte: il SyntaxError scatta a runtime e, in un `computed`, il pannello non si rende (#387).
 */
const ROOT = join(__dirname, '..');
const LOOKBEHIND = /\(\?<[=!]/;

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = join(dir, e.name);
    if (e.isDirectory()) return sourceFiles(full);
    return /\.ts$/.test(e.name) && !/\.spec\.ts$/.test(e.name) ? [full] : [];
  });
}

describe('compatibilità Safari 16.0-16.3: niente lookbehind nelle regex (#387)', () => {
  it('nessun sorgente non-spec usa (?<= o (?<!', () => {
    const offenders = sourceFiles(ROOT).filter((f) => LOOKBEHIND.test(readFileSync(f, 'utf-8')));
    expect(offenders).toEqual([]);
  });

  it('la scansione vede davvero i sorgenti (guardia contro un falso verde)', () => {
    const files = sourceFiles(ROOT).map((f) => f.split(sep).join('/'));
    expect(files.some((f) => f.endsWith('/core/ui-helpers.ts'))).toBe(true);
    expect(files.some((f) => f.endsWith('/core/inline-markdown.ts'))).toBe(true);
  });
});
