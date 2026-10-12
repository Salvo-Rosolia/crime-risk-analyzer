import {
  ISTAT_MIN_DELITTI,
  buildIstatProseCandidates,
  flattenIstatOccurrences,
  withIstatProseIndicators,
} from '@core/ui-helpers';
import type { IstatProseIndicator, ProseSegment } from '@core/ui-helpers';
import { IstatPoi, Poi, RiskItem, RiskModel } from '@core/models/models';
import { istatPoi, istatRiga } from '@core/testing/istat-fixtures';

describe('indicatore ISTAT in linea nella prosa (#365)', () => {
  const ind = (dati: string): IstatProseIndicator => ({
    dati,
    freccia: null,
    tendenza: 'tendenza n.d.',
    nota: null,
  });
  const cand = (hazardLabel: string, voce: string) => ({
    hazardLabel,
    voce,
    indicator: ind(`dati ${voce}`),
  });
  /** Forma compatta: stringa per il testo, [dati] per l'indicatore. */
  const forma = (segs: ProseSegment[]): (string | string[])[] =>
    segs.map((s) => (s.kind === 'text' ? s.text : [s.indicator.dati]));
  const testo = (segs: ProseSegment[]): string =>
    segs.map((s) => (s.kind === 'text' ? s.text : '')).join('');

  describe('withIstatProseIndicators', () => {
    it('inserisce l’indicatore subito dopo la PRIMA menzione, una volta sola', () => {
      const out = withIstatProseIndicators('Il furto è frequente. Il furto cala.', [
        cand('furto', 'THEFT'),
      ]);
      expect(forma(out)).toEqual(['Il furto', ['dati THEFT'], ' è frequente. Il furto cala.']);
    });

    it('un solo indicatore per voce ISTAT anche con etichette diverse', () => {
      const out = withIstatProseIndicators('Danneggiamento A e Danneggiamento B, poi furto.', [
        cand('Danneggiamento A', 'DAMAGE'),
        cand('Danneggiamento B', 'DAMAGE'),
        cand('furto', 'THEFT'),
      ]);
      expect(forma(out)).toEqual([
        'Danneggiamento A',
        ['dati DAMAGE'],
        ' e Danneggiamento B, poi furto.',
        ['dati THEFT'],
      ]);
    });

    it('con voce condivisa vale la prima menzione nel testo, non l’ordine dei candidati', () => {
      const out = withIstatProseIndicators('Prima B poi A.', [cand('A', 'V'), cand('B', 'V')]);
      expect(forma(out)).toEqual(['Prima B', ['dati V'], ' poi A.']);
    });

    it('case-insensitive, conserva il testo originale', () => {
      const out = withIstatProseIndicators('RAPINA AL VIAGGIATORE.', [
        cand('Rapina al viaggiatore', 'ROB'),
      ]);
      expect(forma(out)).toEqual(['RAPINA AL VIAGGIATORE.', ['dati ROB']]);
    });

    it('trova l’etichetta anche tra virgolette tipografiche e dritte', () => {
      for (const [a, b] of [
        ['“', '”'],
        ['"', '"'],
      ]) {
        const prosa = `con ${a}Rapina${b} e altro`;
        const out = withIstatProseIndicators(prosa, [cand('Rapina', 'ROB')]);
        expect(out.filter((s) => s.kind === 'istat')).toHaveLength(1);
        expect(testo(out)).toBe(prosa);
      }
    });

    it('con la citazione tra virgolette l’indicatore va dopo la virgoletta di chiusura', () => {
      const out = withIstatProseIndicators('il “Furto”, poi', [cand('Furto', 'T')]);
      expect(forma(out)).toEqual(['il “Furto”,', ['dati T'], ' poi']);
    });

    it('rispetta i confini di parola (anche con lettere accentate)', () => {
      expect(forma(withIstatProseIndicators('un furtivo e furti', [cand('furto', 'T')]))).toEqual([
        'un furtivo e furti',
      ]);
      expect(forma(withIstatProseIndicators('malfurto', [cand('furto', 'T')]))).toEqual([
        'malfurto',
      ]);
      expect(forma(withIstatProseIndicators('la città', [cand('citt', 'T')]))).toEqual([
        'la città',
      ]);
      expect(forma(withIstatProseIndicators('più città.', [cand('città', 'T')]))).toEqual([
        'più città.',
        ['dati T'],
      ]);
    });

    it('l’etichetta più lunga ha precedenza su quella che ne è un prefisso', () => {
      const out = withIstatProseIndicators('Furto con strappo e poi furto.', [
        cand('Furto', 'THEFT'),
        cand('Furto con strappo', 'SNATCH'),
      ]);
      expect(forma(out)).toEqual([
        'Furto con strappo',
        ['dati SNATCH'],
        ' e poi furto.',
        ['dati THEFT'],
      ]);
    });

    it('apostrofo dritto e tipografico sono equivalenti, in prosa e in etichetta', () => {
      for (const [lab, pro] of [
        ["dell'area", 'Danno dell\u2019area di sosta'],
        ['dell\u2019area', "Danno dell'area di sosta"],
        ['dell\u2018area', 'Danno dell\u2019area di sosta'],
      ]) {
        const out = withIstatProseIndicators(pro, [cand(`Danno ${lab}`, 'D')]);
        expect(out.filter((x) => x.kind === 'istat')).toHaveLength(1);
        expect(testo(out)).toBe(pro);
      }
    });

    it('un blocco (rischio senza dato) più lungo consuma il match: nessuna falsa attribuzione per prefisso', () => {
      const prosa = 'Il furto con strappo è frequente.';
      const out = withIstatProseIndicators(
        prosa,
        [cand('Furto', 'THEFT')],
        ['Furto', 'Furto con strappo'],
      );
      expect(out).toEqual([{ kind: 'text', text: prosa }]);
      // senza il blocco il prefisso verrebbe attribuito
      expect(withIstatProseIndicators(prosa, [cand('Furto', 'THEFT')])).toHaveLength(3);
    });

    it('un blocco non impedisce una menzione autonoma del candidato corto', () => {
      const out = withIstatProseIndicators(
        'Furto con strappo e poi furto.',
        [cand('Furto', 'T')],
        ['Furto con strappo'],
      );
      expect(forma(out)).toEqual(['Furto con strappo e poi furto.', ['dati T']]);
    });

    it('markdown di chiusura: l’indicatore va dopo ** e *, anche con virgolette', () => {
      expect(forma(withIstatProseIndicators('il **furto** cala', [cand('furto', 'T')]))).toEqual([
        'il **furto**',
        ['dati T'],
        ' cala',
      ]);
      expect(forma(withIstatProseIndicators('il *Furto*, poi', [cand('furto', 'T')]))).toEqual([
        'il *Furto*,',
        ['dati T'],
        ' poi',
      ]);
      expect(
        forma(withIstatProseIndicators('il **\u201Cfurto\u201D** cala', [cand('furto', 'T')])),
      ).toEqual(['il **\u201Cfurto\u201D**', ['dati T'], ' cala']);
      expect(forma(withIstatProseIndicators('il _furto_ x', [cand('furto', 'T')]))).toEqual([
        'il _furto_',
        ['dati T'],
        ' x',
      ]);
    });

    it('due rischi con la stessa etichetta: vince il primo candidato (primo POI con dato)', () => {
      const out = withIstatProseIndicators('Il furto.', [
        cand('Furto', 'PRIMO'),
        cand('furto', 'SECONDO'),
      ]);
      expect(forma(out)).toEqual(['Il furto.', ['dati PRIMO']]);
    });

    it('un solo segno di punteggiatura dopo la menzione precede l’indicatore; due no', () => {
      for (const p of [',', '.', ';', ':', ')']) {
        expect(forma(withIstatProseIndicators(`il furto${p} poi`, [cand('furto', 'T')]))).toEqual([
          `il furto${p}`,
          ['dati T'],
          ' poi',
        ]);
      }
      expect(forma(withIstatProseIndicators('il furto.. poi', [cand('furto', 'T')]))).toEqual([
        'il furto.',
        ['dati T'],
        '. poi',
      ]);
    });

    it('virgolette singole tipografiche di chiusura saltate; l’apostrofo dentro la parola no', () => {
      expect(forma(withIstatProseIndicators('il ‘furto’ cala', [cand('furto', 'T')]))).toEqual([
        'il ‘furto’',
        ['dati T'],
        ' cala',
      ]);
      expect(forma(withIstatProseIndicators('dell’area', [cand('dell', 'T')]))).toEqual([
        'dell',
        ['dati T'],
        '’area',
      ]);
    });

    describe('prosa reale (Colosseo)', () => {
      const prosa =
        'L’**impennata della criminalità** è evidente, con *Aggressione a scopo di furto* e ' +
        '*Danneggiamento dell’area di sosta*, oltre al furto di rame.';
      const blocks = [
        'Impennata della criminalità',
        'Aggressione a scopo di furto',
        "Danneggiamento dell'area di sosta",
        'Furto di rame',
        'Furto',
      ];

      it('blocchi completi: ogni indicatore dopo il suo rischio, testo originale intatto', () => {
        const out = withIstatProseIndicators(
          prosa,
          [
            cand('Impennata della criminalità', 'IMP'),
            cand("Danneggiamento dell'area di sosta", 'DAMAGE'),
            cand('Furto', 'THEFT'),
          ],
          blocks,
        );
        expect(testo(out)).toBe(prosa);
        expect(forma(out)).toEqual([
          'L’**impennata della criminalità**',
          ['dati IMP'],
          ' è evidente, con *Aggressione a scopo di furto* e *Danneggiamento dell’area di sosta*,',
          ['dati DAMAGE'],
          ' oltre al furto di rame.',
        ]);
      });

      it('limite documentato: con «Furto» in scope e «Aggressione a scopo di furto» no, l’indicatore si aggancia alla parola esatta', () => {
        const out = withIstatProseIndicators(
          'Pesa *Aggressione a scopo di furto* qui.',
          [cand('Furto', 'THEFT')],
          ['Furto'],
        );
        expect(forma(out)).toEqual([
          'Pesa *Aggressione a scopo di furto*',
          ['dati THEFT'],
          ' qui.',
        ]);
      });
    });

    it('nessun candidato: testo intatto in un solo segmento', () => {
      expect(withIstatProseIndicators('Testo qualunque.', [])).toEqual([
        { kind: 'text', text: 'Testo qualunque.' },
      ]);
    });

    it('nessuna menzione: testo intatto', () => {
      expect(forma(withIstatProseIndicators('Niente qui.', [cand('furto', 'T')]))).toEqual([
        'Niente qui.',
      ]);
    });

    it('prosa vuota: nessun segmento', () => {
      expect(withIstatProseIndicators('', [cand('furto', 'T')])).toEqual([]);
    });

    it('caratteri speciali di regex nell’etichetta non rompono nulla', () => {
      const out = withIstatProseIndicators('Danno (grave) qui', [cand('Danno (grave)', 'D')]);
      expect(forma(out)).toEqual(['Danno (grave)', ['dati D'], ' qui']);
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

    it('indicatore compatto: luogo e anno, voce, tassi, tendenza breve, avviso in coda', () => {
      const riga = istatRiga('THEFT', ['Theft'], {
        voce_label: 'furti',
        luogo_nome: 'Comune di Roma',
        tasso: 4876.4,
        tasso_italia: 1788.7,
        delitti: 134169,
        delitti_confronto: 148910,
        variazione_pct: -10,
      });
      const [c] = buildIstatProseCandidates(
        flattenIstatOccurrences([poi('1', istatPoi(riga))], [model('1', risk('Theft'))]),
      );
      expect(c.indicator).toEqual({
        dati: 'ISTAT · Comune di Roma 2024 · furti: 4.876,4 ogni 100.000 ab. (Italia 1.788,7)',
        freccia: '▼',
        tendenza: '−10% dal 2014',
        nota: 'voce più ampia del rischio',
      });
    });

    it('compatto: crescita con +, tendenza non calcolata, corrispondenza esatta senza avviso, luogo della riga', () => {
      const esatta = [
        { hazard: 'Theft', hazard_label_it: 'Furto', corrispondenza: 'esatta' as const },
      ];
      const su = istatRiga('T', ['Theft'], {
        variazione_pct: 25,
        collegamenti: esatta,
        luogo_nome: 'Provincia di Roma',
      });
      const nd = istatRiga('T', ['Theft'], { variazione_pct: null, collegamenti: esatta });
      const ind = (r: ReturnType<typeof istatRiga>) =>
        buildIstatProseCandidates(
          flattenIstatOccurrences([poi('1', istatPoi(r))], [model('1', risk('Theft'))]),
        )[0].indicator;
      expect(ind(su)).toMatchObject({ freccia: '▲', tendenza: '+25% dal 2014', nota: null });
      expect(ind(su).dati).toMatch(/^ISTAT · Provincia di Roma 2024 · /);
      expect(ind(nd)).toMatchObject({ freccia: null, tendenza: 'tendenza n.d.' });
    });

    it('rischio con dato: candidato con lo stesso indicatore del Dettaglio', () => {
      const dati = istatPoi(istatRiga('THEFT', ['Theft'], { voce_label: 'furti' }));
      const out = buildIstatProseCandidates(
        flattenIstatOccurrences([poi('1', dati)], [model('1', risk('Theft', 'Furto'))]),
      );
      expect(out).toHaveLength(1);
      expect(out[0].hazardLabel).toBe('Furto');
      expect(out[0].voce).toBe('THEFT');
      expect(out[0].indicator.dati).toMatch(/^ISTAT · Comune di Roma 2024 · furti: /);
    });

    it('sotto soglia o senza dato: nessun candidato, testo intatto', () => {
      const sotto = istatPoi(istatRiga('THEFT', ['Theft'], { delitti: ISTAT_MIN_DELITTI - 1 }));
      for (const istat of [sotto, null, undefined]) {
        const cands = buildIstatProseCandidates(
          flattenIstatOccurrences([poi('1', istat)], [model('1', risk('Theft', 'Furto'))]),
        );
        expect(cands).toEqual([]);
        expect(withIstatProseIndicators('Il Furto.', cands)).toEqual([
          { kind: 'text', text: 'Il Furto.' },
        ]);
      }
    });

    it('zona: per un rischio vale il primo POI che lo ha CON un dato', () => {
      const senza = istatPoi(istatRiga('THEFT', ['Theft'], { delitti: 1, voce_label: 'primo' }));
      const buono = istatPoi(istatRiga('THEFT', ['Theft'], { voce_label: 'secondo' }));
      const altro = istatPoi(istatRiga('THEFT', ['Theft'], { voce_label: 'terzo' }));
      const out = buildIstatProseCandidates(
        flattenIstatOccurrences(
          [poi('1', senza), poi('2', buono), poi('3', altro)],
          [model('1', risk('Theft')), model('2', risk('Theft')), model('3', risk('Theft'))],
        ),
      );
      expect(out).toHaveLength(1);
      expect(out[0].indicator.dati).toMatch(/· secondo: /);
    });

    it('aggancia i rischi per poi_id e ignora POI senza modello', () => {
      const dati = istatPoi(istatRiga('THEFT', ['Theft']));
      expect(
        flattenIstatOccurrences([poi('1', dati), poi('9', dati)], [model('1', risk('Theft'))]),
      ).toHaveLength(1);
      expect(flattenIstatOccurrences(null, null)).toEqual([]);
    });
  });
});
