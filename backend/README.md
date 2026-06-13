# Backend — Crime Risk Analyzer

API e logica di dominio del sistema: query geospaziali, ragionamento ontologico
(SPARQL) e pipeline RAG. Lo scaffolding FastAPI (story **#7**) fornisce per ora
l'ossatura runnable con il solo endpoint `GET /health`; gli endpoint di dominio
(`/analyze`, `/cities`, `/scenarios`) arrivano in fase P2.

## Requisiti

- Python 3.11+ (la macchina di sviluppo usa 3.12, fissato in `.python-version`)
- [`uv`](https://docs.astral.sh/uv/) per ambiente, dipendenze e lockfile

## Setup

```bash
# dalla cartella backend/
uv sync
```

`uv sync` crea il virtualenv `.venv`, installa runtime + dev dependencies dal
`uv.lock` e installa il package `crime_risk_analyzer` in editable mode.

## Avvio

```bash
uv run uvicorn crime_risk_analyzer.main:app --reload
```

L'app espone `GET /health` → `{"status": "ok"}`.

## Test

```bash
uv run pytest
```

## Quality gate

```bash
uv run ruff format .          # formattazione
uv run ruff check --fix .     # lint
uv run pyright                # type check (strict)
uv run pytest                 # test
```

## Struttura

```
backend/
├── pyproject.toml        # progetto + dipendenze (uv) + config ruff/pyright/pytest
├── .python-version       # interprete pinnato (3.12)
├── src/
│   └── crime_risk_analyzer/   # package applicativo (src-layout)
│       ├── __init__.py        # __version__
│       └── main.py            # create_app() + app + GET /health
├── ontology/             # ontologia RDF, query SPARQL, mapping OSM (vuota per ora)
├── data/                 # dataset e modelli pesanti — NON versionati (zona ghost)
└── tests/                # test automatici (pytest)
```
