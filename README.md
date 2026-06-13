# Crime Risk Analyzer

Sistema di analisi e prevenzione del rischio criminale a supporto di una tesi di
ricerca. Il progetto combina dati geospaziali, una base di conoscenza ontologica
(RDF/SPARQL) e un livello di ragionamento basato su LLM per stimare e **spiegare** il
rischio in modo trasparente e verificabile.

## Architettura (monorepo)

Il repository è organizzato come **monorepo** con due applicazioni distinte:

| Cartella | Descrizione | Stack |
|----------|-------------|-------|
| [`backend/`](backend/README.md) | API, query geospaziali, ragionamento SPARQL, pipeline RAG | Python (FastAPI, in arrivo con #7) |
| [`frontend/`](frontend/README.md) | UI con mappa interattiva, schede di rischio, citazioni | JS / HTML / CSS |

Consulta i README dei due sottoprogetti per setup e struttura interna.

## Dati e modelli pesanti

Dataset e modelli **non sono versionati** (zona *ghost*): vedi
[`backend/data/README.md`](backend/data/README.md).

## Licenza

Vedi [LICENSE](LICENSE).
