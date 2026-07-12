# Frontend — Crime Risk Analyzer

UI dell'analizzatore di rischio: mappa interattiva (Leaflet), schede di rischio con
livelli di *confidence* e citazioni SPARQL. App **Angular 20** standalone con
*signals*, generata con Angular CLI 20.3.

## Requisiti

- Node.js 20.19.x (vedi `.nvmrc`)
- npm

```bash
npm install
```

## Sviluppo

```bash
npm start
```

Avvia il dev server su `http://localhost:4200/` con ricarica automatica. Lo script usa
`--proxy-config proxy.config.json` per inoltrare le chiamate API al backend FastAPI
durante lo sviluppo.

## Build

```bash
npm run build
```

Compila il progetto in `dist/` (build di produzione ottimizzata di default).

## Test

I test unitari girano con **Jest** (preset `jest-preset-angular`):

```bash
npm test
```

## Quality gate

```bash
npm run lint    # ESLint (ng lint)
npm test        # test unitari (Jest)
```

## Struttura

```
frontend/src/app/
├── core/                 # layer applicativo puro e testabile
│   ├── models/           # contratto dati /analyze, tipi FSM, Action union
│   ├── state/            # macchina a stati pura (transition) + signal store
│   ├── api/              # ApiService (HttpClient) con fallback su cache demo
│   ├── confidence.ts     # livelli di confidence, colore pin, copertura
│   └── ui-helpers.ts     # funzioni pure di derivazione/validazione UI
└── ...                   # componenti e mappa Leaflet (in arrivo)
```

## Risorse

Documentazione Angular CLI: [angular.dev/tools/cli](https://angular.dev/tools/cli).
