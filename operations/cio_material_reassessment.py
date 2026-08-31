"""Live materiality scanner that may request a canonical CIO reassessment."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from operations.direct_global_markets import DirectGlobalMarketClient
from operations.free_paper_pilot import (
    DEFAULT_UNIVERSE_PATH,
    active_paper_universe_path,
    default_alpaca_client,
)


_OPPORTUNITY_TRIGGER_HISTORY_LIMIT = 1024


def aware_utc(value: datetime, name: str = "time") -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def parse_clock(value: str) -> clock_time:
    try:
        hour, minute = (int(part) for part in value.strip().split(":"))
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("clock times must use HH:MM") from error
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("clock time is invalid")
    return clock_time(hour, minute)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def save_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def field(source: object | None, name: str, default=None):
    return (
        source.get(name, default)
        if isinstance(source, Mapping)
        else getattr(source, name, default)
    )


def snapshot_price(snapshot: Mapping[str, Any]) -> float | None:
    for key, price_key in (
        ("latestTrade", "p"),
        ("minuteBar", "c"),
        ("dailyBar", "c"),
    ):
        item = snapshot.get(key)
        if not isinstance(item, Mapping):
            continue
        try:
            value = float(item.get(price_key))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def previous_close(snapshot: Mapping[str, Any]) -> float | None:
    item = snapshot.get("prevDailyBar")
    if not isinstance(item, Mapping):
        return None
    try:
        value = float(item.get("c"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _direction(value: float) -> str:
    return "up" if value >= 0.0 else "down"


@dataclass(frozen=True, slots=True)
class ReassessmentResult:
    state: str
    evaluated_at: datetime
    triggered: bool = False
    trigger_key: str | None = None
    reasons: tuple[str, ...] = ()
    symbol_count: int = 0
    detail: str = ""
    paper_only: bool = True
    real_money_authorized: bool = False

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["evaluated_at"] = self.evaluated_at.isoformat()
        payload["reasons"] = list(self.reasons)
        return payload


class MaterialCIOReassessmentEngine:
    """Request a full CIO review only when live evidence changes materially.

    The scanner has no candidate, action, sizing, construction, execution, or
    real-money authority. Distinct opportunity conditions are independently
    idempotent: one recent event can never suppress another opportunity merely
    because both occurred inside the same wall-clock cooldown window.
    """

    def __init__(
        self,
        *,
        state_path: str | Path,
        timezone_name: str,
        schedule_times: Sequence[str],
        scan_interval: timedelta = timedelta(minutes=5),
        event_cooldown: timedelta = timedelta(minutes=30),
        benchmark_move_threshold: float = 0.01,
        instrument_move_threshold: float = 0.03,
        company_move_threshold: float = 0.05,
        scheduled_guard: timedelta = timedelta(minutes=10),
        client_factory: Callable[[], object] = default_alpaca_client,
        direct_client_factory: Callable[[], object] = DirectGlobalMarketClient,
        active_universe_path: str | Path | None = None,
        fallback_universe_path: str | Path = DEFAULT_UNIVERSE_PATH,
    ) -> None:
        if scan_interval < timedelta(minutes=1):
            raise ValueError("scan interval must be at least one minute")
        if event_cooldown < timedelta(minutes=1):
            raise ValueError("opportunity deduplication lifetime must be at least one minute")
        if scheduled_guard < timedelta(0):
            raise ValueError("scheduled guard cannot be negative")
        thresholds = (
            benchmark_move_threshold,
            instrument_move_threshold,
            company_move_threshold,
        )
        if any(not 0 < float(value) <= 1 for value in thresholds):
            raise ValueError("move thresholds must be between zero and one")
        self.state_path = Path(state_path).expanduser()
        self.timezone = ZoneInfo(timezone_name)
        self.schedule_times = tuple(parse_clock(item) for item in schedule_times)
        self.scan_interval = scan_interval
        # Kept under the existing configuration name for compatibility. It now
        # scopes only repetition of the same opportunity key; it is not a global
        # event-review cooldown.
        self.event_cooldown = event_cooldown
        self.benchmark_move_threshold = float(benchmark_move_threshold)
        self.instrument_move_threshold = float(instrument_move_threshold)
        self.company_move_threshold = float(company_move_threshold)
        self.scheduled_guard = scheduled_guard
        self.client_factory = client_factory
        self.direct_client_factory = direct_client_factory
        self.active_universe_path = Path(
            active_universe_path or active_paper_universe_path()
        ).expanduser()
        # Retained for call-site compatibility only. A stale static universe must not
        # replace the exact active capability publication.
        self.fallback_universe_path = Path(fallback_universe_path).expanduser()

    def _guarded(self, now: datetime) -> bool:
        if self.scheduled_guard <= timedelta(0):
            return False
        local = now.astimezone(self.timezone)
        return any(
            abs(
                (
                    local
                    - local.replace(
                        hour=item.hour,
                        minute=item.minute,
                        second=0,
                        microsecond=0,
                    )
                ).total_seconds()
            )
            <= self.scheduled_guard.total_seconds()
            for item in self.schedule_times
        )

    def _recent_opportunity_claims(
        self,
        state: Mapping[str, Any],
        *,
        now: datetime,
    ) -> dict[str, datetime]:
        raw = state.get("recent_opportunity_claims")
        if not isinstance(raw, Mapping):
            return {}
        recent: dict[str, datetime] = {}
        for raw_key, raw_time in raw.items():
            key = str(raw_key).strip()
            claimed_at = parse_datetime(raw_time)
            if not key or claimed_at is None:
                continue
            elapsed = now - claimed_at
            if elapsed < timedelta(0) or elapsed < self.event_cooldown:
                recent[key] = claimed_at
        return recent

    def _record_trigger(
        self,
        state: dict[str, Any],
        *,
        trigger_key: str,
        opportunity_keys: Sequence[str],
        fingerprint: str,
        timestamp: datetime,
    ) -> None:
        recent = self._recent_opportunity_claims(state, now=timestamp)
        for key in opportunity_keys:
            recent[str(key)] = timestamp
        state["recent_opportunity_claims"] = {
            key: value.isoformat() for key, value in sorted(recent.items())
        }
        records = state.get("opportunity_trigger_records")
        normalized = [
            dict(item)
            for item in (records if isinstance(records, list) else ())
            if isinstance(item, Mapping)
        ]
        normalized.append(
            {
                "trigger_key": trigger_key,
                "triggered_at": timestamp.isoformat(),
                "fingerprint": fingerprint,
                "opportunity_keys": list(dict.fromkeys(opportunity_keys)),
            }
        )
        state["opportunity_trigger_records"] = normalized[
            -_OPPORTUNITY_TRIGGER_HISTORY_LIMIT:
        ]
        # Compatibility fields remain available to diagnostics and older readers,
        # but they no longer provide global suppression authority.
        state.update(
            {
                "last_triggered_at": timestamp.isoformat(),
                "last_trigger_fingerprint": fingerprint,
                "last_trigger_key": trigger_key,
            }
        )

    def _claim_distinct_opportunities(
        self,
        state: dict[str, Any],
        *,
        opportunity_keys: Sequence[str],
        timestamp: datetime,
        prefix: str,
    ) -> tuple[str | None, tuple[str, ...]]:
        keys = tuple(
            dict.fromkeys(str(item).strip() for item in opportunity_keys if str(item).strip())
        )
        recent = self._recent_opportunity_claims(state, now=timestamp)
        new_keys = tuple(key for key in keys if key not in recent)
        state["recent_opportunity_claims"] = {
            key: value.isoformat() for key, value in sorted(recent.items())
        }
        if not new_keys:
            return None, ()
        fingerprint = hashlib.sha256(
            json.dumps(
                {"opportunity_keys": sorted(new_keys)},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        local = timestamp.astimezone(self.timezone)
        trigger_key = f"{prefix}-{local.strftime('%Y%m%d-%H%M%S')}-{fingerprint[:12]}"
        self._record_trigger(
            state,
            trigger_key=trigger_key,
            opportunity_keys=new_keys,
            fingerprint=fingerprint,
            timestamp=timestamp,
        )
        return trigger_key, new_keys

    def _attach_opportunities_to_trigger(
        self,
        state: dict[str, Any],
        *,
        trigger_key: str,
        opportunity_keys: Sequence[str],
        timestamp: datetime,
    ) -> tuple[str, ...]:
        keys = tuple(
            dict.fromkeys(str(item).strip() for item in opportunity_keys if str(item).strip())
        )
        recent = self._recent_opportunity_claims(state, now=timestamp)
        new_keys = tuple(key for key in keys if key not in recent)
        if not new_keys:
            state["recent_opportunity_claims"] = {
                key: value.isoformat() for key, value in sorted(recent.items())
            }
            return ()
        for key in new_keys:
            recent[key] = timestamp
        state["recent_opportunity_claims"] = {
            key: value.isoformat() for key, value in sorted(recent.items())
        }
        records = state.get("opportunity_trigger_records")
        normalized = [
            dict(item)
            for item in (records if isinstance(records, list) else ())
            if isinstance(item, Mapping)
        ]
        matched = False
        for item in normalized:
            if str(item.get("trigger_key", "")) != trigger_key:
                continue
            existing = tuple(
                str(value)
                for value in (item.get("opportunity_keys", ()) or ())
                if str(value).strip()
            )
            item["opportunity_keys"] = list(dict.fromkeys((*existing, *new_keys)))
            matched = True
            break
        if not matched:
            normalized.append(
                {
                    "trigger_key": trigger_key,
                    "triggered_at": timestamp.isoformat(),
                    "fingerprint": str(state.get("last_trigger_fingerprint", "")),
                    "opportunity_keys": list(new_keys),
                }
            )
        state["opportunity_trigger_records"] = normalized[
            -_OPPORTUNITY_TRIGGER_HISTORY_LIMIT:
        ]
        return new_keys

    def _instruments(self) -> tuple[tuple[str, str], ...]:
        payload = load_json(self.active_universe_path)
        publication_identifier = str(
            payload.get("eligible_universe_publication_identifier", "")
        ).strip()
        universe = payload.get("universe")
        items = universe.get("instruments") if isinstance(universe, Mapping) else None
        if not publication_identifier or not isinstance(items, list):
            raise ValueError(
                "the exact certified active paper universe is unavailable for reassessment"
            )
        result = tuple(
            (
                str(item.get("symbol", "")).upper(),
                str(item.get("instrument_type", "fund")).lower(),
            )
            for item in items
            if isinstance(item, Mapping) and str(item.get("symbol", "")).strip()
        )
        if not result:
            raise ValueError("the certified active paper universe contains no instruments")
        return result

    @staticmethod
    def _public_state(collection: object | None) -> tuple[str | None, int]:
        path = field(collection, "state_path")
        if path is None:
            return None, 0
        payload = load_json(Path(path))
        completed = payload.get("completed_at")
        count = payload.get("record_count", 0)
        return (
            completed if isinstance(completed, str) else None,
            int(count) if isinstance(count, int) else 0,
        )

    def scan_if_due(
        self,
        *,
        now: datetime,
        public_collection: object | None = None,
    ) -> ReassessmentResult:
        timestamp = aware_utc(now, "now")
        state = load_json(self.state_path)
        last_scan = parse_datetime(state.get("last_scanned_at"))
        if last_scan is not None and timestamp - last_scan < self.scan_interval:
            return ReassessmentResult(
                "not_due",
                timestamp,
                detail="The materiality scan is not due.",
            )
        if self._guarded(timestamp):
            state["last_scanned_at"] = timestamp.isoformat()
            save_json(self.state_path, state)
            return ReassessmentResult(
                "scheduled_guard",
                timestamp,
                detail="A configured scheduled-cycle guard is active.",
            )

        try:
            instruments = self._instruments()
            direct_types = {"spot", "token", "future"}
            listed_symbols = tuple(
                symbol
                for symbol, instrument_type in instruments
                if instrument_type not in direct_types
            )
            direct_symbols = tuple(
                symbol
                for symbol, instrument_type in instruments
                if instrument_type in direct_types
            )
            client = self.client_factory()
            listed_open = client.clock().get("is_open") is True
            snapshots: dict[str, Mapping[str, Any]] = {}
            if listed_symbols and listed_open:
                snapshots.update(client.snapshots(listed_symbols))
            direct_open = False
            if direct_symbols:
                direct_client = self.direct_client_factory()
                direct_open = direct_client.any_open(direct_symbols, as_of=timestamp)
                if direct_open:
                    snapshots.update(direct_client.snapshots(direct_symbols))
            if not listed_open and not direct_open:
                state["last_scanned_at"] = timestamp.isoformat()
                save_json(self.state_path, state)
                return ReassessmentResult(
                    "market_closed",
                    timestamp,
                    detail="No governed listed or direct market is currently open.",
                )
        except Exception as error:
            return ReassessmentResult(
                "failed",
                timestamp,
                detail=f"Materiality scan failed closed: {type(error).__name__}",
            )

        baselines = (
            state.get("assessment_prices")
            if isinstance(state.get("assessment_prices"), Mapping)
            else {}
        )
        baseline_revision = int(state.get("baseline_revision", 0) or 0)
        prices: dict[str, float] = {}
        reasons: list[str] = []
        opportunity_keys: list[str] = []
        for symbol, instrument_type in instruments:
            snapshot = snapshots.get(symbol)
            if not isinstance(snapshot, Mapping):
                continue
            current = snapshot_price(snapshot)
            prior = previous_close(snapshot)
            if current is None:
                continue
            prices[symbol] = current
            if prior:
                day_move = current / prior - 1
                if (
                    symbol in {"VTI", "VXUS"}
                    and abs(day_move) >= self.benchmark_move_threshold
                ):
                    reasons.append(
                        f"benchmark {symbol} moved {day_move:+.2%} from the prior close"
                    )
                    opportunity_keys.append(
                        f"benchmark-move:{symbol}:prior-close:{_direction(day_move)}"
                    )
                threshold = {
                    "common_stock": self.company_move_threshold,
                    "spot": 0.0075,
                    "token": 0.04,
                    "future": 0.015,
                }.get(instrument_type, self.instrument_move_threshold)
                if abs(day_move) >= threshold:
                    label = {
                        "common_stock": "company",
                        "spot": "spot FX market",
                        "token": "crypto market",
                        "future": "futures market",
                    }.get(instrument_type, "instrument")
                    reasons.append(
                        f"{label} {symbol} moved {day_move:+.2%} from the prior close"
                    )
                    opportunity_keys.append(
                        f"market-move:{symbol}:prior-close:{_direction(day_move)}"
                    )
            baseline = baselines.get(symbol)
            if isinstance(baseline, (int, float)) and float(baseline) > 0:
                move = current / float(baseline) - 1
                if abs(move) >= self.instrument_move_threshold:
                    reasons.append(
                        f"{symbol} moved {move:+.2%} since the last full CIO assessment"
                    )
                    opportunity_keys.append(
                        "assessment-move:"
                        f"{baseline_revision}:{symbol}:{_direction(move)}"
                    )

        public_at, public_count = self._public_state(public_collection)
        previous_public_at = state.get("public_completed_at")
        previous_public_count = int(state.get("public_record_count", 0) or 0)
        if (
            previous_public_at
            and public_at
            and public_at != previous_public_at
            and public_count > previous_public_count
        ):
            reasons.append(
                "governed public-information records increased from "
                f"{previous_public_count} to {public_count}"
            )
            opportunity_keys.append(f"public-record-set:{public_at}:{public_count}")

        state.update(
            {
                "schema_version": "cio-material-reassessment-state.v2",
                "last_scanned_at": timestamp.isoformat(),
                "last_prices": prices,
                "public_completed_at": public_at,
                "public_record_count": public_count,
                "paper_only": True,
                "real_money_authorized": False,
            }
        )
        reasons = list(dict.fromkeys(reasons))
        opportunity_keys = list(dict.fromkeys(opportunity_keys))
        if not reasons:
            # Prune expired claims even during quiet scans so state remains bounded.
            recent = self._recent_opportunity_claims(state, now=timestamp)
            state["recent_opportunity_claims"] = {
                key: value.isoformat() for key, value in sorted(recent.items())
            }
            save_json(self.state_path, state)
            return ReassessmentResult(
                "no_material_change",
                timestamp,
                symbol_count=len(prices),
                detail="No configured materiality threshold was crossed.",
            )

        trigger, claimed = self._claim_distinct_opportunities(
            state,
            opportunity_keys=opportunity_keys,
            timestamp=timestamp,
            prefix="material",
        )
        if trigger is None:
            save_json(self.state_path, state)
            return ReassessmentResult(
                "deduplicated",
                timestamp,
                reasons=tuple(reasons),
                symbol_count=len(prices),
                detail=(
                    "Every currently material opportunity already requested a CIO "
                    "reassessment inside its own deduplication window."
                ),
            )

        state["last_trigger_opportunity_keys"] = list(claimed)
        save_json(self.state_path, state)
        return ReassessmentResult(
            "triggered",
            timestamp,
            True,
            trigger,
            tuple(reasons),
            len(prices),
            (
                "Distinct material live evidence requests a full canonical CIO "
                "reassessment; unrelated recent events do not suppress it."
            ),
        )

    def release_trigger(self, trigger_key: str) -> None:
        state = load_json(self.state_path)
        records = state.get("opportunity_trigger_records")
        normalized = [
            dict(item)
            for item in (records if isinstance(records, list) else ())
            if isinstance(item, Mapping)
        ]
        released_keys: set[str] = set()
        retained: list[dict[str, Any]] = []
        for item in normalized:
            if str(item.get("trigger_key", "")) == trigger_key:
                released_keys.update(
                    str(value)
                    for value in (item.get("opportunity_keys", ()) or ())
                    if str(value).strip()
                )
            else:
                retained.append(item)
        if released_keys:
            recent = state.get("recent_opportunity_claims")
            if isinstance(recent, Mapping):
                state["recent_opportunity_claims"] = {
                    str(key): value
                    for key, value in recent.items()
                    if str(key) not in released_keys
                }
            state["opportunity_trigger_records"] = retained[
                -_OPPORTUNITY_TRIGGER_HISTORY_LIMIT:
            ]
        if state.get("last_trigger_key") == trigger_key:
            for key in (
                "last_triggered_at",
                "last_trigger_fingerprint",
                "last_trigger_key",
                "last_trigger_opportunity_keys",
            ):
                state.pop(key, None)
        save_json(self.state_path, state)

    def acknowledge_assessment(self, *, now: datetime) -> None:
        timestamp = aware_utc(now, "now")
        state = load_json(self.state_path)
        prices = state.get("last_prices")
        if isinstance(prices, Mapping):
            state["assessment_prices"] = {
                str(symbol): float(price)
                for symbol, price in prices.items()
                if isinstance(price, (int, float)) and float(price) > 0
            }
        state["last_assessment_at"] = timestamp.isoformat()
        state["baseline_revision"] = int(state.get("baseline_revision", 0) or 0) + 1
        save_json(self.state_path, state)


__all__ = [
    "MaterialCIOReassessmentEngine",
    "ReassessmentResult",
    "aware_utc",
    "load_json",
    "parse_clock",
    "save_json",
]
