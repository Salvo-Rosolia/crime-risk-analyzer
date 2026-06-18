# Frontend — Crime Risk Analyzer

Interfaccia utente del sistema: mappa interattiva (Leaflet), schede di rischio con
badge di confidenza e citazioni SPARQL. Stack volutamente semplice — **JS / HTML /
CSS**, senza framework.

## Requisiti

- Un browser moderno
- (Opzionale) Node.js 18+ per tooling, dev server e test

## Setup & avvio

Servire i file statici della cartella `public/` **come document root**. Il modulo
`<script type="module" src="../src/app.js">` in `index.html` usa un path relativo
che risale di un livello rispetto a `public/`: quando il server è radicato su
`public/`, `../src/` risolve correttamente in `frontend/src/`.

```bash
# dalla cartella frontend/ (NON da src/)
python -m http.server 5173 --directory public
# oppure, con Node:
# npx serve public
```

> Importante: non servire `frontend/` direttamente come document root (senza
> `--directory public`) perché in quel caso `../src/app.js` uscirebbe fuori dalla
> cartella frontend, rompendo il caricamento del modulo.

## Struttura

```
frontend/
├── src/       # sorgenti JS/CSS dell'applicazione
├── public/    # entry point statico (index.html) e asset serviti
└── tests/     # test automatici
```
