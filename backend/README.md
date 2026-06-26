# Backend — Crime Risk Analyzer

API e logica di dominio del sistema: query geospaziali, ragionamento ontologico
(SPARQL) e pipeline RAG con ragionamento LLM. L'app FastAPI carica l'ontologia RDF
in memoria all'avvio ed espone gli endpoint `GET /health` e `GET /cities`.
Sono già presenti i moduli di supporto — geocoding, client Overpass,
mapping OSM→ontologia, client LLM provider-agnostico e pipeline RAG di generazione.
L'endpoint di dominio `POST /analyze`, che orchestra l'intera pipeline, arriva in fase P2.

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

L'app espone, tra gli altri, `GET /health` → `{"status": "ok"}` e `GET /cities`
(città supportate).

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
│       ├── main.py            # create_app() + app + endpoint (/health, /cities)
│       ├── config.py          # Settings (env)
│       ├── ontology.py        # caricamento ontologia RDF in memoria (rdflib)
│       ├── geocoding.py       # geocoding zone
│       ├── overpass_client.py # client Overpass per POI OSM
│       ├── sparql_module/     # mapping OSM → ontologia
│       ├── llm/               # client LLM provider-agnostico
│       ├── rag/               # pipeline RAG di generazione narrativa
│       ├── errors.py          # errori di dominio
│       └── models/            # modelli dati (geo, vocab)
├── ontology/             # ontologia RDF, query SPARQL, mapping OSM — file NON versionati (zona ghost)
├── data/                 # dataset e modelli pesanti — NON versionati (zona ghost)
└── tests/                # test automatici (pytest)
```
