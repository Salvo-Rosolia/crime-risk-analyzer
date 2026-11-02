"""Shared domain models and vocabularies (Pydantic v2 + base types).

Single point for the types crossing several layers: the typed vocabulary of the
citation layer (:mod:`.vocab`), the geographic bounding box (:mod:`.geo`) and the
per-POI risk profile produced by the SPARQL executor
(:class:`.risk.PoiRiskProfile`).
"""
