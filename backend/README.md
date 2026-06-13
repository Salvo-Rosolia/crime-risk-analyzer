# Backend — Crime Risk Analyzer

API e logica di dominio del sistema: query geospaziali, ragionamento ontologico
(SPARQL) e pipeline RAG. Lo scaffolding di FastAPI arriva con la story **#7**; questa
cartella definisce per ora solo lo **scheletro**.

## Requisiti

- Python 3.11+

## Setup

```bash
# dalla cartella backend/
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
# Le dipendenze (FastAPI, ecc.) verranno aggiunte con #7:
# pip install -r requirements.txt
```

## Avvio

L'applicazione FastAPI non è ancora presente (arriva con #7). Una volta aggiunta, il
comando sarà tipo:

```bash
# placeholder fino a #7
# uvicorn src.main:app --reload
```

## Struttura

```
backend/
├── src/         # codice applicativo (API, servizi, modelli di dominio)
├── ontology/    # ontologia RDF, query SPARQL, mapping OSM
├── data/        # dataset e modelli pesanti — NON versionati (zona ghost)
└── tests/       # test automatici
```
