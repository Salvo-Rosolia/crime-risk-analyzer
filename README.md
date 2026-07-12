# Crime Risk Analyzer

Sistema di analisi e prevenzione del rischio criminale a supporto di una tesi di
ricerca. Il progetto combina dati geospaziali, una base di conoscenza ontologica
(RDF/SPARQL) e un livello di ragionamento basato su LLM per stimare e **spiegare** il
rischio in modo trasparente e verificabile.

## Architettura (monorepo)

Il repository è organizzato come **monorepo** con due applicazioni distinte:

| Cartella | Descrizione | Stack |
|----------|-------------|-------|
| [`backend/`](backend/README.md) | API, query geospaziali, ragionamento ontologico (SPARQL), pipeline RAG e ragionamento LLM | Python · FastAPI · rdflib · uv |
| [`frontend/`](frontend/README.md) | UI con mappa interattiva, schede di rischio con livelli di confidence e citazioni SPARQL | Angular 20 (standalone + signals) · TypeScript · Leaflet |

Consulta i README dei due sottoprogetti per setup e struttura interna.

## Stato

Sviluppo incrementale per story. In sintesi:

- **Backend** — app FastAPI con loader dell'ontologia RDF in memoria, client LLM
  provider-agnostico (Claude/Groq) e pipeline RAG (retrieval → grounding → generation).
  Endpoint attivi: `GET /health`, `GET /cities`, `POST /analyze` (pipeline completa
  geocoding → OSM → SPARQL → grounding → LLM) e `POST /analyze/baseline` (variante
  senza LLM per l'ablation).
- **Frontend** — migrazione ad Angular completata (standalone + signals). Sopra il layer
  *core* — contratto dati `/analyze`, macchina a stati pura, signal store e service HTTP
  con fallback su cache demo, coperto da test (Jest) — è consegnata la UI: mappa
  interattiva Leaflet e pannelli (input, dettaglio POI, narrativa).

## Dati e modelli pesanti

Dataset e modelli **non sono versionati** (zona *ghost*): vedi
[`backend/data/README.md`](backend/data/README.md).

## Licenza

Vedi [LICENSE](LICENSE).
