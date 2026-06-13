# Frontend — Crime Risk Analyzer

Interfaccia utente del sistema: mappa interattiva (Leaflet), schede di rischio con
badge di confidenza e citazioni SPARQL. Stack volutamente semplice — **JS / HTML /
CSS**, senza framework.

## Requisiti

- Un browser moderno
- (Opzionale) Node.js 18+ per tooling, dev server e test

## Setup & avvio

In fase iniziale è sufficiente servire i file statici della cartella `public/`:

```bash
# dalla cartella frontend/
python -m http.server 5173 --directory public
# oppure, con Node:
# npx serve public
```

## Struttura

```
frontend/
├── src/       # sorgenti JS/CSS dell'applicazione
├── public/    # entry point statico (index.html) e asset serviti
└── tests/     # test automatici
```
