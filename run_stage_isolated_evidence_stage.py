"""Run exactly one durable all-market evidence stage in a fresh interpreter.

Each invocation owns one operational evidence boundary and then exits, returning its Python
and provider working set to the operating system before the next stage starts. Successful
work is committed through the existing immutable snapshot/component stores before the stage
journal advances. The worker has no investment, specialist, sizing, construction,
execution, or real-money authority.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping, Sequence

from operations.stage_isolated_evidence_pipeline import (
    _STAGES,
    begin_evidence_stage,
    complete_evidence_stage,
    fail_evidence_stage,
    load_stage_isolated_evidence_state,
)


_PREPARING_ENV = "CAPITAL_INTELLIGENCE_EVIDENCE_PLANE_PREPARING"
_REFERENCE_MANIFEST_PATH_ENV = "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_PATH"
_REFERENCE_MANIFEST_ID_ENV = "CAPITAL_INTELLIGENCE_REFERENCE_MANIFEST_ID"
_DAG_WORKERS_ENV = "CAPITAL_INTELLIGENCE_CERTIFICATION_DAG_WORKERS"
_RENDER_DAG_WORKERS = "6"
_PAPER_HISTORY_DAYS = 365 * 10 + 20
_REDACTED = "[REDACTED]"
_SENSITIVE_ENV_MARKERS = (
    "API_KEY",
    "API_TOKEN",
    "ACCESS_TOKEN",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
    "PRIVATE_KEY",
)


def _credential_safe_detail(error: BaseException, values: Mapping[str, str]) -> str:
    text = str(error).strip() or type(error).__name__
    secrets = {
        str(secret).strip()
        for name, secret in values.items()
        if any(marker in str(name).upper() for marker in _SENSITIVE_ENV_MARKERS)
        and len(str(secret).strip()) >= 4
    }
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, _REDACTED)
    text = re.sub(
        r"(?i)([?&](?:api[_-]?key|apikey|api_token|access_token|token|secret|password)=)[^&\s]+",
        rf"\1{_REDACTED}",
        text,
    )
    text = re.sub(
        r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]{8,}",
        rf"\1{_REDACTED}",
        text,
    )
    return text[:1600]


def _state(values: Mapping[str, str], pipeline_id: str):
    state = load_stage_isolated_evidence_state(values)
    if state is None or state.pipeline_id != pipeline_id:
        raise RuntimeError("stage-isolated evidence pipeline identity is unavailable")
    return state


def _apply_reference_binding(values: dict[str, str], state) -> None:
    if state.reference_manifest_id:
        values[_REFERENCE_MANIFEST_ID_ENV] = state.reference_manifest_id
        os.environ[_REFERENCE_MANIFEST_ID_ENV] = state.reference_manifest_id
    if state.reference_manifest_path:
        values[_REFERENCE_MANIFEST_PATH_ENV] = state.reference_manifest_path
        os.environ[_REFERENCE_MANIFEST_PATH_ENV] = state.reference_manifest_path


def _configure_render_dag_workers(values: dict[str, str]) -> None:
    """Use bounded provider prewarm concurrency without parallelizing publication lanes."""

    if str(values.get("RENDER") or "").strip().lower() != "true":
        return
    values[_DAG_WORKERS_ENV] = _RENDER_DAG_WORKERS
    os.environ[_DAG_WORKERS_ENV] = _RENDER_DAG_WORKERS


def _base_universe_symbols() -> tuple[str, ...]:
    from operations.free_paper_pilot import (
        DEFAULT_UNIVERSE_PATH,
        load_free_paper_pilot_universe,
    )

    universe = load_free_paper_pilot_universe(DEFAULT_UNIVERSE_PATH)
    return tuple(sorted(universe.symbol_map))


def _post_public_live_cache_reclamation(
    values: Mapping[str, str],
) -> dict[str, object]:
    """Release bounded clean pages before the next U.S.-equity stage starts.

    This is operational-only and deliberately fail-soft. It runs after public-live has
    qualified but before that stage is durably completed, so the fresh U.S.-equity child
    does not inherit avoidable data-root page cache from public collection. It changes no
    memory threshold and cannot certify evidence.
    """

    try:
        from operations.pre_comprehensive_cache_reclamation import (
            release_pre_comprehensive_completed_stage_file_cache,
        )

        report = release_pre_comprehensive_completed_stage_file_cache(values)
    except (OSError, RuntimeError, TypeError, ValueError):
        return {
            "status": "unavailable",
            "advisory_only": True,
            "evidence_certified": False,
        }
    return {
        "status": str(report.get("status") or "completed"),
        "released_file_count": report.get("released_file_count"),
        "released_bytes": report.get("released_bytes"),
        "raw_current_reclaimed_kib": report.get("raw_current_reclaimed_kib"),
        "inactive_file_reclaimed_kib": report.get("inactive_file_reclaimed_kib"),
        "advisory_only": True,
        "evidence_certified": False,
    }


def _stage_reference(values: dict[str, str], state) -> dict[str, object]:
    from operations import component_qualified_evidence_maintenance as maintenance

    preparation_cutoff = maintenance._resumable_evidence_cutoff(
        values,
        requested=state.evidence_as_of,
    )
    if preparation_cutoff < state.evidence_as_of:
        attempts_dir = state.path.parent / "attempts"
        try:
            superseded_attempt = attempts_dir.is_dir() and any(
                path.is_file() and path.suffix == ".json"
                for path in attempts_dir.iterdir()
            )
        except OSError:
            superseded_attempt = True
        if superseded_attempt:
            preparation_cutoff = state.evidence_as_of

    manifest, effective_cutoff = maintenance._bound_or_prepare_reference_manifest(
        values,
        preparation_cutoff=preparation_cutoff,
    )
    manifest_id = str(getattr(manifest, "manifest_id", "")).strip()
    manifest_path = getattr(manifest, "path", None)
    if not manifest_id or manifest_path is None:
        raise RuntimeError("reference stage did not publish a durable manifest binding")
    return {
        "evidence_as_of": effective_cutoff,
        "reference_manifest_id": manifest_id,
        "reference_manifest_path": str(Path(manifest_path).expanduser()),
    }


def _stage_public_live(values: dict[str, str], state) -> dict[str, object]:
    from operations import component_qualified_evidence_maintenance as maintenance

    _apply_reference_binding(values, state)
    os.environ[_PREPARING_ENV] = "true"
    values[_PREPARING_ENV] = "true"
    collector = maintenance._component_public_collector(values)
    try:
        result = collector(state.evidence_as_of)
    except maintenance._plane.ContinuousEvidencePlaneError:
        result = collector(state.evidence_as_of)
    if getattr(result, "required_sources_ready", None) is not True:
        raise RuntimeError("required public-live evidence did not qualify")
    cache_reclamation = _post_public_live_cache_reclamation(values)
    return {
        "public_live_state": str(getattr(result, "state", "available")),
        "qualified_component_id": str(
            getattr(result, "qualified_component_id", "") or ""
        ),
        "post_public_live_cache_reclamation": cache_reclamation,
    }


def _stage_us_equity_discovery(values: dict[str, str], state) -> dict[str, object]:
    from operations.comprehensive_discovery_structural_prewarm import (
        start_render_structural_prewarm,
    )
    from operations.evidence_preparation_progress import (
        install_post_public_provider_progress,
    )
    from operations.evidence_state_scope import load_evidence_state_scope
    from operations.equity_discovery import discover_us_equities
    from operations.equity_discovery_snapshot import (
        EquityDiscoverySnapshotError,
        load_equity_discovery_snapshot,
        publish_equity_discovery_snapshot,
    )

    _apply_reference_binding(values, state)
    os.environ[_PREPARING_ENV] = "true"
    values[_PREPARING_ENV] = "true"
    install_post_public_provider_progress(values)
    prewarm = start_render_structural_prewarm(
        evidence_as_of=state.evidence_as_of,
        values=values,
    )
    try:
        scope = load_evidence_state_scope(as_of=state.evidence_as_of, values=values)
        base_symbols = _base_universe_symbols()
        try:
            snapshot = load_equity_discovery_snapshot(
                evidence_as_of=state.evidence_as_of,
                values=values,
            )
        except EquityDiscoverySnapshotError:
            snapshot = None
        if snapshot is not None and (
            snapshot.held_symbols == scope.held_symbols
            and snapshot.tracked_symbols == scope.tracked_symbols
            and snapshot.excluded_symbols == base_symbols
        ):
            return {"snapshot_id": snapshot.snapshot_id, "reused": True}

        result = discover_us_equities(
            as_of=state.evidence_as_of,
            held_symbols=scope.held_symbols,
            tracked_symbols=scope.tracked_symbols,
            excluded_symbols=base_symbols,
        )
        snapshot_id = publish_equity_discovery_snapshot(
            result,
            held_symbols=scope.held_symbols,
            tracked_symbols=scope.tracked_symbols,
            excluded_symbols=base_symbols,
            values=values,
        )
        return {"snapshot_id": snapshot_id, "reused": False}
    finally:
        prewarm.finish()


def _stage_comprehensive_discovery(values: dict[str, str], state) -> dict[str, object]:
    _configure_render_dag_workers(values)
    from run_dag_native_continuous_evidence_plane import (
        install_and_verify_dag_native_runtime,
    )

    install_and_verify_dag_native_runtime()

    from operations import component_qualified_evidence_maintenance as maintenance
    from operations.comprehensive_discovery_snapshot import (
        publish_comprehensive_discovery_snapshot,
    )
    from operations.evidence_state_scope import load_evidence_state_scope

    _apply_reference_binding(values, state)
    os.environ[_PREPARING_ENV] = "true"
    values[_PREPARING_ENV] = "true"
    scope = load_evidence_state_scope(as_of=state.evidence_as_of, values=values)

    def owned_global_discovery(as_of: datetime):
        from operations.comprehensive_market_discovery import discover_comprehensive_markets

        result = discover_comprehensive_markets(
            as_of=as_of,
            held_symbols=scope.held_symbols,
            tracked_symbols=scope.tracked_symbols,
        )
        publish_comprehensive_discovery_snapshot(
            result,
            held_symbols=scope.held_symbols,
            tracked_symbols=scope.tracked_symbols,
            values=values,
        )
        return result

    original = maintenance._plane._default_discovery
    maintenance._plane._default_discovery = owned_global_discovery
    try:
        result = maintenance._component_discovery_runner(values)(state.evidence_as_of)
    finally:
        maintenance._plane._default_discovery = original

    from operations.qualified_comprehensive_discovery_snapshot import (
        load_qualified_comprehensive_discovery_snapshot,
    )

    snapshot = load_qualified_comprehensive_discovery_snapshot(
        evidence_as_of=state.evidence_as_of,
        values=values,
    )
    return {
        "snapshot_id": snapshot.snapshot_id,
        "lane_count": len(result.lanes),
    }


def _paper_universe(values: dict[str, str], state):
    from operations.evidence_collection_universe import build_evidence_collection_universe
    from operations.evidence_state_scope import load_evidence_state_scope

    scope = load_evidence_state_scope(as_of=state.evidence_as_of, values=values)
    universe, holding_only = build_evidence_collection_universe(
        evidence_as_of=state.evidence_as_of,
        held_symbols=scope.held_symbols,
        tracked_symbols=scope.tracked_symbols,
        values=values,
    )
    return scope, universe, holding_only


def _stage_paper_evidence(values: dict[str, str], state) -> dict[str, object]:
    from operations.evidence_preparation_progress import (
        install_post_public_provider_progress,
    )
    from operations.owned_paper_evidence_collection import collect_owned_paper_evidence
    from operations.paper_evidence_snapshot import (
        PaperEvidenceSnapshotError,
        load_paper_evidence_snapshot,
        publish_paper_evidence_snapshot,
    )
    from operations.paper_evidence_spool_concurrent import close_spooled_paper_evidence

    _apply_reference_binding(values, state)
    os.environ[_PREPARING_ENV] = "true"
    values[_PREPARING_ENV] = "true"
    install_post_public_provider_progress(values)
    scope, universe, holding_only = _paper_universe(values, state)
    try:
        snapshot = load_paper_evidence_snapshot(
            evidence_as_of=state.evidence_as_of,
            universe=universe,
            values=values,
        )
    except PaperEvidenceSnapshotError:
        snapshot = None
    if snapshot is not None:
        return {
            "snapshot_id": snapshot.snapshot_id,
            "instrument_count": len(universe.instruments),
            "holding_only_count": len(holding_only),
            "reused": True,
        }

    payload = collect_owned_paper_evidence(
        universe,
        state.evidence_as_of,
        required_holding_symbols=scope.held_symbols,
        values=values,
    )
    try:
        snapshot = publish_paper_evidence_snapshot(
            payload,
            universe=universe,
            evidence_as_of=state.evidence_as_of,
            values=values,
            requested_history_days=_PAPER_HISTORY_DAYS,
        )
    finally:
        close_spooled_paper_evidence(payload)
    return {
        "snapshot_id": snapshot.snapshot_id,
        "instrument_count": len(universe.instruments),
        "holding_only_count": len(holding_only),
        "reused": False,
    }


def _stage_finalize(values: dict[str, str], state) -> dict[str, object]:
    """Publish the generation using only already-qualified durable stage outputs."""

    from operations import component_qualified_evidence_maintenance as maintenance
    from operations.equity_discovery_snapshot import load_equity_discovery_snapshot
    from operations.paper_evidence_snapshot import load_paper_evidence_snapshot
    from operations.qualified_comprehensive_discovery_snapshot import (
        load_qualified_comprehensive_discovery_snapshot,
    )

    _apply_reference_binding(values, state)
    if not state.reference_manifest_id or not state.reference_manifest_path:
        raise RuntimeError("finalization has no durable reference binding")

    public = maintenance._load_public_component(
        values,
        cutoff=datetime.now(timezone.utc),
    )
    if public is None or public.as_of != state.evidence_as_of:
        raise RuntimeError("finalization has no exact qualified public-live component")

    global_snapshot = load_qualified_comprehensive_discovery_snapshot(
        evidence_as_of=state.evidence_as_of,
        values=values,
    )
    equity_snapshot = load_equity_discovery_snapshot(
        evidence_as_of=state.evidence_as_of,
        values=values,
    )
    scope, universe, holding_only = _paper_universe(values, state)
    paper_snapshot = load_paper_evidence_snapshot(
        evidence_as_of=state.evidence_as_of,
        universe=universe,
        values=values,
    )
    base_symbols = _base_universe_symbols()
    if (
        global_snapshot.held_symbols != scope.held_symbols
        or global_snapshot.tracked_symbols != scope.tracked_symbols
    ):
        raise RuntimeError("global discovery snapshot state scope changed before finalization")
    if (
        equity_snapshot.held_symbols != scope.held_symbols
        or equity_snapshot.tracked_symbols != scope.tracked_symbols
        or equity_snapshot.excluded_symbols != base_symbols
    ):
        raise RuntimeError("U.S.-equity snapshot state scope changed before finalization")
    if paper_snapshot.evidence_as_of != state.evidence_as_of:
        raise RuntimeError("paper evidence snapshot changed its evidence epoch")

    generation = maintenance._plane.refresh_continuous_evidence_plane(
        as_of=state.evidence_as_of,
        values=values,
        reference_preparer=lambda _values: SimpleNamespace(
            manifest_id=state.reference_manifest_id
        ),
        public_collector=lambda _timestamp: SimpleNamespace(
            state=str(public.payload.get("state") or "available"),
            required_sources_ready=True,
        ),
        discovery=lambda _timestamp: global_snapshot.result,
    )
    if generation.as_of != state.evidence_as_of:
        raise RuntimeError("final evidence generation changed the stage-isolated evidence epoch")
    archive = maintenance._legacy_maintenance._archive_generation(values, generation)
    return {
        "generation_id": generation.generation_id,
        "global_snapshot_id": global_snapshot.snapshot_id,
        "us_equity_snapshot_id": equity_snapshot.snapshot_id,
        "paper_snapshot_id": paper_snapshot.snapshot_id,
        "instrument_count": len(universe.instruments),
        "holding_only_count": len(holding_only),
        "archive": str(archive),
    }


_STAGE_RUNNERS = {
    "reference": _stage_reference,
    "public_live": _stage_public_live,
    "us_equity_discovery": _stage_us_equity_discovery,
    "comprehensive_discovery": _stage_comprehensive_discovery,
    "paper_evidence": _stage_paper_evidence,
    "finalize": _stage_finalize,
}


def run_stage(
    stage: str,
    *,
    pipeline_id: str,
    values: Mapping[str, str] | None = None,
) -> int:
    resolved = dict(os.environ if values is None else values)
    normalized = str(stage).strip()
    if normalized not in _STAGE_RUNNERS:
        raise ValueError("unsupported stage-isolated evidence stage")
    state = begin_evidence_stage(
        resolved,
        pipeline_id=pipeline_id,
        stage=normalized,
    )
    if normalized in state.completed_stages:
        return 0
    try:
        result = _STAGE_RUNNERS[normalized](resolved, state)
        completed = complete_evidence_stage(
            resolved,
            pipeline_id=pipeline_id,
            stage=normalized,
            evidence_as_of=(
                result.get("evidence_as_of")
                if isinstance(result.get("evidence_as_of"), datetime)
                else None
            ),
            reference_manifest_id=(
                str(result.get("reference_manifest_id") or "").strip() or None
            ),
            reference_manifest_path=(
                str(result.get("reference_manifest_path") or "").strip() or None
            ),
            generation_id=(
                str(result.get("generation_id") or "").strip() or None
            ),
        )
    except Exception as error:
        detail = _credential_safe_detail(error, resolved)
        try:
            fail_evidence_stage(
                resolved,
                pipeline_id=pipeline_id,
                stage=normalized,
                error_type=type(error).__name__,
                error_detail=detail,
            )
        except Exception:
            pass
        print(
            json.dumps(
                {
                    "event": "stage_isolated_evidence_stage_failed",
                    "pipeline_id": pipeline_id,
                    "stage": normalized,
                    "error_type": type(error).__name__,
                    "error_detail": detail,
                    "credential_safe": True,
                    "decision_authority": False,
                    "execution_authority": False,
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 2

    try:
        print(
            json.dumps(
                {
                    "event": "stage_isolated_evidence_stage_completed",
                    "pipeline_id": pipeline_id,
                    "stage": normalized,
                    "evidence_as_of": completed.evidence_as_of.isoformat(),
                    "generation_id": completed.generation_id,
                    "result": {
                        key: value
                        for key, value in result.items()
                        if key not in {"evidence_as_of"}
                    },
                    "credential_safe": True,
                    "decision_authority": False,
                    "execution_authority": False,
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
                default=str,
            ),
            flush=True,
        )
    except Exception:
        pass
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=_STAGES)
    parser.add_argument("--pipeline-id", required=True)
    args = parser.parse_args(argv)
    try:
        return run_stage(args.stage, pipeline_id=args.pipeline_id)
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "event": "stage_isolated_evidence_stage_start_failed",
                    "stage": args.stage,
                    "error_type": type(error).__name__,
                    "credential_safe": True,
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
