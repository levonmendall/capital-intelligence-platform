"""Durable partitioned option discovery for exact-release all-market certification.

The canonical option universe remains opportunity-complete. Alpaca continues to own
contract-definition discovery; this module changes only how historical evidence is
hydrated after those definitions are known. Evidence work is partitioned by expiration,
large Alpaca history requests are recursively reduced after transient failures, and only
missing symbols are routed through the existing Alpaca -> Tradier -> Massive redundant
history path.

Completed definition manifests and expiration partitions are persisted under the exact
release and exact decision epoch. A new epoch never reuses freshness-sensitive option
history. Existing checkpoints are integrity checked and a malformed/tampered artifact
fails closed rather than being silently ignored.

This module grants no investment, construction, execution, or live-money authority and
never truncates the configured option universe or lowers an evidence requirement.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from operations.manual_cio_diagnostic import record_manual_cio_diagnostic_progress
from providers.alpaca_indicative_options import (
    ALPACA_INDICATIVE_OPTIONS_DATASET,
    AlpacaIndicativeOptionsError,
)
from providers.redundant_options import (
    RedundantOptionBar,
    RedundantOptionDefinition,
    RedundantOptionSelection,
    RedundantOptionsError,
    RedundantOptionsProvider,
    build_redundant_options_provider,
)

_SCHEMA_VERSION = "resumable-options-discovery.v1"
_SELECTION_HISTORY_DAYS = 365


class ResumableOptionsDiscoveryError(RedundantOptionsError):
    """Raised when an exact-release option checkpoint cannot be trusted."""


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("option decision epoch must be timezone-aware")
    return value.astimezone(timezone.utc)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _checkpoint_enabled(values: Mapping[str, str]) -> bool:
    return bool(values.get("CAPITAL_INTELLIGENCE_DATA_DIR")) and _release(values) != "unknown"


def _slug(value: object) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value).strip())
    return normalized.strip("-.") or "unknown"


def _request_material(
    *,
    underlying: str,
    underlying_price: float,
    as_of: datetime,
    minimum_days_to_expiry: int,
    maximum_days_to_expiry: int,
    maximum_expirations: int,
    candidates_per_bucket: int,
) -> Mapping[str, object]:
    return {
        "underlying": underlying,
        "underlying_price": float(underlying_price),
        "decision_epoch": as_of.isoformat(),
        "minimum_days_to_expiry": minimum_days_to_expiry,
        "maximum_days_to_expiry": maximum_days_to_expiry,
        "maximum_expirations": maximum_expirations,
        "candidates_per_bucket": candidates_per_bucket,
    }


def _checkpoint_dir(
    values: Mapping[str, str],
    *,
    request: Mapping[str, object],
) -> Path | None:
    if not _checkpoint_enabled(values):
        return None
    base = Path(values["CAPITAL_INTELLIGENCE_DATA_DIR"]).expanduser()
    epoch = str(request["decision_epoch"])
    return (
        base
        / "all-market-certification"
        / "options"
        / _slug(_release(values))
        / _digest(epoch)[:20]
        / _slug(request["underlying"])
        / _digest(request)[:24]
    )


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    material = dict(payload)
    material["integrity_sha256"] = _digest(payload)
    encoded = json.dumps(material, sort_keys=True, indent=2, allow_nan=False) + "\n"
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(encoded, encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: Path, *, expected: Mapping[str, object]) -> Mapping[str, object] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as error:
        raise ResumableOptionsDiscoveryError(
            f"option checkpoint is unreadable: {path.name}"
        ) from error
    if not isinstance(raw, Mapping):
        raise ResumableOptionsDiscoveryError(
            f"option checkpoint is not an object: {path.name}"
        )
    payload = dict(raw)
    integrity = payload.pop("integrity_sha256", None)
    if not isinstance(integrity, str) or integrity != _digest(payload):
        raise ResumableOptionsDiscoveryError(
            f"option checkpoint integrity mismatch: {path.name}"
        )
    if payload.get("schema_version") != _SCHEMA_VERSION:
        raise ResumableOptionsDiscoveryError(
            f"option checkpoint schema mismatch: {path.name}"
        )
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ResumableOptionsDiscoveryError(
                f"option checkpoint scope mismatch for {key}: {path.name}"
            )
    return payload


def _definition_payload(item: RedundantOptionDefinition) -> Mapping[str, object]:
    return {
        "symbol": item.symbol,
        "raw_symbol": item.raw_symbol,
        "underlying": item.underlying,
        "option_right": item.option_right,
        "expiration_at": item.expiration_at.isoformat(),
        "strike": item.strike,
        "contract_multiplier": item.contract_multiplier,
        "session_date": item.session_date.isoformat(),
        "provider_kind": item.provider_kind,
        "provider_dataset": item.provider_dataset,
        "provider_stype_in": item.provider_stype_in,
        "provider_instrument_id": item.provider_instrument_id,
        "source_identifier": item.source_identifier,
    }


def _definition_from_payload(raw: Mapping[str, object]) -> RedundantOptionDefinition:
    expiration = datetime.fromisoformat(str(raw["expiration_at"]))
    session = date.fromisoformat(str(raw["session_date"]))
    return RedundantOptionDefinition(
        symbol=str(raw["symbol"]),
        raw_symbol=str(raw["raw_symbol"]),
        underlying=str(raw["underlying"]),
        option_right=str(raw["option_right"]),
        expiration_at=_aware(expiration),
        strike=float(raw["strike"]),
        contract_multiplier=float(raw["contract_multiplier"]),
        session_date=session,
        provider_kind=str(raw["provider_kind"]),
        provider_dataset=str(raw["provider_dataset"]),
        provider_stype_in=str(raw["provider_stype_in"]),
        provider_instrument_id=(
            None
            if raw.get("provider_instrument_id") is None
            else int(raw["provider_instrument_id"])
        ),
        source_identifier=str(raw["source_identifier"]),
    )


def _bar_payload(item: RedundantOptionBar) -> Mapping[str, object]:
    return {
        "raw_symbol": item.raw_symbol,
        "observed_at": item.observed_at.isoformat(),
        "close": item.close,
        "volume": item.volume,
        "provider_kind": item.provider_kind,
        "source_identifier": item.source_identifier,
    }


def _bar_from_payload(raw: Mapping[str, object], *, as_of: datetime) -> RedundantOptionBar:
    observed = _aware(datetime.fromisoformat(str(raw["observed_at"])))
    if observed > as_of:
        raise ResumableOptionsDiscoveryError(
            "option checkpoint contains evidence from after the decision epoch"
        )
    return RedundantOptionBar(
        raw_symbol=str(raw["raw_symbol"]),
        observed_at=observed,
        close=float(raw["close"]),
        volume=float(raw["volume"]),
        provider_kind=str(raw["provider_kind"]),
        source_identifier=str(raw["source_identifier"]),
    )


def _selection_payload(item: RedundantOptionSelection) -> Mapping[str, object]:
    return {
        "definition": _definition_payload(item.definition),
        "bar": _bar_payload(item.bar),
    }


def _selection_from_payload(raw: Mapping[str, object], *, as_of: datetime) -> RedundantOptionSelection:
    definition = raw.get("definition")
    bar = raw.get("bar")
    if not isinstance(definition, Mapping) or not isinstance(bar, Mapping):
        raise ResumableOptionsDiscoveryError("option checkpoint selection is malformed")
    return RedundantOptionSelection(
        definition=_definition_from_payload(definition),
        bar=_bar_from_payload(bar, as_of=as_of),
    )


def _adapt_primary_definition(item: object) -> RedundantOptionDefinition:
    return RedundantOptionDefinition(
        symbol=str(getattr(item, "symbol")),
        raw_symbol=str(getattr(item, "raw_symbol")),
        underlying=str(getattr(item, "underlying")),
        option_right=str(getattr(item, "option_right")),
        expiration_at=_aware(getattr(item, "expiration_at")),
        strike=float(getattr(item, "strike")),
        contract_multiplier=float(getattr(item, "contract_multiplier")),
        session_date=getattr(item, "session_date"),
        provider_kind="alpaca_indicative",
        provider_dataset=ALPACA_INDICATIVE_OPTIONS_DATASET,
        provider_stype_in="raw_symbol",
        provider_instrument_id=None,
        source_identifier=str(getattr(item, "source_identifier")),
    )


def _adapt_primary_bars(
    bars: Mapping[str, Sequence[object]],
) -> dict[str, tuple[RedundantOptionBar, ...]]:
    result: dict[str, tuple[RedundantOptionBar, ...]] = {}
    for raw_symbol, history in bars.items():
        adapted = tuple(
            RedundantOptionBar(
                raw_symbol=str(getattr(item, "raw_symbol", raw_symbol)),
                observed_at=_aware(getattr(item, "observed_at")),
                close=float(getattr(item, "close")),
                volume=float(getattr(item, "volume")),
                provider_kind="alpaca_indicative",
                source_identifier=str(getattr(item, "source_identifier")),
            )
            for item in history
        )
        if adapted:
            result[str(raw_symbol).strip().upper()] = adapted
    return result


class ResumableOptionsProvider:
    """Exact-epoch option catalog provider with expiration-level evidence checkpoints."""

    redundant_options_provider = True

    def __init__(
        self,
        delegate: RedundantOptionsProvider | None = None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.delegate = delegate or build_redundant_options_provider()
        self._environ = environ

    @property
    def _values(self) -> Mapping[str, str]:
        return os.environ if self._environ is None else self._environ

    @property
    def configured(self) -> bool:
        return bool(self.delegate.configured)

    @property
    def primary_configured(self) -> bool:
        return bool(self.delegate.primary_configured)

    @property
    def secondary_configured(self) -> bool:
        return bool(self.delegate.secondary_configured)

    @property
    def fallback_configured(self) -> bool:
        return bool(self.delegate.fallback_configured)

    def latest_daily_bars(self, *args, **kwargs):
        return self.delegate.latest_daily_bars(*args, **kwargs)

    def _definitions(
        self,
        *,
        underlying: str,
        underlying_price: float,
        as_of: datetime,
        minimum_days_to_expiry: int,
        maximum_days_to_expiry: int,
        request: Mapping[str, object],
        directory: Path | None,
    ) -> tuple[RedundantOptionDefinition, ...]:
        path = None if directory is None else directory / "definitions.json"
        expected = {
            "release": _release(self._values),
            "decision_epoch": as_of.isoformat(),
            "request_sha256": _digest(request),
            "kind": "definitions",
        }
        if path is not None:
            payload = _read_json(path, expected=expected)
            if payload is not None:
                rows = payload.get("definitions")
                if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
                    raise ResumableOptionsDiscoveryError(
                        "option definition checkpoint rows are malformed"
                    )
                return tuple(
                    _definition_from_payload(item)
                    for item in rows
                    if isinstance(item, Mapping)
                )
        if not self.delegate.primary_configured:
            return ()
        try:
            raw = self.delegate.primary.definitions(
                underlying,
                underlying_price=underlying_price,
                as_of=as_of,
                minimum_days_to_expiry=minimum_days_to_expiry,
                maximum_days_to_expiry=maximum_days_to_expiry,
            )
        except AlpacaIndicativeOptionsError:
            raise
        definitions = tuple(_adapt_primary_definition(item) for item in raw)
        if path is not None:
            _atomic_json(
                path,
                {
                    "schema_version": _SCHEMA_VERSION,
                    **expected,
                    "paper_only": True,
                    "real_money_authorized": False,
                    "definitions": [_definition_payload(item) for item in definitions],
                },
            )
        return definitions

    def _primary_history(
        self,
        raw_symbols: Sequence[str],
        *,
        as_of: datetime,
        history_days: int,
    ) -> dict[str, tuple[RedundantOptionBar, ...]]:
        symbols = tuple(dict.fromkeys(str(item).strip().upper() for item in raw_symbols if str(item).strip()))
        if not symbols or not self.delegate.primary_configured:
            return {}

        def fetch(batch: tuple[str, ...]) -> dict[str, tuple[RedundantOptionBar, ...]]:
            try:
                _session, bars = self.delegate.primary.latest_daily_bars(
                    tuple((None, symbol) for symbol in batch),
                    as_of=as_of,
                    history_days=history_days,
                )
                return _adapt_primary_bars(bars)
            except AlpacaIndicativeOptionsError:
                if len(batch) <= 1:
                    return {}
                midpoint = max(1, len(batch) // 2)
                result = fetch(batch[:midpoint])
                result.update(fetch(batch[midpoint:]))
                return result

        return fetch(symbols)

    def _resilient_history(
        self,
        raw_symbols: Sequence[str],
        *,
        as_of: datetime,
        history_days: int,
    ) -> Mapping[str, tuple[RedundantOptionBar, ...]]:
        normalized = tuple(dict.fromkeys(str(item).strip().upper() for item in raw_symbols if str(item).strip()))
        result = self._primary_history(
            normalized,
            as_of=as_of,
            history_days=history_days,
        )
        missing = tuple(symbol for symbol in normalized if symbol not in result)
        if missing:
            _session, redundant = self.delegate.latest_daily_bars(
                tuple((None, symbol) for symbol in missing),
                as_of=as_of,
                history_days=history_days,
            )
            for symbol, bars in redundant.items():
                key = str(symbol).strip().upper()
                if bars:
                    result[key] = tuple(bars)
        return result

    def _partition(
        self,
        *,
        expiration: datetime,
        definitions: Sequence[RedundantOptionDefinition],
        underlying_price: float,
        as_of: datetime,
        candidates_per_bucket: int,
        request: Mapping[str, object],
        directory: Path | None,
    ) -> tuple[RedundantOptionSelection, ...]:
        path = (
            None
            if directory is None
            else directory / f"expiration-{expiration.strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        expected = {
            "release": _release(self._values),
            "decision_epoch": as_of.isoformat(),
            "request_sha256": _digest(request),
            "kind": "expiration_partition",
            "expiration_at": expiration.isoformat(),
        }
        if path is not None:
            payload = _read_json(path, expected=expected)
            if payload is not None:
                rows = payload.get("selections")
                if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
                    raise ResumableOptionsDiscoveryError(
                        "option expiration checkpoint rows are malformed"
                    )
                return tuple(
                    _selection_from_payload(item, as_of=as_of)
                    for item in rows
                    if isinstance(item, Mapping)
                )

        buckets: dict[str, tuple[RedundantOptionDefinition, ...]] = {}
        candidates: list[RedundantOptionDefinition] = []
        for right in ("call", "put"):
            ranked = sorted(
                (
                    item
                    for item in definitions
                    if item.expiration_at == expiration and item.option_right == right
                ),
                key=lambda item: (
                    abs(item.strike / underlying_price - 1.0),
                    item.strike,
                    item.symbol,
                ),
            )[:candidates_per_bucket]
            buckets[right] = tuple(ranked)
            candidates.extend(ranked)
        if not candidates:
            selections: tuple[RedundantOptionSelection, ...] = ()
        else:
            short_bars = self._resilient_history(
                tuple(item.raw_symbol for item in candidates),
                as_of=as_of,
                history_days=10,
            )
            provisional: list[RedundantOptionSelection] = []
            for right in ("call", "put"):
                choices: list[tuple[float, RedundantOptionDefinition, RedundantOptionBar]] = []
                for definition in buckets[right]:
                    history = short_bars.get(definition.raw_symbol.strip().upper(), ())
                    if not history:
                        continue
                    latest = history[-1]
                    moneyness = abs(definition.strike / underlying_price - 1.0)
                    score = math.log10(max(1.0, latest.volume)) - 5.0 * moneyness
                    choices.append((score, definition, latest))
                if choices:
                    choices.sort(key=lambda item: (item[0], item[1].symbol), reverse=True)
                    _score, definition, latest = choices[0]
                    provisional.append(
                        RedundantOptionSelection(definition=definition, bar=latest)
                    )
            if provisional:
                deep_bars = self._resilient_history(
                    tuple(item.definition.raw_symbol for item in provisional),
                    as_of=as_of,
                    history_days=_SELECTION_HISTORY_DAYS,
                )
                selections = tuple(
                    RedundantOptionSelection(
                        definition=item.definition,
                        bar=deep_bars[item.definition.raw_symbol.strip().upper()][-1],
                    )
                    for item in provisional
                    if deep_bars.get(item.definition.raw_symbol.strip().upper())
                )
            else:
                selections = ()

        if path is not None:
            _atomic_json(
                path,
                {
                    "schema_version": _SCHEMA_VERSION,
                    **expected,
                    "paper_only": True,
                    "real_money_authorized": False,
                    "candidate_count_limit_applied": False,
                    "selections": [_selection_payload(item) for item in selections],
                },
            )
        return selections

    def select_contracts(
        self,
        underlying: str,
        *,
        underlying_price: float,
        as_of: datetime,
        minimum_days_to_expiry: int,
        maximum_days_to_expiry: int,
        maximum_expirations: int = 1_000,
        candidates_per_bucket: int = 8,
    ) -> tuple[RedundantOptionSelection, ...]:
        timestamp = _aware(as_of)
        normalized = str(underlying).strip().upper()
        price = float(underlying_price)
        if not normalized:
            raise ValueError("underlying cannot be empty")
        if not math.isfinite(price) or price <= 0.0:
            raise ValueError("underlying_price must be positive")
        if maximum_expirations < 1 or candidates_per_bucket < 1:
            raise ValueError("option partition bounds must be positive")
        request = _request_material(
            underlying=normalized,
            underlying_price=price,
            as_of=timestamp,
            minimum_days_to_expiry=minimum_days_to_expiry,
            maximum_days_to_expiry=maximum_days_to_expiry,
            maximum_expirations=maximum_expirations,
            candidates_per_bucket=candidates_per_bucket,
        )
        directory = _checkpoint_dir(self._values, request=request)
        record_manual_cio_diagnostic_progress(
            "catalog_options_partitioned",
            metrics={"underlying": normalized},
        )
        if not self.delegate.primary_configured:
            return self.delegate.select_contracts(
                normalized,
                underlying_price=price,
                as_of=timestamp,
                minimum_days_to_expiry=minimum_days_to_expiry,
                maximum_days_to_expiry=maximum_days_to_expiry,
                maximum_expirations=maximum_expirations,
                candidates_per_bucket=candidates_per_bucket,
            )
        definitions = self._definitions(
            underlying=normalized,
            underlying_price=price,
            as_of=timestamp,
            minimum_days_to_expiry=minimum_days_to_expiry,
            maximum_days_to_expiry=maximum_days_to_expiry,
            request=request,
            directory=directory,
        )
        expirations = tuple(sorted({item.expiration_at for item in definitions}))[:maximum_expirations]
        selected: list[RedundantOptionSelection] = []
        for index, expiration in enumerate(expirations, start=1):
            record_manual_cio_diagnostic_progress(
                "catalog_options_expiration_partition",
                metrics={
                    "underlying": normalized,
                    "partition": index,
                    "partitions": len(expirations),
                },
            )
            selected.extend(
                self._partition(
                    expiration=expiration,
                    definitions=definitions,
                    underlying_price=price,
                    as_of=timestamp,
                    candidates_per_bucket=candidates_per_bucket,
                    request=request,
                    directory=directory,
                )
            )
        selected.sort(
            key=lambda item: (
                item.definition.expiration_at,
                item.definition.option_right,
                item.definition.strike,
                item.definition.symbol,
            )
        )
        record_manual_cio_diagnostic_progress(
            "catalog_options_partitioned_complete",
            metrics={
                "underlying": normalized,
                "expiration_partitions": len(expirations),
                "selected_contracts": len(selected),
            },
        )
        return tuple(selected)


def install_resumable_options_catalog(core_module) -> None:
    """Inject exact-epoch option partitioning into the preserved catalog facade."""

    catalog_module = core_module._base
    current = catalog_module.default_catalog_probe
    if bool(getattr(current, "resumable_options_catalog", False)):
        return

    def checkpointed_default_catalog_probe(as_of, **kwargs):
        if kwargs.get("databento_options_provider") is None:
            kwargs["databento_options_provider"] = ResumableOptionsProvider()
        return current(as_of, **kwargs)

    checkpointed_default_catalog_probe.resumable_options_catalog = True
    checkpointed_default_catalog_probe.__name__ = current.__name__
    catalog_module.default_catalog_probe = checkpointed_default_catalog_probe


__all__ = [
    "ResumableOptionsDiscoveryError",
    "ResumableOptionsProvider",
    "install_resumable_options_catalog",
]
