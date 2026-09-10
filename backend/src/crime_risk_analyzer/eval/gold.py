"""Annotazione gold dei rischi per valutazione della copertura narrativa (#152).

Modulo in fase di riscrittura: l'implementazione della nuova annotazione
per-rischio (costruita a valle della generazione narrativa, incrociando il set
grounded con i rischi effettivamente citati) arriva nel prossimo task (#152).

Sostituisce il meccanismo per-run deprecato (che confrontava metriche proxy
con annotazioni umane globali della narrativa, #109): quel codice è stato
rimosso in questa sessione. La nuova annotazione opererà a granularità di
singolo rischio, permettendo al tesista di marcare "citato" o "mancato"
per ogni elemento del set di grounding.
"""

from __future__ import annotations
