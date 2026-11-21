import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { SOURCE_LEGENDS } from './sources-legend';

/**
 * The legend is written by hand; this file is the contract shared with the backend
 * (#538): `backend/tests/sources/test_legend_contract.py` checks that it matches
 * the parser, this spec checks that the legend matches it.
 */
interface ColumnsContract {
  required: string[];
  optional: string[];
}
interface Contract {
  osm_table: ColumnsContract;
  data: ColumnsContract;
  hazard_table: ColumnsContract;
  boundaries: ColumnsContract;
  values: { corrispondenza: string[]; tipo: string[] };
}

const contract: Contract = JSON.parse(
  readFileSync(join(__dirname, 'sources-contract.json'), 'utf-8'),
) as Contract;

const FILES = ['osm_table', 'data', 'hazard_table', 'boundaries'] as const;

describe('sources legend vs backend contract', () => {
  it.each(FILES)('%s: the legend lists exactly the contract columns', (key) => {
    const names = SOURCE_LEGENDS[key].columns.map((c) => c.name);
    expect([...names].sort()).toEqual(
      [...contract[key].required, ...contract[key].optional].sort(),
    );
  });

  it.each(FILES)('%s: only the optional columns are marked as optional', (key) => {
    const optional = SOURCE_LEGENDS[key].columns.filter((c) => c.optional).map((c) => c.name);
    expect([...optional].sort()).toEqual([...contract[key].optional].sort());
  });

  it('hazard_table: the legend lists exactly the allowed values of corrispondenza', () => {
    const column = SOURCE_LEGENDS.hazard_table.columns.find((c) => c.name === 'corrispondenza')!;
    // The text reads "esatta (...), piu_larga (...), piu_stretta (...)": the values are the
    // words that open each item.
    const listed = [...column.values!.matchAll(/(?:^|, )([a-z_]+)(?= \()/g)].map((m) => m[1]);
    expect([...listed].sort()).toEqual([...contract.values.corrispondenza].sort());
  });

  it('boundaries: the legend lists exactly the allowed values of tipo', () => {
    const column = SOURCE_LEGENDS.boundaries.columns.find((c) => c.name === 'tipo')!;
    const listed = column.values!.split(' oppure ');
    expect([...listed].sort()).toEqual([...contract.values.tipo].sort());
  });

  it('each CSV legend example has one cell per listed column', () => {
    // One cell per listed column: a renamed or dropped column changes the count.
    for (const key of ['osm_table', 'data', 'hazard_table'] as const) {
      const cells = SOURCE_LEGENDS[key].example.split(';');
      expect(cells.length).toBe(SOURCE_LEGENDS[key].columns.length);
    }
  });

  it('hazard_table: the example row uses an allowed corrispondenza', () => {
    const columns = SOURCE_LEGENDS.hazard_table.columns.map((c) => c.name);
    const cells = SOURCE_LEGENDS.hazard_table.example.split(';');
    expect(contract.values.corrispondenza).toContain(cells[columns.indexOf('corrispondenza')]);
  });

  it('boundaries: the example uses contract properties and an allowed tipo', () => {
    const example = JSON.parse(SOURCE_LEGENDS.boundaries.example) as Record<string, string>;
    const known = [...contract.boundaries.required, ...contract.boundaries.optional];
    expect(Object.keys(example).every((name) => known.includes(name))).toBe(true);
    for (const name of contract.boundaries.required) {
      expect(example).toHaveProperty(name);
    }
    expect(contract.values.tipo).toContain(example['tipo']);
  });
});
