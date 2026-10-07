"""Script di misura del budget (#345, D14, F9 della review finale).

Senza ontologia reale: contesti sintetici. Lo script deve preparare la richiesta
ESATTAMENTE come ``generate_analysis`` (stessa funzione), e la ricerca del budget
deve guardare anche sopra il default.
"""

from __future__ import annotations

from typing import Any

from scripts.istat_budget import budget_suggerito, misura

from crime_risk_analyzer.rag.generation import (
    DEFAULT_MAX_TOKENS,
    SYSTEM_PROMPT_ISTAT,
    _estimate_tokens,  # pyright: ignore[reportPrivateUsage]
    generate_analysis,
    prepara_richiesta_zona,
)
from tests.istat._fattorie import BANKROB, istat_poi
from tests.test_generation_istat import (
    _ctx,  # pyright: ignore[reportPrivateUsage]
    _poi,  # pyright: ignore[reportPrivateUsage]
    _Spia,  # pyright: ignore[reportPrivateUsage]
)


def _molti_poi(con_istat: bool) -> dict[str, Any]:
    return _ctx(
        *(
            _poi(f"node/{i}", istat=istat_poi(BANKROB) if con_istat else None)
            for i in range(40)
        )
    )


def _budget_stretto() -> int:
    """Budget che col prompt ISTAT lascia poco spazio: la selezione dei POI cambia."""
    return _estimate_tokens(SYSTEM_PROMPT_ISTAT) + DEFAULT_MAX_TOKENS + 200


def test_istat_acceso_senza_righe_misura_come_istat_spento() -> None:
    """Il gate di ``generate_analysis``: senza righe ISTAT, tutto come a spento."""
    ctx = _molti_poi(con_istat=False)
    acceso = misura("z", ctx, istat=True, budget=_budget_stretto())
    spento = misura("z", ctx, istat=False, budget=_budget_stretto())
    assert acceso._replace(istat=False) == spento


async def test_la_misura_e_la_richiesta_che_generate_analysis_invia() -> None:
    for con_istat in (False, True):
        ctx = _molti_poi(con_istat)
        for istat in (False, True):
            spia = _Spia()
            await generate_analysis(
                ctx, spia, istat=istat, request_token_budget=_budget_stretto()
            )
            richiesta = prepara_richiesta_zona(
                ctx, istat=istat, request_token_budget=_budget_stretto()
            )
            assert spia.calls == [(richiesta.system_prompt, richiesta.contesto.testo)]
            m = misura("z", ctx, istat=istat, budget=_budget_stretto())
            assert m.stima_totale == (
                _estimate_tokens(richiesta.system_prompt)
                + _estimate_tokens(richiesta.contesto.testo)
                + DEFAULT_MAX_TOKENS
            )
            assert m.poi_inclusi == richiesta.contesto.poi_inclusi


def test_budget_suggerito_cerca_anche_sopra_il_default() -> None:
    casi = [("z", _molti_poi(con_istat=True))]
    # Contatore che non pesa niente: ogni budget della ricerca sta sotto il limite,
    # quindi il suggerito e' il piu' alto dell'intervallo, non il default.
    assert budget_suggerito(casi, reali=lambda _testo: 0) == 12000


def test_budget_suggerito_none_se_nessun_budget_sta_sotto_il_limite() -> None:
    casi = [("z", _molti_poi(con_istat=True))]
    assert budget_suggerito(casi, reali=lambda _testo: 10**6) is None
