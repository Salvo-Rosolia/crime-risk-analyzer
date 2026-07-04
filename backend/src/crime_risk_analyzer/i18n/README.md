# Vocabolario controllato EN→IT (TERMINUS) — #77

## Fonte
Sottografo affiorante dell'ontologia ENEA **TERMINUS-Crime v01**
(`http://www.enea-terin-sen-apic.it/TERMINUS-crime-v01#`): i POI raggiungibili da
`sparql_module/osm_mapping.py` più gli hazard / eventi critici / vulnerabilità
collegati via `owl:Restriction`.

## Convenzione
Ogni voce di `terminus_labels.json` ha:
- `identifier` — nome-classe **reale** dell'ontologia (refusi inclusi). È ciò che
  SPARQL vincola e la citazione referenzia: **non va mai corretto**.
- `label_en` — EN leggibile, con i refusi noti corretti (solo display).
- `label_it` — termine italiano controllato (UI, narrativa, matching eval).
- `category` — `poi` | `hazard` | `critical_event` | `vulnerability`.

## Provenienza
Il set EN è estratto in modo deterministico da `i18n/extract.py`
(`uv run python -m crime_risk_analyzer.i18n.extract`). Le etichette IT sono
**curazione d'autore** (vocabolario controllato), non traduzione automatica; la
ri-esecuzione dell'estrazione conserva le IT già curate (`merge_preserving_it`).

## Refusi noti corretti (solo in `label_en`/`label_it`)
- `Brank_branch` → "Branch robbery"
- `Buiding_damage` → "Building damage"
