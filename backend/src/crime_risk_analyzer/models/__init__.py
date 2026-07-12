"""Modelli e vocabolari condivisi del dominio (Pydantic v2 + tipi base).

Punto unico per i tipi attraversati da piu' layer: il vocabolario tipizzato del
citation layer (:mod:`.vocab`), il bounding box geografico (:mod:`.geo`) e il
profilo di rischio per POI prodotto dall'executor SPARQL
(:class:`.risk.PoiRiskProfile`).
"""
