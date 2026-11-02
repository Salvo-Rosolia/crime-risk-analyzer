import { readdirSync, readFileSync } from 'fs';
import { join, sep } from 'path';

/**
 * Regex lookbehind (`(?<=` / `(?<!`) does not exist on Safari 16.0-16.3 (and the iOS equivalent), which
 * Angular 20 still declares supported. Built with `new RegExp(string)` the build does not
 * warn: the SyntaxError fires at runtime and, inside a `computed`, the panel does not render (#387).
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

describe('Safari 16.0-16.3 compatibility: no lookbehind in regexes (#387)', () => {
  it('no non-spec source uses (?<= or (?<!', () => {
    const offenders = sourceFiles(ROOT).filter((f) => LOOKBEHIND.test(readFileSync(f, 'utf-8')));
    expect(offenders).toEqual([]);
  });

  it('the scan really sees the sources (guard against a false green)', () => {
    const files = sourceFiles(ROOT).map((f) => f.split(sep).join('/'));
    expect(files.some((f) => f.endsWith('/core/ui-helpers.ts'))).toBe(true);
    expect(files.some((f) => f.endsWith('/core/inline-markdown.ts'))).toBe(true);
  });
});
