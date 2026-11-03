"""Active set per request via ContextVar (#411)."""

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


def _other_set(id_: str) -> SourceSet:
    return dataclasses.replace(default_set(), id=id_, kind="custom")


def test_outside_bind_is_default() -> None:
    assert current() is default_set()
    assert current_executor() is default_set().executor


def test_inside_bind_is_the_given_set_then_back_to_default() -> None:
    x = _other_set("x")
    with bind(x):
        assert current() is x
        assert current_executor() is x.executor
    assert current() is default_set()


def test_nested_binds_restore_the_previous_one() -> None:
    x, y = _other_set("x"), _other_set("y")
    with bind(x):
        with bind(y):
            assert current() is y
        assert current() is x
    assert current() is default_set()


def test_bind_restores_even_with_exception() -> None:
    with pytest.raises(RuntimeError):
        with bind(_other_set("x")):
            raise RuntimeError("boom")
    assert current() is default_set()


async def test_bind_is_not_visible_across_different_tasks() -> None:
    seen: dict[str, str] = {}
    ready = asyncio.Event()

    async def with_set(name: str) -> None:
        with bind(_other_set(name)):
            await ready.wait()
            seen[name] = current().id

    async def without_set() -> None:
        await asyncio.sleep(0)
        seen["none"] = current().id
        ready.set()

    await asyncio.gather(with_set("a"), with_set("b"), without_set())
    assert seen == {"a": "a", "b": "b", "none": "default"}


async def test_visible_in_threadpool() -> None:
    with bind(_other_set("x")):
        assert await run_in_threadpool(lambda: current().id) == "x"
