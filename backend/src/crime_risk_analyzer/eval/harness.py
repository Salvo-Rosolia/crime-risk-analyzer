"""Execution harness of an evaluation experiment (#34).

Migration constraint (#165.4): ``results/runs/`` must contain only runs in
#157 format (run_id with ``__rep{NN}`` marker). Pre-#157 legacy records for the
same experiment are detected and rejected by ``run`` (or removed with
``--clean-stale``): coexisting with ``__rep`` runs would corrupt fold/compare.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

from crime_risk_analyzer.eval.istat_metrics import (
    compute_istat_metrics,
    excluded_sentences_without_item,
)
from crime_risk_analyzer.eval.metrics import compute_metrics, m1_excluded_sentences
from crime_risk_analyzer.eval.schema import (
    ExperimentConfig,
    Metrics,
    Provenance,
    RunCase,
    RunRecord,
    RunStatus,
)
from crime_risk_analyzer.eval.snapshots import (
    describe_config_mismatch,
    offline_geo_source,
    replay_source,
    snapshot_path,
    snapshot_provenance,
)
from crime_risk_analyzer.llm.client import model_id_for_provider
from crime_risk_analyzer.orchestrator import (
    AnalyzeResponse,
    _LLMClientLike,  # pyright: ignore[reportPrivateUsage]
    run_analysis,
    run_baseline,
    run_no_ontology_prompt,
)
from crime_risk_analyzer.rag.generation import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_REQUEST_TOKEN_BUDGET,
)
from crime_risk_analyzer.rag.retrieval import RiskProfiler

logger = logging.getLogger(__name__)


def uses_model(config: ExperimentConfig) -> bool:
    """True if the arm calls the model: all except the baseline.

    A single place for this question (#357): previously every function repeated it with
    its own comparison on ``config.mode``, and a new arm without a model would have
    had to be added by hand in each.
    """
    return config.mode != "baseline"


def _run_budget(config: ExperimentConfig) -> tuple[int | None, int | None]:
    """``(request budget, max_tokens)`` with which the arm builds the prompt.

    These are the values the harness passes to :func:`run_analysis` (#345, F8 of the
    final review): they end up in the provenance because the budget decides how many
    POIs go into the prompt, and two arms with different budgets do not isolate a single
    variable. The arm without ontology runs with the same configuration: its
    prompt does not truncate, but with these values it reconstructs which POIs the
    full one kept and lists only those (#349); the baseline does not call the LLM and
    has no budget.
    """
    if not uses_model(config):
        return None, None
    return DEFAULT_REQUEST_TOKEN_BUDGET, DEFAULT_MAX_TOKENS


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def make_run_id(
    experiment: str, citta: str, zona: str, mode: str, model: str, rep: int = 0
) -> str:
    """Deterministic run_id + repetition index (#157).

    The ``__rep{NN}`` suffix (2 digits) makes the K repetitions of the same
    (experiment, citta, zona, mode, model) distinct: re-running with --repeat K does NOT
    overwrite the JSONs any more. ``rep=0`` by default (K=1) -> ``__rep00``.
    """
    parts = [experiment, citta, zona, mode, model]
    return "__".join(_slug(p) for p in parts) + f"__rep{rep:02d}"


def make_snapshot_key(citta: str, zona: str) -> str:
    """Key of the POI snapshot, derived ONLY from (citta, zona) (#110).

    Independent of mode/model: the comparative arms (analyze/claude,
    analyze/groq, baseline) on the same (citta, zona) replay the SAME
    POI fixture (iso-input comparison, unblocks #32/#33). Reuses the same
    ``_slug`` as :func:`make_run_id`, so the normalisation of citta/zona
    stays single and does not diverge between run_id and snapshot key.
    """
    return "__".join(_slug(p) for p in (citta, zona))


_REP_MARKER = re.compile(r"__rep\d{2,}$")


def is_repeated_run_id(run_id: str) -> bool:
    """True if the run_id carries the repetition marker ``__rep{NN}`` (#157)."""
    return _REP_MARKER.search(run_id) is not None


def legacy_run_paths(results_dir: Path, experiment: str) -> list[Path]:
    """Path of the experiment's records in PRE-#157 format (without ``__rep``).

    A legacy record for the same (citta, zona) of a ``__rep`` run would be
    treated as a stale repetition by fold/compare: it must be detected before
    writing new repetitions.
    """
    from crime_risk_analyzer.eval.aggregate import load_runs

    return [
        results_dir / "runs" / f"{rec.run_id}.json"
        for rec in load_runs(results_dir, experiment=experiment)
        if not is_repeated_run_id(rec.run_id)
    ]


def guard_no_legacy_runs(
    results_dir: Path, experiment: str, *, clean_stale: bool = False
) -> None:
    """Guard against pre-#157 legacy records for the experiment (#165.4).

    ``clean_stale=True`` removes them; otherwise raises ``ValueError`` with
    the list and the indication to regenerate or use ``--clean-stale``.
    """
    legacy = legacy_run_paths(results_dir, experiment)
    if not legacy:
        return
    if clean_stale:
        for path in legacy:
            path.unlink(missing_ok=True)
        return
    joined = ", ".join(str(p) for p in legacy)
    raise ValueError(
        f"run legacy pre-#157 (senza __rep) per l'esperimento '{experiment}': "
        f"{joined}. Rigenera results/runs/ o rilancia con --clean-stale."
    )


def write_record(results_dir: Path, record: RunRecord) -> Path:
    """Write the RunRecord as JSON in results/runs/<run_id>.json."""
    path = results_dir / "runs" / f"{record.run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return path


def _record_from_response(
    *,
    run_id: str,
    snapshot_id: str,
    config: ExperimentConfig,
    case: RunCase,
    model_id: str,
    resp: AnalyzeResponse,
    code_commit: str,
    ontology_hash: str,
    snapshot_catturato_il: str | None,
    snapshot_configurazione_canonica: dict[str, object] | None,
) -> RunRecord:
    status = RunStatus.FALLBACK if resp.fallback else RunStatus.OK
    # #369: with ISTAT, the sentences that M1 does not measure (None without ISTAT).
    excluded = m1_excluded_sentences(resp, mode=config.mode)
    # #378: among these, those without an item of the ISTAT rows of the prompt.
    without_item = (
        excluded_sentences_without_item(excluded, resp.controllo_istat)
        if excluded is not None and resp.controllo_istat is not None
        else None
    )
    return RunRecord(
        run_id=run_id,
        experiment=config.name,
        citta=case.citta,
        zona=case.zona,
        mode=config.mode,
        model_id=model_id,
        status=status,
        # The ``mode`` decides on which block the textual proxies pronounce
        # (#236): the ablated arm labels its block for what it is, and
        # measuring it on the other's label would give it as not attributed.
        # On records with ISTAT (#345, #369) M1 grades the raw text without the
        # sentences that speak of the ISTAT datum and name neither a POI nor a risk: it
        # is decided by ``compute_metrics`` from the check that the response carries.
        metrics=compute_metrics(resp, mode=config.mode),
        # ``resp.narrativa`` is ``str | None`` since #259 (phase 1: narrative not
        # yet generated); the harness runs only on ``run_analysis``/``run_baseline``,
        # which today always produce a string (never None) -- the coercion is
        # defensive on the type, not a change of behaviour.
        narrativa=resp.narrativa or "",
        n_poi=len(resp.poi),
        risk_models=resp.risk_models,
        # #345: raw text/ISTAT metrics only for the harness (``AnalyzeResponse``
        # excludes them from the HTTP response, ``exclude=True``).
        narrativa_grezza=resp.narrativa_grezza,
        # #349: the POIs that entered the prompt, so that the comparison VERIFIES that
        # the two LLM arms saw the same points instead of assuming it. None for
        # the baseline (no prompt) and on fallbacks (no generation).
        poi_nel_prompt=resp.poi_nel_prompt,
        istat_frasi_scartate=resp.istat_frasi_scartate,
        istat_metrics=(
            compute_istat_metrics(
                resp.controllo_istat,
                frasi_escluse_m1=len(excluded or []),
                frasi_escluse_senza_voce=(
                    None if without_item is None else len(without_item)
                ),
            )
            if resp.controllo_istat
            else None
        ),
        frasi_escluse_m1=excluded,
        frasi_escluse_senza_voce=without_item,
        provenance=Provenance(
            code_commit=code_commit,
            ontology_hash=ontology_hash,
            snapshot_id=snapshot_id,
            model_id=model_id,
            prompt_hash=resp.repro.prompt_hash,
            temperature=resp.repro.temperature,
            seed=resp.repro.seed,
            experiment=config.name,
            context_format=config.context_format,
            snapshot_catturato_il=snapshot_catturato_il,
            snapshot_configurazione_canonica=snapshot_configurazione_canonica,
            istat=config.istat,
            istat_versione_dati=resp.istat_versione_dati,
            request_token_budget=_run_budget(config)[0],
            llm_max_tokens=_run_budget(config)[1],
        ),
    )


def _error_record(
    *,
    run_id: str,
    snapshot_id: str,
    config: ExperimentConfig,
    case: RunCase,
    model_id: str,
    code_commit: str,
    ontology_hash: str,
    snapshot_catturato_il: str | None,
    snapshot_configurazione_canonica: dict[str, object] | None,
    status: RunStatus = RunStatus.ERROR,
) -> RunRecord:
    """Record of a failed case: zeroed metrics, no narrative.

    ``status`` distinguishes WHO failed (see :class:`RunStatus`): the case's
    pipeline (``ERROR``, default, produced by :func:`run_case`) or the
    downstream instrumentation (``HARNESS_ERROR``, produced by
    :func:`run_experiment`). The rest of the record is identical because identical is
    what can be said: there is nothing to measure in either case.
    """
    return RunRecord(
        run_id=run_id,
        experiment=config.name,
        citta=case.citta,
        zona=case.zona,
        mode=config.mode,
        model_id=model_id,
        status=status,
        metrics=Metrics(grounding=0.0, hallucination=0.0, latency_ms=0, cost_usd=0.0),
        narrativa="",
        n_poi=0,
        provenance=Provenance(
            code_commit=code_commit,
            ontology_hash=ontology_hash,
            snapshot_id=snapshot_id,
            model_id=model_id,
            prompt_hash="",
            temperature=0.0,
            seed=0,
            experiment=config.name,
            context_format=config.context_format,
            snapshot_catturato_il=snapshot_catturato_il,
            snapshot_configurazione_canonica=snapshot_configurazione_canonica,
            istat=config.istat,
            request_token_budget=_run_budget(config)[0],
            llm_max_tokens=_run_budget(config)[1],
        ),
    )


def _model_id_of(llm_client: _LLMClientLike | None, config: ExperimentConfig) -> str:
    """Model id of the arm: ``"baseline"``, the client's ``.model``, or the config.

    Total on purpose (accepts ``llm_client=None``): it is also needed on the ERROR
    path of :func:`run_experiment`, where a record must be written anyway and a
    second exception while describing the first would make the isolation useless.
    The rejection of an arm with a model but without a client lives elsewhere, in
    :func:`_require_llm_client`, where it is needed: before executing.
    """
    if not uses_model(config):
        return "baseline"
    model = getattr(llm_client, "model", None)
    if isinstance(model, str):
        return model
    return model_id_for_provider(config.model)


def _require_llm_client(
    config: ExperimentConfig, llm_client: _LLMClientLike | None
) -> None:
    """Raise if an arm WITH a model did not receive the client.

    Called both by :func:`run_case` and at the head of :func:`run_experiment`, and not
    only by the former: it is an impossible configuration, not the failure of a
    single case. Letting it fall into the per-case isolation would write a
    ``HARNESS_ERROR`` record for every case and every repetition -- N "failed" zones in
    the downstream comparison -- for an error known before starting, in which there is
    really nothing to save by continuing.
    """
    if uses_model(config) and llm_client is None:
        raise ValueError(f"llm_client required for mode={config.mode}")


async def run_case(
    case: RunCase,
    config: ExperimentConfig,
    *,
    executor: RiskProfiler,
    llm_client: _LLMClientLike | None = None,
    results_dir: Path,
    code_commit: str,
    ontology_hash: str,
    rep: int = 0,
) -> RunRecord:
    """Run a case and return the RunRecord (status=error on exception).

    ``llm_client`` is optional: required by the arms WITH a model (``analyze`` and
    ``no_ontology_prompt``, #236); for ``mode='baseline'`` it can be ``None``.
    Raises :class:`ValueError` if an arm with a model receives ``None``.
    """
    _require_llm_client(config, llm_client)
    model_id = _model_id_of(llm_client, config)
    run_id = make_run_id(
        config.name, case.citta, case.zona, config.mode, config.model, rep
    )
    # Snapshot keyed by (citta, zona): shared by the comparative arms (#110).
    snapshot_key = make_snapshot_key(case.citta, case.zona)
    path = snapshot_path(results_dir, snapshot_key)
    # #267: the provenance is read at most once and feeds both the warning and
    # the record (avoids reading the file twice just for the provenance --
    # the POI payload is however re-parsed by ``load_snapshot`` inside
    # ``replay_source``, which serves a different purpose: reading the points, not
    # inspecting the provenance). A MISSING snapshot is not a provenance
    # case to report: it is a different failure, already handled further
    # below when ``replay_source`` really consumes it (isolation #252) -- here it
    # would warn with a misleading message ("configuration not known") right
    # before the real "file absent" error.
    provenance = snapshot_provenance(path) if path.exists() else None
    if path.exists():
        mismatch = describe_config_mismatch(provenance)
        if mismatch is not None:
            logger.warning(
                "snapshot (%s, %s): %s — la run potrebbe mescolare politiche di "
                "selezione diverse senza saperlo (#267)",
                case.citta,
                case.zona,
                mismatch,
            )
    # Defensive on the TYPE, not only on presence: ``provenance`` comes from external
    # JSON cast to TypedDict, so ``catturato_il`` may not be a
    # string despite the declared type -- an invalid value here must not
    # make ``Provenance(...)`` blow up (pydantic would not coerce int->str) and
    # with it the whole experiment.
    _captured_at = provenance.get("catturato_il") if provenance else None
    snapshot_catturato_il = _captured_at if isinstance(_captured_at, str) else None
    _conf = provenance.get("configurazione_canonica") if provenance else None
    snapshot_configurazione_canonica = dict(_conf) if isinstance(_conf, dict) else None
    source = replay_source(path)
    # #349: budget and max_tokens from ONE single point, the same that writes them into
    # the provenance, for both LLM arms: two literals in the two calls
    # could diverge from what the record declares.
    budget, max_tok = _run_budget(config)
    # Deterministic placeholder geo (#169): the run replays the POIs and must never
    # call Nominatim. The geo is dead-downstream, so the value does not matter.
    geo_source = offline_geo_source()
    try:
        if config.mode == "baseline":
            resp = await run_baseline(
                case.citta,
                case.zona,
                executor=executor,
                poi_source=source,
                geo_source=geo_source,
            )
        elif config.mode == "no_ontology_prompt":
            # narrowing for pyright strict
            assert llm_client is not None and budget is not None
            assert max_tok is not None
            # Ablation arm (#236): same ``source``/``geo_source`` as the full
            # arm -- i.e. the SAME POI snapshot, which is the point.
            # #349: also the same prompt parameters of the full arm
            # (budget, max_tokens, format, switch), with which the ablated one
            # reconstructs which POIs that prompt kept and lists all and only those.
            # The format here is always ``per_poi`` (the schema rejects the others for
            # this mode) and the switch always off (D6): the iso-input therefore holds
            # against a full arm launched with those values, i.e. the
            # thesis ``ablation-*-groq`` pair; a ``per_classe`` full arm
            # would choose other POIs. Parity is not presumed: the two records
            # save ``poi_nel_prompt`` and ``eval/compare.py`` verifies it.
            resp = await run_no_ontology_prompt(
                case.citta,
                case.zona,
                executor=executor,
                llm_client=llm_client,
                poi_source=source,
                geo_source=geo_source,
                context_format=config.context_format,
                istat_context_enabled=config.istat,
                request_token_budget=budget,
                max_tokens=max_tok,
            )
        else:
            # narrowing for pyright strict
            assert llm_client is not None and budget is not None
            assert max_tok is not None
            resp = await run_analysis(
                case.citta,
                case.zona,
                executor=executor,
                llm_client=llm_client,
                poi_source=source,
                geo_source=geo_source,
                context_format=config.context_format,
                istat_context_enabled=config.istat,
                request_token_budget=budget,
                max_tokens=max_tok,
            )
    except Exception:  # noqa: BLE001 -- a broken case does not block the experiment
        return _error_record(
            run_id=run_id,
            snapshot_id=snapshot_key,
            config=config,
            case=case,
            model_id=model_id,
            code_commit=code_commit,
            ontology_hash=ontology_hash,
            snapshot_catturato_il=snapshot_catturato_il,
            snapshot_configurazione_canonica=snapshot_configurazione_canonica,
        )
    # Outside the try on purpose: the metrics computation is not an event to
    # absorb as "the model failed". A ``KeyError`` from the price list
    # (#34) on an unpriced model_id is a code/configuration bug, and
    # inside the try it would become a status=ERROR record with zeroed metrics,
    # indistinguishable from a failed LLM call: in a live run it
    # would burn the day's quota producing 100% ERROR records
    # without a single traceback to read.
    # The exception therefore leaves from here, but NO longer reaches the top: it is
    # caught by ``run_experiment`` one level up, which logs it with the traceback and
    # assigns it a status of its own (``HARNESS_ERROR``). The two halves say
    # different things -- here "do not mask", there "do not let the experiment die" --
    # and both are needed.
    return _record_from_response(
        run_id=run_id,
        snapshot_id=snapshot_key,
        config=config,
        case=case,
        model_id=model_id,
        resp=resp,
        code_commit=code_commit,
        ontology_hash=ontology_hash,
        snapshot_catturato_il=snapshot_catturato_il,
        snapshot_configurazione_canonica=snapshot_configurazione_canonica,
    )


async def run_experiment(
    config: ExperimentConfig,
    *,
    executor: RiskProfiler,
    llm_client: _LLMClientLike | None = None,
    results_dir: Path,
    code_commit: str,
    ontology_hash: str,
    repeat: int = 1,
    clean_stale: bool = False,
    pause_seconds: float = 0.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[RunRecord]:
    """Run all the cases ``repeat`` times, write the JSONs, return the records.

    ``llm_client`` is optional: it can be ``None`` for ``mode='baseline'``;
    for the arms with a model it must be supplied, and its absence is rejected
    at once (:func:`_require_llm_client`) instead of turning into N failed records.

    ``repeat`` (#157): K repetitions to estimate the variance; each repetition
    has a distinct ``rep`` in the run_id (no overwriting). Default 1.

    A case that blows up does not stop the experiment: the exception is logged with
    the traceback and the case gets a ``status=HARNESS_ERROR`` record (distinct from
    ``ERROR``, which describes a pipeline failure -- see
    :class:`~crime_risk_analyzer.eval.schema.RunStatus`). No metric is
    invented: the record stays zeroed and is excluded from the downstream means.

    ``clean_stale`` (#165.4): if ``True`` removes the pre-#157 legacy records
    of the experiment before running; otherwise the guard raises
    :class:`ValueError` if it finds any (coexisting with ``__rep`` runs corrupts
    fold/compare).

    Raises :class:`ValueError` if ``repeat < 1`` (no silently empty experiment:
    without a guard ``range(repeat)`` would return ``[]``).

    ``pause_seconds`` (#357): wait BEFORE every case of the arms that call the
    model, first call included. On the free provider one call of the
    arm with ontology uses almost the whole tokens-per-minute cap: two
    calls in a row made the second one time out, i.e. a fallback
    answer discarded by the comparison. It waits also before the first one because the
    two arms run as two commands launched one after the other: without it, the first
    call of the second would fall in the same minute as the last of the first. Every
    wait is announced in the log (WARNING), so a long run is not mistaken for
    a hang. Declared limits: it also waits before a case that then fails
    without reaching the model (not known in advance); the ``sleep`` does not enter the
    measured latency, but after long pauses the call reopens the connection and its
    time (tens of milliseconds) enters the latency. Default 0 =
    previous behaviour; negative or non-finite values are rejected. ``sleep``
    is injectable for tests.
    """
    if repeat < 1:
        raise ValueError(f"repeat deve essere >= 1, ricevuto {repeat}")
    if not math.isfinite(pause_seconds) or pause_seconds < 0:
        raise ValueError(
            f"pause_seconds deve essere un numero finito >= 0, ricevuto {pause_seconds}"
        )
    should_wait = pause_seconds > 0 and uses_model(config)
    _require_llm_client(config, llm_client)
    guard_no_legacy_runs(results_dir, config.name, clean_stale=clean_stale)
    records: list[RunRecord] = []
    for rep in range(repeat):
        for case in config.cases:
            if should_wait:
                logger.warning(
                    "pausa di %s s prima di (%s, %s) rep %d: tetto di token al minuto "
                    "del provider (#357)",
                    pause_seconds,
                    case.citta,
                    case.zona,
                    rep,
                )
                await sleep(pause_seconds)
            try:
                record = await run_case(
                    case,
                    config,
                    executor=executor,
                    llm_client=llm_client,
                    results_dir=results_dir,
                    code_commit=code_commit,
                    ontology_hash=ontology_hash,
                    rep=rep,
                )
            except Exception as exc:  # noqa: BLE001 -- see the comment below
                # What ``run_case`` lets through (metrics/price list,
                # or a badly configured arm) would die here taking with it
                # ALL the following cases and repetitions. On a live run with a
                # daily quota it is the worst damage: the quota already spent does not
                # come back, and a ``model_id`` outside the price list would burn all of
                # it at the first case without even finishing the experiment.
                # It is not the old wide try inside ``run_case``: there the error
                # vanished inside a record indistinguishable from "the model
                # failed", here it comes out with its traceback (``logger.exception``)
                # and with a status that says so (``HARNESS_ERROR``).
                logger.exception(
                    "harness fallito su (%s, %s) rep %d: %s — record marcato "
                    "'%s', l'esperimento prosegue",
                    case.citta,
                    case.zona,
                    rep,
                    exc,
                    RunStatus.HARNESS_ERROR.value,
                )
                record = _error_record(
                    run_id=make_run_id(
                        config.name,
                        case.citta,
                        case.zona,
                        config.mode,
                        config.model,
                        rep,
                    ),
                    snapshot_id=make_snapshot_key(case.citta, case.zona),
                    config=config,
                    case=case,
                    model_id=_model_id_of(llm_client, config),
                    code_commit=code_commit,
                    ontology_hash=ontology_hash,
                    # Snapshot provenance not reported: here it is not known at
                    # what point the case broke, and re-reading the file to
                    # describe it would risk a second
                    # exception while handling the first. ``None`` = "not
                    # detected", which is the truth available.
                    snapshot_catturato_il=None,
                    snapshot_configurazione_canonica=None,
                    status=RunStatus.HARNESS_ERROR,
                )
            write_record(results_dir, record)
            records.append(record)
    return records
