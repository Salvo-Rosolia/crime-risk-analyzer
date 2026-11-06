"""Shared test configuration.

Before any ``Settings`` is built, point ``ONTOLOGY_PATH`` to the committed
Turtle fixture: the ``lifespan`` warm-up (and ``get_ontology``) find a valid
graph even before the professor delivers the real ontology.
``setdefault`` does not overwrite a value already present in the environment.

The ``lifespan`` also warms up the LLM client (fail-fast on a missing key,
#111): without a key the app startup would fail and every test entering the
lifespan via ``with TestClient(app)`` would break. We provide dummy keys with
the same ``setdefault`` used for ``ONTOLOGY_PATH`` -- no network: the
Anthropic/Groq SDKs do not validate the key when the client is built. The
fail-fast test removes the key in a targeted way (see ``test_lifespan.py``).
"""

import os
from pathlib import Path

import pytest

_FIXTURE = Path(__file__).parent / "fixtures" / "ontology_sample.ttl"
os.environ.setdefault("ONTOLOGY_PATH", str(_FIXTURE))
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")
os.environ.setdefault("GROQ_API_KEY", "gsk-test-dummy")
# No public Overpass mirrors in tests (#509): they must never touch the network.
os.environ.setdefault("OVERPASS_FALLBACK_URLS", "[]")


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip ``integration`` tests (real network) unless explicitly selected.

    They run only when the user passes ``-m integration`` (or an expression
    that includes it); the default suite stays offline and deterministic.
    """
    expr = config.getoption("-m")
    if isinstance(expr, str) and "integration" in expr:
        return
    skip = pytest.mark.skip(reason="integration test: use -m integration")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
