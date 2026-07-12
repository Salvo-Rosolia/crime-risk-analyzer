# Backend — Crime Risk Analyzer

API e logica di dominio del sistema: query geospaziali, ragionamento ontologico
(SPARQL) e pipeline RAG con ragionamento LLM. L'app FastAPI carica l'ontologia RDF
in memoria all'avvio ed espone gli endpoint `GET /health`, `GET /cities`,
`POST /analyze` e `POST /analyze/baseline`. L'endpoint di dominio `POST /analyze`
orchestra l'intera pipeline (geocoding → POI OSM via Overpass → mapping OSM→TERMINUS
→ query SPARQL dei rischi → grounding → generazione LLM); `POST /analyze/baseline`
è la variante senza LLM usata per l'ablation. I moduli di supporto — geocoding,
client Overpass, mapping OSM→ontologia, executor SPARQL, client LLM
provider-agnostico e pipeline RAG — sono cablati dall'orchestratore.

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

L'app espone, tra gli altri, `GET /health` → `{"status": "ok", "ontology_triples": <n>}`
e `GET /cities` (città supportate).

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
│   └── crime_risk_analyzer/        # package applicativo (src-layout)
│       ├── __init__.py             # __version__
│       ├── main.py                 # create_app() + app + endpoint (/health, /cities, POST /analyze, POST /analyze/baseline) + CORS + lifespan
│       ├── config.py               # Settings (env, pydantic-settings)
│       ├── errors.py               # errori di dominio + mappatura errore → HTTP
│       ├── ontology.py             # caricamento ontologia RDF in memoria (rdflib)
│       ├── ontology_materialize.py # materializzazione offline OWL → Turtle (tool one-shot)
│       ├── ontology_namespaces.py  # IRI/namespace TERMINUS (single source of truth)
│       ├── geocoding.py            # geocoding zone
│       ├── overpass_client.py      # client Overpass per POI OSM
│       ├── orchestrator.py         # cabla la pipeline di /analyze e /analyze/baseline (run_analysis/run_baseline)
│       ├── sparql_module/          # mapping OSM → TERMINUS + executor SPARQL (rischi via OWL restriction)
│       ├── llm/                    # client LLM provider-agnostico (Claude/Groq)
│       ├── rag/                    # pipeline RAG: retrieval, grounding, generation
│       ├── i18n/                   # vocabolario controllato EN → IT dell'ontologia TERMINUS
│       ├── eval/                   # harness di valutazione, metriche e CLI (python -m crime_risk_analyzer.eval)
│       └── models/                 # modelli dati condivisi (geo, risk, vocab)
├── ontology/             # ontologia RDF, query SPARQL, mapping OSM — file NON versionati (zona ghost)
├── data/                 # dataset e modelli pesanti — NON versionati (zona ghost)
└── tests/                # test automatici (pytest)
```
