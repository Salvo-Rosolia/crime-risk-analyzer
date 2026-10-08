# Dati ISTAT sui delitti denunciati — #345

## Fonte
- Dataset ISTAT **73_67** (ex `DCCV_DELITTIPS`), "Delitti denunciati dalle forze di polizia all'autorità giudiziaria", estratto via API SDMX di `esploradati.istat.it`. URL e data di estrazione sono nell'intestazione di `delitti.json`.
- Misure: `CRIMEN` (numero di delitti denunciati) e `CRIMET` (delitti per 100.000 abitanti); autore totale (`9`), periodo anno intero (`YRDUR`). Sono delitti che le forze di polizia hanno denunciato all'autorità giudiziaria, non denunce dei cittadini.
- Confini: ISTAT, confini amministrativi generalizzati al 1/1/2024 (`Limiti01012024_g`: province e città metropolitane, comuni) e al 2001 (`Limiti2001_g`: le 4 province sarde storiche). I file si chiamano `*_WGS84` ma sono in WGS84 UTM 32N (EPSG:32632): lo script li riproietta in coordinate geografiche (EPSG:4326).
- Licenza: **CC BY 4.0** (dati e confini ISTAT). Attribuzione anche in `NOTICE`.

## Contenuto
- `delitti.json`: per le 106 province, i 108 comuni capoluogo e l'Italia, per ogni voce collegata a un hazard (`mappatura.py`) più `TOT`: delitti e tasso di `anno` (2024) e di `anno_confronto` (2014). `tasso: null` con `tasso_sotto_soglia: true` corrisponde al flag ISTAT "il dato non raggiunge la metà della cifra minima considerata" e si mostra come "meno di 0,1 ogni 100.000 abitanti".
- `luoghi.json`: un `MultiPolygon` semplificato (coordinate `lon, lat`) per luogo, con codice del dataset, nome, tipo, riquadro, punto interno e, per i comuni, la provincia del dataset.
- `mappatura.py`: tabella hazard → voce ISTAT (D3).
- `catalogo.py`: le 56 voci del dataset 73_67 (codelist CL_REATI_PS v1.0) con etichetta, voce madre, voci legate al luogo e rottura 2016; per le voci che nessun hazard usa, lo stato (`usabile`/`esclusa`, `cornice` per il totale) e il motivo. L'uso è derivato da `mappatura.py`.

## Conversione dei codici
- Comuni capoluogo: codice comune ISTAT a 6 cifre (`PRO_COM_T`), uguale nel dataset e nei confini 2024.
- Province: tabella esplicita `PROVINCIA_NUTS` in `scripts/istat_refresh.py` (codice provincia ISTAT → codice NUTS3 del dataset; es. 58 → ITE43 Roma, 15 → ITC45 Milano, 108 → IT108 Monza e della Brianza, 109 → IT109 Fermo, 110 → IT110 Barletta-Andria-Trani, 21 → ITD10 Bolzano, 22 → ITD20 Trento, 19 → ITC4A Cremona, 20 → ITC4B Mantova, 53 → ITE1A Grosseto). Lo script la verifica a ogni esecuzione confrontando i nomi dei confini con la codelist `CL_ITTER107`.
- Sardegna: il dataset usa le 4 province storiche ITG25 Sassari, ITG26 Nuoro, ITG27 Cagliari, ITG28 Oristano con i confini all'inizio del 2001 (nota ISTAT). I loro poligoni vengono dai confini 2001, non dai comuni attuali: nessuna assegnazione comune per comune, quindi nessun margine d'errore (es. Bosa, in provincia di Oristano dal 2005, cade in ITG26 come nel dataset).

## Limiti
- Un solo poligono per provincia (confini 2024) per entrambi gli anni: i comuni passati di provincia fra 2014 e 2024 (Sappada da Belluno a Udine nel 2017; Montecopiolo e Sassofeltrio da Pesaro e Urbino a Rimini nel 2021) sono attribuiti alla provincia del 2024.
- Poligoni semplificati (circa 200 m per le province, 50 m per i comuni): un punto a pochi metri da un confine può cadere nel luogo vicino o in nessuno.
- Dati fermi all'anno di riferimento; granularità comune o provincia, mai zona o POI.

## Aggiornamento
Da `backend/`: `uv run python scripts/istat_refresh.py` (solo `delitti.json`), con `--confini` anche `luoghi.json`. Dopo l'aggiornamento serve il riavvio dell'app (dati in cache di processo).
