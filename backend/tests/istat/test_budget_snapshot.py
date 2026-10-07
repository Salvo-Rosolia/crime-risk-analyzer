"""Budget del prompt con ISTAT acceso sulle 4 zone di valutazione (#345, D14).

Usa l'ontologia reale (ghost): in CI il test salta. Si esegue in locale prima della
PR e a ogni cambio di budget, prompt o dati.
"""

from __future__ import annotations

import pytest
from scripts.istat_budget import ONTOLOGIA, contesti, misura

from crime_risk_analyzer.rag.generation import DEFAULT_REQUEST_TOKEN_BUDGET

pytestmark = pytest.mark.skipif(
    not ONTOLOGIA.exists(), reason="ontologia reale assente (non e' nel repo)"
)


async def test_con_istat_acceso_ogni_zona_ha_il_blocco_e_sta_nel_budget() -> None:
    casi = await contesti()
    assert len(casi) == 4
    for zona, ctx in casi:
        spento = misura(zona, ctx, istat=False)
        acceso = misura(zona, ctx, istat=True)
        assert acceso.voci_istat > 0, zona  # la riserva tiene il blocco nel prompt
        assert acceso.stima_totale <= DEFAULT_REQUEST_TOKEN_BUDGET, zona
        assert spento.stima_totale <= DEFAULT_REQUEST_TOKEN_BUDGET, zona
        assert acceso.poi_inclusi <= spento.poi_inclusi, zona
