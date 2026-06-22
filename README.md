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

- **Backend** — scaffolding FastAPI runnable con loader dell'ontologia RDF in memoria;
  endpoint attivi `GET /health`, `GET /cities`, `GET /scenarios`; client LLM
  provider-agnostico e pipeline RAG di generazione. L'endpoint di dominio `POST /analyze`
  è la prossima fase (P2).
- **Frontend** — migrazione ad Angular completata (scaffold standalone + signals). È pronto
  il layer *core* — contratto dati `/analyze`, macchina a stati pura, signal store e service
  HTTP con fallback su cache demo — coperto da test (Jest); UI e mappa Leaflet in arrivo.

## Dati e modelli pesanti

Dataset e modelli **non sono versionati** (zona *ghost*): vedi
[`backend/data/README.md`](backend/data/README.md).

## Licenza

Vedi [LICENSE](LICENSE).
