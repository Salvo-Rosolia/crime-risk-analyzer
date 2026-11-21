import type { SourceFile } from '@core/models/models';

/** One column (or element) of a source file, explained for a non-technical user. */
export interface LegendColumn {
  name: string;
  meaning: string;
  /** Allowed values or format, when the column is constrained. */
  values?: string;
  optional?: boolean;
}

/** Foldable legend of a source file: what goes in it, column by column, plus an example. */
export interface SourceLegend {
  intro: string;
  columns: readonly LegendColumn[];
  /** Label of the example block (a row, a snippet...). */
  exampleLabel: string;
  example: string;
}

export const SOURCE_LEGENDS: Record<SourceFile, SourceLegend> = {
  ontology: {
    intro:
      'Descrive i tipi di luogo (classi) e i rischi (hazard) che possono avere. Ogni classe di luogo ' +
      'è collegata ai suoi rischi con una restrizione OWL; anche ogni hazard è una classe. ' +
      'Classi e hazard devono stare nel namespace di TERMINUS ' +
      '(http://www.enea-terin-sen-apic.it/TERMINUS-crime-v01#) e la proprietà si chiama havingHazard: ' +
      "se la tua ontologia usa altri nomi indicali in «Impostazioni avanzate dell'ontologia». " +
      'Le classi fuori dal namespace vengono ignorate.',
    columns: [
      {
        name: 'Classe di luogo',
        meaning:
          'Un tipo di luogo (es. Bank). Il suo nome va nella colonna «classe» della tabella OSM.',
        values: 'owl:Class',
      },
      {
        name: 'havingHazard',
        meaning:
          'Collega la classe a un rischio. Il nome del rischio va nella colonna «hazard» della tabella hazard.',
        values: 'owl:Restriction con owl:someValuesFrom',
      },
      {
        name: 'Etichette',
        meaning: 'Nome leggibile della classe, in italiano e in inglese.',
        values: 'rdfs:label con @it e @en',
        optional: true,
      },
    ],
    exampleLabel: 'Esempio',
    example:
      '@prefix t: <http://www.enea-terin-sen-apic.it/TERMINUS-crime-v01#> .\n' +
      '@prefix owl: <http://www.w3.org/2002/07/owl#> .\n' +
      '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n\n' +
      't:Bank a owl:Class ;\n' +
      '    rdfs:subClassOf [ a owl:Restriction ;\n' +
      '        owl:onProperty t:havingHazard ; owl:someValuesFrom t:Bank_robbery ] .\n' +
      't:Bank_robbery a owl:Class .',
  },
  osm_table: {
    intro:
      "Dice a quale classe dell'ontologia corrisponde ogni elemento di OpenStreetMap. Una riga per ogni tag. " +
      'Il separatore delle colonne è il punto e virgola (come nei modelli) oppure la virgola.',
    columns: [
      {
        name: 'osm_tag',
        meaning: 'Il tag OpenStreetMap, nella forma chiave=valore.',
        values: 'es. amenity=bank',
      },
      {
        name: 'classe',
        meaning: "La classe dell'ontologia a cui il tag corrisponde.",
        values: "un nome di classe presente nell'ontologia",
      },
    ],
    exampleLabel: 'Esempio di riga',
    example: 'amenity=bank;Bank',
  },
  hazard_table: {
    intro:
      "Collega ogni hazard dell'ontologia a una voce dei dati statistici. Un hazard può restare " +
      'senza voce: in quel caso lascia vuote le colonne «voce» e «corrispondenza». ' +
      'Il separatore delle colonne è il punto e virgola (come nei modelli) oppure la virgola.',
    columns: [
      {
        name: 'hazard',
        meaning: "Il rischio, come si chiama nell'ontologia.",
        values: 'es. Bank_robbery',
      },
      {
        name: 'voce',
        meaning: 'La voce dei dati statistici che lo rappresenta meglio.',
        values: 'un codice della colonna «voce» del file dei dati (es. THEFT)',
      },
      {
        name: 'corrispondenza',
        meaning: 'Quanto la voce coincide con il rischio.',
        values:
          'esatta (la voce è lo stesso reato), piu_larga (la voce comprende il rischio e altro), piu_stretta (la voce copre solo una parte del rischio)',
      },
      {
        name: 'serie_non_confrontabile',
        meaning:
          'Se la serie storica della voce non si può confrontare tra gli anni. Vale per tutta la voce: se due righe della stessa voce non concordano, prevale si.',
        values: 'si oppure no (se vuota vale no)',
        optional: true,
      },
      { name: 'nota', meaning: 'Una nota libera, per te.', optional: true },
    ],
    exampleLabel: 'Esempio di riga',
    example: 'Bank_robbery;THEFT;piu_larga;no;',
  },
  data: {
    intro:
      'I dati statistici sui delitti denunciati, per luogo, voce e anno. La riga nazionale (luogo IT) ' +
      "è obbligatoria; senza l'anno di confronto (10 anni prima dell'anno più recente) la tendenza " +
      'non viene calcolata. Il separatore delle colonne è il punto e virgola (come nel modello) oppure ' +
      'la virgola; solo nei file con il punto e virgola i decimali si scrivono con la virgola, e il punto ' +
      'come separatore delle migliaia (es. 3.400) viene rifiutato. Se modifichi il file con Excel, ' +
      'controlla che i codici come 001 non perdano gli zeri iniziali.',
    columns: [
      {
        name: 'luogo',
        meaning:
          'Il codice del luogo (codice ISTAT del comune o della provincia), con gli zeri iniziali. IT è il totale Italia.',
        values: 'fino a 20 tra lettere, cifre, _ e -, es. 058091 oppure IT',
      },
      {
        name: 'voce',
        meaning:
          'Il codice del tipo di delitto. TOT è il totale: se manca la riga TOT compare un avviso.',
        values: 'fino a 40 tra lettere, cifre e _',
      },
      {
        name: 'voce_etichetta',
        meaning:
          'Il nome leggibile della voce. La stessa voce deve avere sempre la stessa etichetta.',
        values: 'es. furti',
      },
      { name: 'anno', meaning: "L'anno dei dati.", values: 'quattro cifre, es. 2024' },
      {
        name: 'delitti',
        meaning: 'Il numero di delitti denunciati. Vuoto se il dato manca.',
        values: 'numero intero, oppure vuoto',
      },
      {
        name: 'tasso',
        meaning:
          'Delitti ogni 100.000 abitanti. Vuoto se il dato manca o se tasso_sotto_soglia è si.',
        values:
          'numero decimale, es. 1500,0 (la virgola decimale vale solo nei file con il punto e virgola), oppure vuoto',
      },
      {
        name: 'tasso_sotto_soglia',
        meaning:
          'Se il tasso è sotto la soglia di affidabilità. Se «delitti» è vuoto, lascia vuoti anche «tasso» e questa colonna.',
        values: 'si oppure no (se vuota vale no)',
        optional: true,
      },
    ],
    exampleLabel: 'Esempio di riga',
    example: '058091;THEFT;furti;2024;2000;2500,0;no',
  },
  boundaries: {
    intro:
      'Facoltativo. Un GeoJSON di tipo FeatureCollection con i confini dei luoghi dei dati: ' +
      'una feature per luogo, con queste proprietà. La geometria deve essere Polygon o MultiPolygon e ' +
      'lo stesso codice non può comparire in più feature. Senza questo file valgono solo i confini già ' +
      "presenti nell'app. Non esiste un modello da scaricare.",
    columns: [
      {
        name: 'codice',
        meaning: 'Lo stesso codice usato nella colonna «luogo» dei dati.',
        values: 'es. 058091',
      },
      {
        name: 'tipo',
        meaning: 'Se il luogo è un comune o una provincia.',
        values: 'comune oppure provincia',
      },
      { name: 'nome', meaning: 'Il nome completo.', values: 'es. Roma' },
      { name: 'nome_breve', meaning: 'Il nome breve, usato nei testi.', values: 'es. Roma' },
      { name: 'provincia', meaning: 'Il codice della provincia del comune.', optional: true },
    ],
    exampleLabel: 'Esempio di proprietà',
    example: '{ "codice": "058091", "tipo": "comune", "nome": "Roma", "nome_breve": "Roma" }',
  },
};
