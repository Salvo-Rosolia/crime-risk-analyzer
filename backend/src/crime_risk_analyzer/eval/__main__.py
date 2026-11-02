"""Entry point: uv run python -m crime_risk_analyzer.eval <command> ..."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from crime_risk_analyzer.config import get_settings
from crime_risk_analyzer.eval.aggregate import load_runs, write_tables
from crime_risk_analyzer.eval.city_agnostic import ROSTER, capture_roster
from crime_risk_analyzer.eval.city_agnostic_report import build_report
from crime_risk_analyzer.eval.cli import (
    build_llm_eval_client,
    build_parser,
    code_commit,
    load_config,
    ontology_hash,
)
from crime_risk_analyzer.eval.compare import NoUsableOutputError, compare_experiments
from crime_risk_analyzer.eval.gold import (
    WORKSHEET_FILENAME,
    collect_kept_risks,
    write_gold_worksheet,
    write_precision_report,
)
from crime_risk_analyzer.eval.harness import (
    make_snapshot_key,
    run_experiment,
    uses_model,
)
from crime_risk_analyzer.eval.repeated_comparison import build_repeated_report
from crime_risk_analyzer.eval.snapshots import (
    PoiSourceWithCut,
    capturing_source,
    describe_config_mismatch,
    load_snapshot,
    offline_fetch_pois,
    snapshot_path,
    snapshot_provenance,
)
from crime_risk_analyzer.models.geo import Bbox
from crime_risk_analyzer.ontology import load_ontology
from crime_risk_analyzer.orchestrator import run_baseline
from crime_risk_analyzer.overpass_client import OsmCut, Poi
from crime_risk_analyzer.rag.retrieval import PoiSource
from crime_risk_analyzer.sparql_module.query_executor import get_executor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CaptureCase:
    """A case (citta, zona), succeeded or failed, for the summary of _capture."""

    citta: str
    zona: str
    error_type: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class CaptureSummary:
    """Overall outcome of ``_capture`` (#252): who was captured, who was not.

    Tuple fields (not list): the immutability declared by ``frozen=True``
    would otherwise be only a facade (a list stays mutable in place).
    """

    succeeded: tuple[CaptureCase, ...]
    failed: tuple[CaptureCase, ...]


def _snapshot_reusable(path: Path) -> bool:
    """True if the existing snapshot is reusable on skip (#148).

    Reusable = the file exists, is non-empty (``size > 0``) AND is parseable JSON.
    A truncated/corrupt snapshot (interrupted write) is NOT reusable: it must be
    re-captured instead of being silently replayed (previously recoverable
    only with ``--force``). Light check: it does not validate every POI, only that the
    file ``load_snapshot`` can read without blowing up.

    Boundary of the check (deliberate):
    - Guaranteed invariant = **parse-safe for replay**: if the check passes, the
      replay's ``load_snapshot`` will not blow up in parse. It is NOT "shape-valid":
      a valid JSON snapshot that is semantically wrong (e.g. POIs lacking the
      expected keys) is NOT caught -- schema validation is out of scope.
      Since #241 the boundary shifts slightly: a valid JSON file whose shape
      ``load_snapshot`` does not recognise (neither bare list nor envelope) raises
      ``ValueError`` and is treated as not reusable, hence re-captured,
      instead of making the capture blow up.
    - Environmental errors (``OSError``/``PermissionError`` on ``stat``/read) are NOT
      caught on purpose: wanted fail-loud and, the capture being
      idempotent, a re-run resumes anyway from the cases already captured.
    - It does NOT check the presence of the OSM cut in the provenance (#251): an
      envelope-format snapshot written between #241 and #251 stays reusable even
      without that field. The acceptance criterion of #251 asks that existing
      snapshots stay readable and replayable, not that they be
      updated -- an operator who wants it for already captured zones repeats with
      ``--force``, the same route already required for any other update of the
      canonical configuration.
    """
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        load_snapshot(path)
    # A single clause: ``json.JSONDecodeError`` and ``UnicodeDecodeError`` are
    # both subclasses of ``ValueError``, which also covers the unrecognised
    # format raised by ``load_snapshot`` (#241).
    except ValueError:
        return False
    return True


def _without_cut(source: PoiSource) -> PoiSourceWithCut:
    """Adapt a plain ``PoiSource`` to the OSM-cut contract of
    :func:`capturing_source` (#251).

    Needed ONLY for the ``_capture`` test doubles (``poi_source`` parameter,
    #252): those stay plain ``(bbox, citta) -> list[Poi]`` without having to
    fabricate a cut they do not know, and ``None`` declares it honestly.
    """

    async def _wrapped(bbox: Bbox, citta: str) -> tuple[list[Poi], OsmCut | None]:
        return await source(bbox, citta), None

    return _wrapped


async def _capture(
    config_path: Path,
    results_dir: Path,
    *,
    force: bool = False,
    poi_source: PoiSource | None = None,
) -> CaptureSummary:
    config = load_config(config_path)
    executor = get_executor()
    # Long retry policy by default (#232): the capture source
    # lives in ``snapshots`` next to ``capturing_source``, not here. The OSM cut
    # (#251) really only comes from the default offline source: an injected
    # ``poi_source`` from the tests does not know it, so it is adapted to
    # declare it absent instead of fabricating a fake one.
    inner: PoiSourceWithCut = (
        _without_cut(poi_source) if poi_source is not None else offline_fetch_pois
    )
    succeeded: list[CaptureCase] = []
    failed: list[CaptureCase] = []
    for case in config.cases:
        # Capture keyed by (citta, zona) (#110): the comparative arms
        # reuse the same fixture, without diverging Overpass queries per arm.
        key = make_snapshot_key(case.citta, case.zona)
        path = snapshot_path(results_dir, key)
        # Needed BEFORE the try to know, in case of failure, whether the snapshot
        # on disk was written by THIS attempt (to be cleaned up, #252) or
        # pre-existed (must not be touched).
        existed_before = path.exists()
        # Per-case isolation (#252): a failure on one case must not
        # swallow the following cases, as ``capture_roster`` already does --
        # otherwise, with OFFLINE_RETRY, a case that gives up after minutes of
        # backoff takes the remaining work with it. Deliberately ``Exception``
        # and not just ``(GeocodingError, OverpassError)``: a bug elsewhere in the
        # pipeline (e.g. a malformed POI) must not silently lose the
        # cases already captured nor skip the final summary -- ``Exception``
        # excludes ``KeyboardInterrupt``/``CancelledError`` anyway. The block
        # also wraps the skip-check: ``_snapshot_reusable`` deliberately does not
        # catch environmental errors (``OSError``/``PermissionError``, see
        # its docstring) and without this try/except a hiccup there would abort
        # the whole capture instead of isolating only this case.
        try:
            # Idempotence (skip-if-exists, #110 M2): do not re-capture the same
            # (citta, zona) for a second arm -- it would reintroduce the
            # confound. Skip ONLY if the snapshot is intact (#148): a
            # truncated/corrupt one must be re-captured, not silently replayed.
            # --force forces the re-capture.
            if not force and _snapshot_reusable(path):
                logger.info(
                    "snapshot (%s, %s) già presente, riuso: %s",
                    case.citta,
                    case.zona,
                    path,
                )
                # #267: reuse is the point where a changed selection policy
                # (e.g. the caps of #254) can stay invisible longest
                # -- an old file is never touched again until
                # someone launches ``eval run`` on the same (citta, zona) and
                # reads the logs. Warning here, not only at run time, anticipates the
                # signal to the moment when the capture itself already knows.
                mismatch = describe_config_mismatch(snapshot_provenance(path))
                if mismatch is not None:
                    logger.warning(
                        "riuso snapshot (%s, %s) con %s (#267)",
                        case.citta,
                        case.zona,
                        mismatch,
                    )
                succeeded.append(CaptureCase(case.citta, case.zona))
                continue
            if not force and existed_before:
                logger.warning(
                    "snapshot (%s, %s) presente ma vuoto/corrotto, ri-cattura: %s",
                    case.citta,
                    case.zona,
                    path,
                )
            source = capturing_source(path, inner=inner, zona=case.zona)
            # Path WITHOUT LLM whatever the config ``mode`` (#233): the
            # capture is input acquisition, not an experiment. The snapshot
            # is written by ``capturing_source`` when the Overpass fetch returns, and
            # the key is (citta, zona) (#110): the narrative that
            # ``run_analysis`` would generate here is discarded output at the cost of
            # real tokens -- on 26/07 a third of the daily Groq quota, with
            # the K=3 run blocked for an hour.
            await run_baseline(
                case.citta, case.zona, executor=executor, poi_source=source
            )
        except Exception as exc:
            # ``capturing_source`` writes the snapshot BEFORE an error
            # downstream (e.g. in grounding) makes the case fail: without this
            # cleanup, a failed case would still leave on disk a valid
            # file that the next run would treat as "already captured" -- a
            # silent false success. Removed ONLY if it did not pre-exist: a
            # pre-existing snapshot (intact or not) must not be touched here.
            if not existed_before and path.exists():
                path.unlink()
            logger.exception(
                "cattura fallita per (%s, %s): %s", case.citta, case.zona, exc
            )
            failed.append(
                CaptureCase(
                    case.citta,
                    case.zona,
                    error_type=type(exc).__name__,
                    error=str(exc) or None,
                )
            )
            continue
        succeeded.append(CaptureCase(case.citta, case.zona))

    report_line = (
        f"riepilogo cattura: {len(succeeded)}/{len(config.cases)} catturati "
        f"({', '.join(f'{c.citta}/{c.zona}' for c in succeeded) or 'nessuno'}); "
        f"falliti: {', '.join(f'{c.citta}/{c.zona}' for c in failed) or 'nessuno'}"
    )
    logger.info(report_line)
    # Besides the log: without an explicit ``logging`` configuration, the root
    # logger default is WARNING and this INFO would never reach the screen
    # for whoever launches the command from the command line -- the same pattern already
    # in use in ``i18n/extract.py`` for the final output of a CLI script.
    print(report_line)
    return CaptureSummary(succeeded=tuple(succeeded), failed=tuple(failed))


async def _run(
    config_path: Path,
    results_dir: Path,
    *,
    repeat: int = 1,
    clean_stale: bool = False,
    pause_seconds: float = 0.0,
) -> None:
    config = load_config(config_path)
    # Build the client only when mode requires it (fix T9), using config.model (fix I1).
    client = build_llm_eval_client(config) if uses_model(config) else None
    await run_experiment(
        config,
        executor=get_executor(),
        llm_client=client,
        results_dir=results_dir,
        code_commit=code_commit(),
        ontology_hash=ontology_hash(),
        repeat=repeat,
        clean_stale=clean_stale,
        pause_seconds=pause_seconds,
    )


def main() -> int:
    ns = build_parser().parse_args()
    results_dir = Path(ns.results)
    if ns.command == "capture":
        summary = asyncio.run(_capture(Path(ns.config), results_dir, force=ns.force))
        # #252: a partially failed capture is not a complete experiment --
        # a later run on missing snapshots would be crippled without knowing it.
        if summary.failed:
            return 1
    elif ns.command == "run":
        asyncio.run(
            _run(
                Path(ns.config),
                results_dir,
                repeat=ns.repeat,
                clean_stale=ns.clean_stale,
                pause_seconds=ns.pausa,
            )
        )
    elif ns.command == "aggregate":
        write_tables(results_dir, ns.experiment)
    elif ns.command == "compare":
        try:
            compare_experiments(
                results_dir,
                ns.experiment_a,
                ns.experiment_b,
                label_a=ns.label_a,
                label_b=ns.label_b,
                stem=ns.out,
                force=ns.force,
            )
        except NoUsableOutputError:
            # #239: no usable zone (all ERROR/FALLBACK). The report
            # explaining what failed is already on disk (written by
            # compare_experiments before re-raising): here only the exit code,
            # for whoever wants to intercept it from a script.
            return 1
    elif ns.command == "compare-repeated":
        try:
            build_repeated_report(
                results_dir,
                ns.experiment_a,
                ns.experiment_b,
                label_a=ns.label_a,
                label_b=ns.label_b,
                stem=ns.out,
                force=ns.force,
            )
        except NoUsableOutputError:
            return 1
    elif ns.command == "city-agnostic":
        if ns.phase == "capture":
            asyncio.run(capture_roster(ROSTER, results_dir))
        else:
            graph = load_ontology(get_settings().ontology_path)
            records_path, _, _ = build_report(results_dir, graph, ontology_hash())
            # The provenance warnings on screen (stderr), not only in the
            # gitignored files: without this an outcome without provenance or with
            # mixed configurations goes unnoticed (same reason as the
            # summary of ``_capture``, which does not rely on the log).
            summary = json.loads(records_path.read_text(encoding="utf-8"))["summary"]
            for warning in summary["avvisi"]:
                print(f"AVVISO: {warning}", file=sys.stderr)
    elif ns.command == "gold-sample":
        records = load_runs(results_dir, experiment=ns.experiment)
        records = [r for r in records if r.mode == ns.mode]
        path = write_gold_worksheet(results_dir, records, force=ns.force)
        # The count on screen (not only in the log, which by default is WARNING --
        # same reason as the summary of ``_capture``): a sheet with just the
        # header and exit code 0 is otherwise indistinguishable from a success
        # with data, until someone opens the file. ``collect_kept_risks`` is
        # pure and already run inside ``write_gold_worksheet``: recomputing it here
        # adds no I/O and keeps the function signature at a single value.
        n_rows = len(collect_kept_risks(records))
        print(f"foglio scritto: {path} (rischi da annotare: {n_rows})")
    elif ns.command == "gold-report":
        worksheet = (
            Path(ns.worksheet)
            if ns.worksheet
            else results_dir / "gold" / WORKSHEET_FILENAME
        )
        write_precision_report(results_dir, worksheet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
