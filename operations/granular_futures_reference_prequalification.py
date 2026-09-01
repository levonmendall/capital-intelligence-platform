"""Granular, resumable supervision for production futures reference qualification.

The reference manifest remains strict: all configured futures roots must be current and
complete before ``reference-futures-contracts`` can be published.  This module changes
only the execution boundary.  CME venue work and Massive fallback work are supervised as
small killable units, while the coordinator itself is not wrapped in an aggregate timeout.

Successful root results are persisted immediately through the existing CME venue cache.
A later timeout therefore leaves qualified work reusable on the next attempt.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from operations.supervised_component_execution import (
    SupervisedComponentExecutionError,
    SupervisedComponentTimeout,
    run_supervised_component,
    run_supervised_components,
)
from providers.cme_futures_reference_executable import (
    CmeExecutableFuturesReferenceProvider,
    _ROOT_VENUES,
    _canonical_exchange,
)
from providers.massive_futures_reference_rate_resilient import (
    MassiveFuturesReferenceProvider,
)
from providers.massive_multi_asset import MassiveFuturesContract, MassiveMultiAssetError


_PROGRESS_SCHEMA = "futures-reference-prequalification-progress.v1"
_UNIT_TIMEOUT_ENV = "CAPITAL_INTELLIGENCE_FUTURES_REFERENCE_UNIT_TIMEOUT_SECONDS"
_DEFAULT_UNIT_TIMEOUT_SECONDS = 45.0
_FALLBACK_MAX_WORKERS_ENV = (
    "CAPITAL_INTELLIGENCE_FUTURES_REFERENCE_FALLBACK_MAX_WORKERS"
)
_DEFAULT_FALLBACK_MAX_WORKERS = 3
_MAX_FALLBACK_MAX_WORKERS = 4


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def futures_reference_progress_path(values: Mapping[str, str]) -> Path:
    data_root = Path(
        str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "database")
    ).expanduser()
    return data_root / "reference_readiness" / "futures-prequalification-latest.json"


def load_futures_reference_progress(
    values: Mapping[str, str] | None = None,
) -> Mapping[str, object] | None:
    resolved = os.environ if values is None else values
    path = futures_reference_progress_path(resolved)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    if payload.get("schema_version") != _PROGRESS_SCHEMA:
        return None
    if str(payload.get("release") or "") != _release(resolved):
        return None
    if payload.get("credential_safe") is not True:
        return None
    if payload.get("paper_only") is not True:
        return None
    if payload.get("real_money_authorized") is not False:
        return None
    return dict(payload)


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(dict(payload), sort_keys=True, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _unit_timeout_seconds(values: Mapping[str, str]) -> float:
    raw = str(
        values.get(_UNIT_TIMEOUT_ENV)
        or os.getenv(_UNIT_TIMEOUT_ENV, "")
        or ""
    ).strip()
    if not raw:
        return _DEFAULT_UNIT_TIMEOUT_SECONDS
    try:
        timeout = float(raw)
    except ValueError as error:
        raise ValueError(f"{_UNIT_TIMEOUT_ENV} must be numeric") from error
    if not math.isfinite(timeout) or timeout <= 0.0:
        raise ValueError(f"{_UNIT_TIMEOUT_ENV} must be positive")
    return timeout


def _fallback_max_workers(values: Mapping[str, str]) -> int:
    raw = str(
        values.get(_FALLBACK_MAX_WORKERS_ENV)
        or os.getenv(_FALLBACK_MAX_WORKERS_ENV, "")
        or ""
    ).strip()
    if not raw:
        return _DEFAULT_FALLBACK_MAX_WORKERS
    try:
        workers = int(raw)
    except ValueError as error:
        raise ValueError(f"{_FALLBACK_MAX_WORKERS_ENV} must be an integer") from error
    if workers < 1 or workers > _MAX_FALLBACK_MAX_WORKERS:
        raise ValueError(
            f"{_FALLBACK_MAX_WORKERS_ENV} must be between 1 and "
            f"{_MAX_FALLBACK_MAX_WORKERS}"
        )
    return workers


def _root_set(
    rows: Sequence[MassiveFuturesContract],
    *,
    allowed: Sequence[str],
) -> set[str]:
    valid = set(allowed)
    return {
        row.product_code.strip().upper()
        for row in rows
        if row.active and row.product_code.strip().upper() in valid
    }


def _failure_kind(error: BaseException) -> str:
    if isinstance(error, SupervisedComponentTimeout):
        return "timeout"
    if isinstance(error, SupervisedComponentExecutionError):
        return "provider_failure"
    return type(error).__name__


class GranularFuturesReferenceProvider:
    """Coordinate root-qualified futures reference work without an aggregate timeout."""

    def __init__(
        self,
        *,
        values: MutableMapping[str, str] | Mapping[str, str] | None = None,
        cme_provider: CmeExecutableFuturesReferenceProvider | None = None,
        massive_provider_factory: Callable[[], MassiveFuturesReferenceProvider] | None = None,
        component_runner: Callable[..., Any] = run_supervised_component,
        batch_component_runner: Callable[..., Mapping[str, Any | BaseException]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.values = os.environ if values is None else values
        self.cme = cme_provider or CmeExecutableFuturesReferenceProvider(
            fallback_provider=None,
            values=self.values,
        )
        self._massive_provider_factory = (
            massive_provider_factory or MassiveFuturesReferenceProvider
        )
        self._component_runner = component_runner
        self._batch_component_runner = (
            run_supervised_components
            if batch_component_runner is None and component_runner is run_supervised_component
            else batch_component_runner
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._reference_telemetry: list[dict[str, object]] = []
        self._reference_metadata: dict[str, object] = {}
        self._units: list[dict[str, object]] = []
        self._cutoff: datetime | None = None
        self._required_roots: tuple[str, ...] = ()
        self._qualified_roots: set[str] = set()
        self._active_unit: str | None = None
        self._active_units: tuple[str, ...] = ()
        self._deferred_fallbacks: list[tuple[str, str]] = []

    @property
    def configured(self) -> bool:
        return True

    @property
    def reference_telemetry(self) -> tuple[Mapping[str, object], ...]:
        return tuple(dict(item) for item in self._reference_telemetry)

    @property
    def reference_metadata(self) -> Mapping[str, object]:
        return dict(self._reference_metadata)

    def _write_progress(self, *, state: str) -> None:
        cutoff = self._cutoff
        if cutoff is None:
            return
        unresolved = sorted(set(self._required_roots) - self._qualified_roots)
        _atomic_json(
            futures_reference_progress_path(self.values),
            {
                "schema_version": _PROGRESS_SCHEMA,
                "release": _release(self.values),
                "cutoff": cutoff.isoformat(),
                "updated_at": self._clock().astimezone(timezone.utc).isoformat(),
                "state": state,
                "required_root_count": len(self._required_roots),
                "qualified_root_count": len(self._qualified_roots),
                "unresolved_root_count": len(unresolved),
                "required_roots": list(self._required_roots),
                "qualified_roots": sorted(self._qualified_roots),
                "unresolved_roots": unresolved,
                "active_unit": self._active_unit,
                "active_units": list(self._active_units),
                "fallback_max_workers": _fallback_max_workers(self.values),
                "units": [dict(item) for item in self._units],
                "credential_safe": True,
                "decision_evidence_authority": False,
                "paper_only": True,
                "real_money_authorized": False,
            },
        )

    def _record_unit(
        self,
        *,
        unit: str,
        provider: str,
        state: str,
        roots: Sequence[str],
        venue: str | None = None,
        root: str | None = None,
        duration_ms: int = 0,
        failure_type: str | None = None,
        fallback: bool = False,
        detail: str | None = None,
        provider_error_type: str | None = None,
        http_status: int | None = None,
        retryable: bool | None = None,
    ) -> None:
        self._units.append(
            {
                "unit": unit,
                "provider": provider,
                "state": state,
                "venue": venue,
                "root": root,
                "roots": list(roots),
                "duration_ms": int(max(0, duration_ms)),
                "failure_type": failure_type,
                "fallback": bool(fallback),
                "detail": detail,
                "provider_error_type": provider_error_type,
                "http_status": http_status,
                "retryable": retryable,
            }
        )

    def _run_unit(
        self,
        *,
        unit: str,
        provider: str,
        roots: Sequence[str],
        operation: Callable[[], Any],
        venue: str | None = None,
        root: str | None = None,
        fallback: bool = False,
    ) -> Any | None:
        self._active_unit = unit
        self._write_progress(state="qualifying")
        started = time.monotonic()
        try:
            result = self._component_runner(
                component=unit,
                operation=operation,
                timeout_seconds=_unit_timeout_seconds(self.values),
                return_value=True,
            )
        except (SupervisedComponentTimeout, SupervisedComponentExecutionError) as error:
            elapsed = int((time.monotonic() - started) * 1000)
            failure_type = _failure_kind(error)
            self._record_unit(
                unit=unit,
                provider=provider,
                state="timed-out" if failure_type == "timeout" else "failed",
                roots=roots,
                venue=venue,
                root=root,
                duration_ms=elapsed,
                failure_type=failure_type,
                fallback=fallback,
                detail=str(error),
                provider_error_type=(
                    getattr(error, "remote_error_type", None) or type(error).__name__
                ),
                http_status=getattr(error, "status_code", None),
                retryable=getattr(error, "retryable", None),
            )
            return None
        finally:
            self._active_unit = None
        elapsed = int((time.monotonic() - started) * 1000)
        self._record_unit(
            unit=unit,
            provider=provider,
            state="qualified",
            roots=roots,
            venue=venue,
            root=root,
            duration_ms=elapsed,
            fallback=fallback,
        )
        return result

    def _massive_cached(
        self,
        *,
        root: str,
        as_of: datetime,
        provider: MassiveFuturesReferenceProvider,
    ) -> tuple[MassiveFuturesContract, ...] | None:
        try:
            return provider._load_root_cache(root=root, as_of=as_of)
        except (OSError, TypeError, ValueError):
            return None

    def _persist_root_checkpoint(
        self,
        *,
        venue: str,
        root: str,
        as_of: datetime,
        contracts: Sequence[MassiveFuturesContract],
        business_dates: Sequence[date],
    ) -> None:
        rows = tuple(
            row
            for row in contracts
            if row.active and row.product_code.strip().upper() == root
        )
        if not rows or not self.cme._complete(rows, (root,)):
            return
        self.cme._write_venue_cache(
            venue=venue,
            roots=(root,),
            captured_at=self._clock().astimezone(timezone.utc),
            business_dates=business_dates or (as_of.date(),),
            contracts=rows,
        )

    def _reuse_root_checkpoint(
        self,
        *,
        venue: str,
        root: str,
        as_of: datetime,
    ) -> tuple[MassiveFuturesContract, ...] | None:
        cached = self.cme._records_from_venue_cache(
            venue=venue,
            roots=(root,),
            as_of=as_of,
        )
        if cached is None:
            return None
        rows, _dates = cached
        self._qualified_roots.add(root)
        source = (
            "cme_fprf"
            if all(row.source_identifier.startswith("cme-fprf:") for row in rows)
            else "cme-massive"
        )
        self._record_unit(
            unit=f"futures-root-{root}",
            provider=source,
            state="reused",
            roots=(root,),
            venue=venue,
            root=root,
            fallback=source != "cme_fprf",
        )
        return rows

    def _collect_massive_root(
        self,
        *,
        venue: str,
        root: str,
        as_of: datetime,
        maximum_pages: int,
    ) -> tuple[MassiveFuturesContract, ...]:
        provider = self._massive_provider_factory()
        cached = self._massive_cached(root=root, as_of=as_of, provider=provider)
        if cached is not None and self.cme._complete(cached, (root,)):
            rows = tuple(cached)
            self._record_unit(
                unit=f"massive-root-{root}",
                provider="massive",
                state="reused",
                roots=(root,),
                venue=venue,
                root=root,
                fallback=True,
            )
        else:
            result = self._run_unit(
                unit=f"massive-root-{root}",
                provider="massive",
                roots=(root,),
                venue=venue,
                root=root,
                fallback=True,
                operation=lambda: provider.futures_contracts(
                    as_of=as_of,
                    product_codes=(root,),
                    maximum_pages=maximum_pages,
                ),
            )
            rows = () if result is None else tuple(result)
        if not rows or not self.cme._complete(rows, (root,)):
            return ()
        self._persist_root_checkpoint(
            venue=venue,
            root=root,
            as_of=as_of,
            contracts=rows,
            business_dates=(as_of.date(),),
        )
        self._qualified_roots.add(root)
        return rows

    def _collect_massive_roots(
        self,
        *,
        units: Sequence[tuple[str, str]],
        as_of: datetime,
        maximum_pages: int,
    ) -> tuple[MassiveFuturesContract, ...]:
        """Collect independent fallback roots in a bounded concurrent process batch."""

        ordered = tuple(dict.fromkeys((str(venue), str(root)) for venue, root in units))
        if not ordered:
            return ()
        if self._batch_component_runner is None or len(ordered) == 1:
            sequential: list[MassiveFuturesContract] = []
            for venue, root in ordered:
                sequential.extend(
                    self._collect_massive_root(
                        venue=venue,
                        root=root,
                        as_of=as_of,
                        maximum_pages=maximum_pages,
                    )
                )
            return tuple(sequential)

        collected: list[MassiveFuturesContract] = []
        pending: list[tuple[str, str, MassiveFuturesReferenceProvider]] = []
        for venue, root in ordered:
            provider = self._massive_provider_factory()
            cached = self._massive_cached(root=root, as_of=as_of, provider=provider)
            if cached is not None and self.cme._complete(cached, (root,)):
                rows = tuple(cached)
                self._record_unit(
                    unit=f"massive-root-{root}",
                    provider="massive",
                    state="reused",
                    roots=(root,),
                    venue=venue,
                    root=root,
                    fallback=True,
                )
                self._persist_root_checkpoint(
                    venue=venue,
                    root=root,
                    as_of=as_of,
                    contracts=rows,
                    business_dates=(as_of.date(),),
                )
                self._qualified_roots.add(root)
                collected.extend(rows)
                continue
            pending.append((venue, root, provider))

        if not pending:
            return tuple(collected)

        tasks = {
            f"massive-root-{root}": (
                lambda provider=provider, root=root: provider.futures_contracts(
                    as_of=as_of,
                    product_codes=(root,),
                    maximum_pages=maximum_pages,
                )
            )
            for _venue, root, provider in pending
        }
        self._active_unit = "massive-fallback-batch"
        self._active_units = tuple(tasks)
        self._write_progress(state="qualifying")
        started = time.monotonic()
        try:
            outcomes = self._batch_component_runner(
                components=tasks,
                timeout_seconds=_unit_timeout_seconds(self.values),
                maximum_parallel=_fallback_max_workers(self.values),
            )
        finally:
            self._active_unit = None
            self._active_units = ()
        elapsed = int((time.monotonic() - started) * 1000)

        for venue, root, _provider in pending:
            unit = f"massive-root-{root}"
            outcome = outcomes.get(unit)
            if isinstance(outcome, BaseException):
                failure_type = _failure_kind(outcome)
                unit_elapsed = int(
                    getattr(outcome, "supervised_duration_ms", elapsed)
                )
                self._record_unit(
                    unit=unit,
                    provider="massive",
                    state="timed-out" if failure_type == "timeout" else "failed",
                    roots=(root,),
                    venue=venue,
                    root=root,
                    duration_ms=unit_elapsed,
                    failure_type=failure_type,
                    fallback=True,
                    detail=str(outcome),
                    provider_error_type=(
                        getattr(outcome, "remote_error_type", None)
                        or type(outcome).__name__
                    ),
                    http_status=getattr(outcome, "status_code", None),
                    retryable=getattr(outcome, "retryable", None),
                )
                continue
            rows = () if outcome is None else tuple(outcome)
            if not rows or not self.cme._complete(rows, (root,)):
                self._record_unit(
                    unit=unit,
                    provider="massive",
                    state="failed",
                    roots=(root,),
                    venue=venue,
                    root=root,
                    duration_ms=elapsed,
                    failure_type="incomplete_root_coverage",
                    fallback=True,
                    detail="Massive fallback returned no complete active root coverage",
                )
                continue
            self._record_unit(
                unit=unit,
                provider="massive",
                state="qualified",
                roots=(root,),
                venue=venue,
                root=root,
                duration_ms=elapsed,
                fallback=True,
            )
            self._persist_root_checkpoint(
                venue=venue,
                root=root,
                as_of=as_of,
                contracts=rows,
                business_dates=(as_of.date(),),
            )
            self._qualified_roots.add(root)
            collected.extend(rows)

        self._write_progress(state="qualifying")
        return tuple(collected)

    def _collect_venue(
        self,
        *,
        venue: str,
        url: str,
        roots: Sequence[str],
        as_of: datetime,
        maximum_pages: int,
    ) -> tuple[MassiveFuturesContract, ...]:
        result: dict[tuple[str, str], MassiveFuturesContract] = {}
        unresolved: list[str] = []
        for root in roots:
            cached = self._reuse_root_checkpoint(
                venue=venue,
                root=root,
                as_of=as_of,
            )
            if cached is None:
                unresolved.append(root)
            else:
                for row in cached:
                    result[(root, row.ticker)] = row

        business_dates: tuple[date, ...] = ()
        if unresolved:
            operation_result = self._run_unit(
                unit=f"cme-venue-{venue.lower()}",
                provider="cme_fprf",
                roots=tuple(unresolved),
                venue=venue,
                operation=lambda: self.cme._collect_file(
                    exchange_name=venue,
                    url=url,
                    roots=set(unresolved),
                    reference_date=as_of.date(),
                ),
            )
            if operation_result is None:
                cme_rows: tuple[MassiveFuturesContract, ...] = ()
            else:
                raw_rows, raw_dates, _telemetry = operation_result
                cme_rows = tuple(raw_rows)
                business_dates = tuple(sorted(raw_dates))
                if cme_rows and (
                    not business_dates
                    or not self.cme._source_dates_current(business_dates, as_of.date())
                ):
                    cme_rows = ()
                    self._record_unit(
                        unit=f"cme-venue-{venue.lower()}-business-date",
                        provider="cme_fprf",
                        state="failed",
                        roots=tuple(unresolved),
                        venue=venue,
                        failure_type="stale_source_date",
                        detail="CME source business date outside governed current window",
                    )

            cme_covered = _root_set(cme_rows, allowed=unresolved)
            for root in sorted(cme_covered):
                root_rows = tuple(
                    row
                    for row in cme_rows
                    if row.product_code.strip().upper() == root
                )
                self._persist_root_checkpoint(
                    venue=venue,
                    root=root,
                    as_of=as_of,
                    contracts=root_rows,
                    business_dates=business_dates or (as_of.date(),),
                )
                self._qualified_roots.add(root)
                for row in root_rows:
                    result[(root, row.ticker)] = row

            unresolved = [root for root in unresolved if root not in cme_covered]

        self._deferred_fallbacks.extend((venue, root) for root in unresolved)

        return tuple(
            sorted(result.values(), key=lambda row: (row.product_code, row.ticker))
        )

    def futures_contracts(
        self,
        *,
        as_of: datetime,
        product_codes: Sequence[str] = (),
        maximum_pages: int = 20,
    ) -> tuple[MassiveFuturesContract, ...]:
        timestamp = as_of.astimezone(timezone.utc)
        roots = tuple(
            sorted(
                {
                    str(item).strip().upper()
                    for item in product_codes
                    if str(item).strip()
                }
            )
        )
        if not roots:
            raise MassiveMultiAssetError(
                "granular futures reference requires configured product roots"
            )

        self._cutoff = timestamp
        self._required_roots = roots
        self._qualified_roots = set()
        self._units = []
        self._active_unit = None
        self._active_units = ()
        self._deferred_fallbacks = []
        self._write_progress(state="qualifying")

        complete_cache = self.cme._records_from_cache(roots=roots, as_of=timestamp)
        if complete_cache is not None:
            self._qualified_roots.update(roots)
            self._record_unit(
                unit="futures-complete-cache",
                provider="cme-massive",
                state="reused",
                roots=roots,
            )
            self._reference_telemetry = [dict(item) for item in self._units]
            self._reference_metadata = {
                "provider": "cme-massive-granular",
                "configured_roots": len(roots),
                "covered_roots": len(roots),
                "reused_complete_cache": True,
                "unit_timeout_seconds": _unit_timeout_seconds(self.values),
            }
            self._write_progress(state="qualified")
            return tuple(complete_cache)

        contracts: dict[tuple[str, str], MassiveFuturesContract] = {}
        visited_venues: set[str] = set()
        for raw_venue, url in self.cme.file_urls:
            venue = _canonical_exchange(raw_venue)
            if venue in visited_venues:
                continue
            visited_venues.add(venue)
            venue_roots = tuple(root for root in roots if _ROOT_VENUES.get(root) == venue)
            if not venue_roots:
                continue
            for row in self._collect_venue(
                venue=venue,
                url=url,
                roots=venue_roots,
                as_of=timestamp,
                maximum_pages=maximum_pages,
            ):
                contracts[(row.product_code.strip().upper(), row.ticker)] = row
            self._write_progress(state="qualifying")

        unmapped = tuple(root for root in roots if _ROOT_VENUES.get(root) is None)
        self._deferred_fallbacks.extend(("UNMAPPED", root) for root in unmapped)
        for row in self._collect_massive_roots(
            units=self._deferred_fallbacks,
            as_of=timestamp,
            maximum_pages=maximum_pages,
        ):
            contracts[(row.product_code.strip().upper(), row.ticker)] = row
        self._write_progress(state="qualifying")

        result = tuple(
            sorted(contracts.values(), key=lambda row: (row.product_code, row.ticker))
        )
        covered = _root_set(result, allowed=roots)
        self._qualified_roots.update(covered)
        unresolved = tuple(root for root in roots if root not in covered)

        self._reference_telemetry = [dict(item) for item in self._units]
        self._reference_metadata = {
            "provider": "cme-massive-granular",
            "configured_roots": len(roots),
            "covered_roots": len(covered),
            "unresolved_roots": list(unresolved),
            "unit_timeout_seconds": _unit_timeout_seconds(self.values),
            "fallback_max_workers": _fallback_max_workers(self.values),
            "unit_count": len(self._units),
        }

        if unresolved:
            timeout_seen = any(
                item.get("failure_type") == "timeout" for item in self._units
            )
            self._write_progress(state="incomplete")
            first_failure = next(
                (
                    item
                    for item in self._units
                    if item.get("state") in {"failed", "timed-out"}
                ),
                None,
            )
            context = ""
            if first_failure is not None:
                context = (
                    f"; futures_unit={first_failure.get('unit')}"
                    f"; venue={first_failure.get('venue') or 'unknown'}"
                    f"; root={first_failure.get('root') or 'multiple'}"
                    f"; provider={first_failure.get('provider') or 'unknown'}"
                )
            raise MassiveMultiAssetError(
                "granular futures reference remains incomplete"
                f"; failure_type={'timeout' if timeout_seen else 'provider_failure'}"
                f"{context}; unresolved_roots={','.join(unresolved)}"
            )

        captured_at = self._clock().astimezone(timezone.utc)
        source_dates: set[date] = set()
        for row in result:
            identifier = str(row.source_identifier)
            if identifier.startswith("cme-fprf:"):
                raw = identifier.rsplit(":", 1)[-1]
                try:
                    source_dates.add(date.fromisoformat(raw))
                except ValueError:
                    pass
        if not source_dates:
            source_dates.add(timestamp.date())
        self.cme._write_cache(
            roots=roots,
            captured_at=captured_at,
            business_dates=tuple(sorted(source_dates)),
            contracts=result,
        )
        self._write_progress(state="qualified")
        return result


__all__ = [
    "GranularFuturesReferenceProvider",
    "futures_reference_progress_path",
    "load_futures_reference_progress",
]
