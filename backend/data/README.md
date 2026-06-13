# Dati e modelli — zona *ghost* (non versionata)

Questa cartella ospita **dataset e modelli pesanti** che **NON devono essere
committati**. Sono esclusi via `.gitignore` (root del repo) e vivono nella cosiddetta
*zona ghost*: presenti in locale, mai tracciati da git.

## Cosa NON va versionato

- Estratti OpenStreetMap (`.osm`, `.pbf`, `.gpkg`)
- Dataset criminalità / geospaziali (`.csv`, `.geojson`, `.parquet`, archivi `.zip`/`.gz`)
- Modelli, embeddings e indici vettoriali (`.bin`, `.pt`, `.safetensors`, `.gguf`)

## Cosa è tracciato

Solo questo `README.md` (più un eventuale `.gitkeep`), per mantenere la cartella nel
repository.

## Popolare i dati in locale

1. Scaricare/generare i dataset e collocarli qui sotto (es. `backend/data/osm/`,
   `backend/data/crime/`).
2. I percorsi attesi verranno documentati dalle story che li consumano.
3. Nulla di ciò che metti qui finirà in un commit: è già coperto da `.gitignore`.

> Se un file specifico deve invece essere versionato (es. un piccolo campione di
> esempio), forzane l'inclusione con `git add -f <file>` e aggiorna `.gitignore`.
