"""Set attivo per richiesta via ContextVar (#411)."""

import asyncio
import dataclasses

import pytest
from starlette.concurrency import run_in_threadpool

from crime_risk_analyzer.sources.context import (
    bind,
    current,
    current_executor,
    default_set,
)
from crime_risk_analyzer.sources.model import SourceSet


def _altro(id_: str) -> SourceSet:
    return dataclasses.replace(default_set(), id=id_, kind="custom")


def test_fuori_da_bind_e_default() -> None:
    assert current() is default_set()
    assert current_executor() is default_set().executor


def test_dentro_bind_e_il_set_passato_poi_torna_default() -> None:
    x = _altro("x")
    with bind(x):
        assert current() is x
        assert current_executor() is x.executor
    assert current() is default_set()


def test_bind_annidati_ripristinano_il_precedente() -> None:
    x, y = _altro("x"), _altro("y")
    with bind(x):
        with bind(y):
            assert current() is y
        assert current() is x
    assert current() is default_set()


def test_bind_ripristina_anche_con_eccezione() -> None:
    with pytest.raises(RuntimeError):
        with bind(_altro("x")):
            raise RuntimeError("boom")
    assert current() is default_set()


async def test_bind_non_si_vede_fra_task_diversi() -> None:
    visti: dict[str, str] = {}
    pronto = asyncio.Event()

    async def con_set(nome: str) -> None:
        with bind(_altro(nome)):
            await pronto.wait()
            visti[nome] = current().id

    async def senza_set() -> None:
        await asyncio.sleep(0)
        visti["nessuno"] = current().id
        pronto.set()

    await asyncio.gather(con_set("a"), con_set("b"), senza_set())
    assert visti == {"a": "a", "b": "b", "nessuno": "default"}


async def test_visibile_nel_threadpool() -> None:
    with bind(_altro("x")):
        assert await run_in_threadpool(lambda: current().id) == "x"
