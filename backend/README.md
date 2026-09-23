# Backend — Crime Risk Analyzer

API e logica di dominio del sistema: query geospaziali, ragionamento ontologico
(SPARQL) e pipeline RAG con ragionamento LLM. L'app FastAPI carica l'ontologia RDF
in memoria all'avvio ed espone gli endpoint `GET /health`, `GET /geocode`,
`POST /analyze`, `POST /analyze/narrativa`, `POST /analyze/baseline` e
`POST /analyze/poi`. L'input di ricerca è un cerchio disegnato sulla mappa
(centro `{lat, lon}` + `radius_m`, non più città/zona testuali): `resolve_circle`
lo traduce in un bounding box circoscritto e, best-effort, in un'etichetta
città/zona (reverse geocode Nominatim, solo per display/narrativa — un fallimento
non blocca mai l'analisi). L'analisi di zona è divisa in due fasi: `POST /analyze`
esegue la pipeline dei dati sul cerchio (bbox circoscritto → POI OSM via Overpass →
mapping OSM→TERMINUS → query SPARQL dei rischi → grounding → filtro per raggio) e
risponde subito con `narrativa: null`, mentre `POST /analyze/narrativa` genera il
testo con l'LLM sullo stesso contesto — così mappa e lista non aspettano la
latenza del provider. `POST /analyze/poi` fa lo stesso per il singolo punto
selezionato; `POST /analyze/baseline` è la variante senza LLM usata per l'ablation
(accetta `tipo_poi` ma non `domanda`, mentre `POST /analyze/narrativa` accetta
`domanda` ma non `tipo_poi`: asimmetria nota fra i due bracci del confronto,
tracciata da #263 e non ancora chiusa perché dipende dalla decisione sul contratto
di `tipo_poi` FE-BE, #143). `GET /geocode` è un forward-geocode indipendente
dal contratto di ricerca: serve solo la casella "vai a un luogo" del frontend
(ricentra la mappa, non seleziona un'area da analizzare). I moduli di supporto —
geocoding, client Overpass, mapping OSM→ontologia, executor SPARQL, client LLM
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
e `GET /geocode?query=...` → `{"lat": <float>, "lon": <float>}` (forward-geocode di un
luogo libero, per la casella "vai a un luogo" del frontend — 404 se non trovato).

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
│       ├── main.py                 # create_app() + app + endpoint (/health, /geocode, POST /analyze, POST /analyze/narrativa, POST /analyze/baseline, POST /analyze/poi) + CORS + lifespan
│       ├── analyze_narrative.py    # le due fasi dell'analisi di zona: dati subito (run_analysis_fast) + narrativa a parte (run_zone_narrative)
│       ├── poi_narrative.py        # narrativa del singolo POI selezionato (run_poi_narrative)
│       ├── circle_search.py        # risolve un cerchio (centro+raggio) in un GeoSource + un'etichetta città/zona best-effort (reverse geocode)
│       ├── config.py               # Settings (env, pydantic-settings)
│       ├── context_fingerprint.py  # impronta della lista POI di un contesto di zona (identità, non misura)
│       ├── errors.py               # errori di dominio + mappatura errore → HTTP
│       ├── ontology.py             # caricamento ontologia RDF in memoria (rdflib)
│       ├── ontology_materialize.py # materializzazione offline OWL → Turtle (tool one-shot)
│       ├── ontology_namespaces.py  # IRI/namespace TERMINUS (single source of truth)
│       ├── geocoding.py            # geocoding forward/reverse (Nominatim) + bbox della zona
│       ├── overpass_client.py      # client Overpass per POI OSM
│       ├── orchestrator.py         # cabla la pipeline: layer RAG + contratto della response (/analyze/baseline via run_baseline; run_analysis = percorso sincrono completo, ormai solo per la valutazione) + il braccio di ablazione con prompt senza ontologia (run_no_ontology_prompt, solo valutazione)
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
