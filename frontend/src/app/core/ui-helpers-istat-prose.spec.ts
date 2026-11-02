import {
  ISTAT_MIN_DELITTI,
  buildIstatProseCandidates,
  flattenIstatOccurrences,
  withIstatProseIndicators,
} from '@core/ui-helpers';
import type { IstatProseIndicator, ProseSegment } from '@core/ui-helpers';
import { IstatPoi, Poi, RiskItem, RiskModel } from '@core/models/models';
import { istatPoi, istatRow } from '@core/testing/istat-fixtures';

describe('inline ISTAT indicator in the prose (#365)', () => {
  const ind = (data: string): IstatProseIndicator => ({
    data,
    arrow: null,
    trend: 'tendenza n.d.',
    note: null,
  });
  const cand = (hazardLabel: string, item: string) => ({
    hazardLabel,
    item,
    indicator: ind(`dati ${item}`),
  });
  /** Compact shape: string for the text, [data] for the indicator. */
  const compact = (segs: ProseSegment[]): (string | string[])[] =>
    segs.map((s) => (s.kind === 'text' ? s.text : [s.indicator.data]));
  const joinText = (segs: ProseSegment[]): string =>
    segs.map((s) => (s.kind === 'text' ? s.text : '')).join('');

  describe('withIstatProseIndicators', () => {
    it('inserts the indicator right after the FIRST mention, only once', () => {
      const out = withIstatProseIndicators('Il furto è frequente. Il furto cala.', [
        cand('furto', 'THEFT'),
      ]);
      expect(compact(out)).toEqual(['Il furto', ['dati THEFT'], ' è frequente. Il furto cala.']);
    });

    it('a single indicator per ISTAT item even with different labels', () => {
      const out = withIstatProseIndicators('Danneggiamento A e Danneggiamento B, poi furto.', [
        cand('Danneggiamento A', 'DAMAGE'),
        cand('Danneggiamento B', 'DAMAGE'),
        cand('furto', 'THEFT'),
      ]);
      expect(compact(out)).toEqual([
        'Danneggiamento A',
        ['dati DAMAGE'],
        ' e Danneggiamento B, poi furto.',
        ['dati THEFT'],
      ]);
    });

    it('with a shared item the first mention in the text counts, not the order of the candidates', () => {
      const out = withIstatProseIndicators('Prima B poi A.', [cand('A', 'V'), cand('B', 'V')]);
      expect(compact(out)).toEqual(['Prima B', ['dati V'], ' poi A.']);
    });

    it('case-insensitive, keeps the original text', () => {
      const out = withIstatProseIndicators('RAPINA AL VIAGGIATORE.', [
        cand('Rapina al viaggiatore', 'ROB'),
      ]);
      expect(compact(out)).toEqual(['RAPINA AL VIAGGIATORE.', ['dati ROB']]);
    });

    it('finds the label also between typographic and straight quotes', () => {
      for (const [a, b] of [
        ['“', '”'],
        ['"', '"'],
      ]) {
        const prose = `con ${a}Rapina${b} e altro`;
        const out = withIstatProseIndicators(prose, [cand('Rapina', 'ROB')]);
        expect(out.filter((s) => s.kind === 'istat')).toHaveLength(1);
        expect(joinText(out)).toBe(prose);
      }
    });

    it('with the quote in quotation marks the indicator goes after the closing quotation mark', () => {
      const out = withIstatProseIndicators('il “Furto”, poi', [cand('Furto', 'T')]);
      expect(compact(out)).toEqual(['il “Furto”,', ['dati T'], ' poi']);
    });

    it('respects word boundaries (even with accented letters)', () => {
      expect(compact(withIstatProseIndicators('un furtivo e furti', [cand('furto', 'T')]))).toEqual(
        ['un furtivo e furti'],
      );
      expect(compact(withIstatProseIndicators('malfurto', [cand('furto', 'T')]))).toEqual([
        'malfurto',
      ]);
      expect(compact(withIstatProseIndicators('la città', [cand('citt', 'T')]))).toEqual([
        'la città',
      ]);
      expect(compact(withIstatProseIndicators('più città.', [cand('città', 'T')]))).toEqual([
        'più città.',
        ['dati T'],
      ]);
    });

    it('the longer label takes precedence over one that is a prefix of it', () => {
      const out = withIstatProseIndicators('Furto con strappo e poi furto.', [
        cand('Furto', 'THEFT'),
        cand('Furto con strappo', 'SNATCH'),
      ]);
      expect(compact(out)).toEqual([
        'Furto con strappo',
        ['dati SNATCH'],
        ' e poi furto.',
        ['dati THEFT'],
      ]);
    });

    it('straight and typographic apostrophe are equivalent, in prose and in label', () => {
      for (const [lab, pro] of [
        ["dell'area", 'Danno dell\u2019area di sosta'],
        ['dell\u2019area', "Danno dell'area di sosta"],
        ['dell\u2018area', 'Danno dell\u2019area di sosta'],
      ]) {
        const out = withIstatProseIndicators(pro, [cand(`Danno ${lab}`, 'D')]);
        expect(out.filter((x) => x.kind === 'istat')).toHaveLength(1);
        expect(joinText(out)).toBe(pro);
      }
    });

    it('a longer block (risk without data) consumes the match: no false attribution by prefix', () => {
      const prose = 'Il furto con strappo è frequente.';
      const out = withIstatProseIndicators(
        prose,
        [cand('Furto', 'THEFT')],
        ['Furto', 'Furto con strappo'],
      );
      expect(out).toEqual([{ kind: 'text', text: prose }]);
      // without the block the prefix would be attributed
      expect(withIstatProseIndicators(prose, [cand('Furto', 'THEFT')])).toHaveLength(3);
    });

    it('a block does not prevent an autonomous mention of the short candidate', () => {
      const out = withIstatProseIndicators(
        'Furto con strappo e poi furto.',
        [cand('Furto', 'T')],
        ['Furto con strappo'],
      );
      expect(compact(out)).toEqual(['Furto con strappo e poi furto.', ['dati T']]);
    });

    it('closing markdown: the indicator goes after ** and *, even with quotes', () => {
      expect(compact(withIstatProseIndicators('il **furto** cala', [cand('furto', 'T')]))).toEqual([
        'il **furto**',
        ['dati T'],
        ' cala',
      ]);
      expect(compact(withIstatProseIndicators('il *Furto*, poi', [cand('furto', 'T')]))).toEqual([
        'il *Furto*,',
        ['dati T'],
        ' poi',
      ]);
      expect(
        compact(withIstatProseIndicators('il **\u201Cfurto\u201D** cala', [cand('furto', 'T')])),
      ).toEqual(['il **\u201Cfurto\u201D**', ['dati T'], ' cala']);
      expect(compact(withIstatProseIndicators('il _furto_ x', [cand('furto', 'T')]))).toEqual([
        'il _furto_',
        ['dati T'],
        ' x',
      ]);
    });

    it('word boundaries treat _ as a word character (snake_case identifiers)', () => {
      const c = [cand('Furto', 'T')];
      expect(compact(withIstatProseIndicators('Il furto_di_rame cala.', c))).toEqual([
        'Il furto_di_rame cala.',
      ]);
      expect(compact(withIstatProseIndicators('Il tipo_furto cala.', c))).toEqual([
        'Il tipo_furto cala.',
      ]);
      expect(compact(withIstatProseIndicators('Il _furto_ cala.', c))).toEqual([
        'Il _furto_',
        ['dati T'],
        ' cala.',
      ]);
      expect(compact(withIstatProseIndicators('_furto_ cala.', c))).toEqual([
        '_furto_',
        ['dati T'],
        ' cala.',
      ]);
      expect(compact(withIstatProseIndicators('Il __furto__ cala.', c))).toEqual([
        'Il __furto__',
        ['dati T'],
        ' cala.',
      ]);
    });

    it('boundaries: start of text, newline, accented letters and consecutive mentions', () => {
      const c = [cand('Furto', 'T'), cand('Danno', 'D')];
      expect(compact(withIstatProseIndicators('Furto cala.', c))).toEqual([
        'Furto',
        ['dati T'],
        ' cala.',
      ]);
      expect(compact(withIstatProseIndicators('x\nfurto\ndanno', c))).toEqual([
        'x\nfurto',
        ['dati T'],
        '\ndanno',
        ['dati D'],
      ]);
      expect(compact(withIstatProseIndicators('èfurto e furtò', c))).toEqual(['èfurto e furtò']);
      expect(compact(withIstatProseIndicators('furto,danno', c))).toEqual([
        'furto,',
        ['dati T'],
        'danno',
        ['dati D'],
      ]);
    });

    it('two risks with the same label: the first candidate wins (first POI with data)', () => {
      const out = withIstatProseIndicators('Il furto.', [
        cand('Furto', 'PRIMO'),
        cand('furto', 'SECONDO'),
      ]);
      expect(compact(out)).toEqual(['Il furto.', ['dati PRIMO']]);
    });

    it('a single punctuation mark after the mention precedes the indicator; two do not', () => {
      for (const p of [',', '.', ';', ':', ')']) {
        expect(compact(withIstatProseIndicators(`il furto${p} poi`, [cand('furto', 'T')]))).toEqual(
          [`il furto${p}`, ['dati T'], ' poi'],
        );
      }
      expect(compact(withIstatProseIndicators('il furto.. poi', [cand('furto', 'T')]))).toEqual([
        'il furto.',
        ['dati T'],
        '. poi',
      ]);
    });

    it('closing typographic single quotes skipped; the apostrophe inside the word is not', () => {
      expect(compact(withIstatProseIndicators('il ‘furto’ cala', [cand('furto', 'T')]))).toEqual([
        'il ‘furto’',
        ['dati T'],
        ' cala',
      ]);
      expect(compact(withIstatProseIndicators('dell’area', [cand('dell', 'T')]))).toEqual([
        'dell',
        ['dati T'],
        '’area',
      ]);
    });

    describe('real prose (Colosseo)', () => {
      const prose =
        'L’**impennata della criminalità** è evidente, con *Aggressione a scopo di furto* e ' +
        '*Danneggiamento dell’area di sosta*, oltre al furto di rame.';
      const blocks = [
        'Impennata della criminalità',
        'Aggressione a scopo di furto',
        "Danneggiamento dell'area di sosta",
        'Furto di rame',
        'Furto',
      ];

      it('complete blocks: each indicator after its risk, original text intact', () => {
        const out = withIstatProseIndicators(
          prose,
          [
            cand('Impennata della criminalità', 'IMP'),
            cand("Danneggiamento dell'area di sosta", 'DAMAGE'),
            cand('Furto', 'THEFT'),
          ],
          blocks,
        );
        expect(joinText(out)).toBe(prose);
        expect(compact(out)).toEqual([
          'L’**impennata della criminalità**',
          ['dati IMP'],
          ' è evidente, con *Aggressione a scopo di furto* e *Danneggiamento dell’area di sosta*,',
          ['dati DAMAGE'],
          ' oltre al furto di rame.',
        ]);
      });

      it('documented limit: with «Furto» in scope and «Aggressione a scopo di furto» not, the indicator attaches to the exact word', () => {
        const out = withIstatProseIndicators(
          'Pesa *Aggressione a scopo di furto* qui.',
          [cand('Furto', 'THEFT')],
          ['Furto'],
        );
        expect(compact(out)).toEqual([
          'Pesa *Aggressione a scopo di furto*',
          ['dati THEFT'],
          ' qui.',
        ]);
      });
    });

    it('no candidate: text intact in a single segment', () => {
      expect(withIstatProseIndicators('Testo qualunque.', [])).toEqual([
        { kind: 'text', text: 'Testo qualunque.' },
      ]);
    });

    it('no mention: text intact', () => {
      expect(compact(withIstatProseIndicators('Niente qui.', [cand('furto', 'T')]))).toEqual([
        'Niente qui.',
      ]);
    });

    it('empty prose: no segment', () => {
      expect(withIstatProseIndicators('', [cand('furto', 'T')])).toEqual([]);
    });

    it('regex special characters in the label break nothing', () => {
      const out = withIstatProseIndicators('Danno (grave) qui', [cand('Danno (grave)', 'D')]);
      expect(compact(out)).toEqual(['Danno (grave)', ['dati D'], ' qui']);
    });
  });

  describe('buildIstatProseCandidates / flattenIstatOccurrences', () => {
    const risk = (hazard: string, label = hazard): RiskItem => ({
      hazard,
      confidence: 'verificato',
      tag: 'ONTOLOGIA',
      hazard_label_it: label,
      hazard_label_en: hazard,
    });
    const poi = (id: string, istat?: IstatPoi | null): Poi =>
      ({ id, name: id, istat }) as unknown as Poi;
    const model = (poi_id: string, ...risks: RiskItem[]): RiskModel => ({
      poi_id,
      poi: poi_id,
      risks,
    });

    it('compact indicator: place and year, item, rates, short trend, warning at the end', () => {
      const row = istatRow('THEFT', ['Theft'], {
        voce_label: 'furti',
        luogo_nome: 'Comune di Roma',
        tasso: 4876.4,
        tasso_italia: 1788.7,
        delitti: 134169,
        delitti_confronto: 148910,
        variazione_pct: -10,
      });
      const [c] = buildIstatProseCandidates(
        flattenIstatOccurrences([poi('1', istatPoi(row))], [model('1', risk('Theft'))]),
      );
      expect(c.indicator).toEqual({
        data: 'ISTAT · Comune di Roma 2024 · furti: 4.876,4 ogni 100.000 ab. (Italia 1.788,7)',
        arrow: '▼',
        trend: '−10% dal 2014',
        note: 'voce più ampia del rischio',
      });
    });

    it('compact: growth with +, trend not computed, exact match without warning, place of the row', () => {
      const exactLinks = [
        { hazard: 'Theft', hazard_label_it: 'Furto', corrispondenza: 'esatta' as const },
      ];
      const up = istatRow('T', ['Theft'], {
        variazione_pct: 25,
        collegamenti: exactLinks,
        luogo_nome: 'Provincia di Roma',
      });
      const nd = istatRow('T', ['Theft'], { variazione_pct: null, collegamenti: exactLinks });
      const ind = (r: ReturnType<typeof istatRow>) =>
        buildIstatProseCandidates(
          flattenIstatOccurrences([poi('1', istatPoi(r))], [model('1', risk('Theft'))]),
        )[0].indicator;
      expect(ind(up)).toMatchObject({ arrow: '▲', trend: '+25% dal 2014', note: null });
      expect(ind(up).data).toMatch(/^ISTAT · Provincia di Roma 2024 · /);
      expect(ind(nd)).toMatchObject({ arrow: null, trend: 'tendenza n.d.' });
    });

    it('risk with data: candidate with the same indicator as the Detail', () => {
      const data = istatPoi(istatRow('THEFT', ['Theft'], { voce_label: 'furti' }));
      const out = buildIstatProseCandidates(
        flattenIstatOccurrences([poi('1', data)], [model('1', risk('Theft', 'Furto'))]),
      );
      expect(out).toHaveLength(1);
      expect(out[0].hazardLabel).toBe('Furto');
      expect(out[0].item).toBe('THEFT');
      expect(out[0].indicator.data).toMatch(/^ISTAT · Comune di Roma 2024 · furti: /);
    });

    it('below threshold or without data: no candidate, text intact', () => {
      const below = istatPoi(istatRow('THEFT', ['Theft'], { delitti: ISTAT_MIN_DELITTI - 1 }));
      for (const istat of [below, null, undefined]) {
        const cands = buildIstatProseCandidates(
          flattenIstatOccurrences([poi('1', istat)], [model('1', risk('Theft', 'Furto'))]),
        );
        expect(cands).toEqual([]);
        expect(withIstatProseIndicators('Il Furto.', cands)).toEqual([
          { kind: 'text', text: 'Il Furto.' },
        ]);
      }
    });

    it('zone: for a risk the first POI that has it WITH data counts', () => {
      const without = istatPoi(istatRow('THEFT', ['Theft'], { delitti: 1, voce_label: 'primo' }));
      const good = istatPoi(istatRow('THEFT', ['Theft'], { voce_label: 'secondo' }));
      const other = istatPoi(istatRow('THEFT', ['Theft'], { voce_label: 'terzo' }));
      const out = buildIstatProseCandidates(
        flattenIstatOccurrences(
          [poi('1', without), poi('2', good), poi('3', other)],
          [model('1', risk('Theft')), model('2', risk('Theft')), model('3', risk('Theft'))],
        ),
      );
      expect(out).toHaveLength(1);
      expect(out[0].indicator.data).toMatch(/· secondo: /);
    });

    it('links the risks by poi_id and ignores POIs without a model', () => {
      const data = istatPoi(istatRow('THEFT', ['Theft']));
      expect(
        flattenIstatOccurrences([poi('1', data), poi('9', data)], [model('1', risk('Theft'))]),
      ).toHaveLength(1);
      expect(flattenIstatOccurrences(null, null)).toEqual([]);
    });
  });
});
