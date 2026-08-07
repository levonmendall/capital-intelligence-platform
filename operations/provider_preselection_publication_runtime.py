"""Build the governed provider-factor publication needed by market discovery.

The provider-enriched selector intentionally does not synthesize neutral factors from
catalog order or static metadata. This runtime collector obtains point-in-time provider
measurements in two bounded ways:

* EODHD exchange-wide bulk EOD snapshots provide current price, provider technicals,
  volume, dividend, and earnings fields without issuing one request per security; and
* provider-native market probes supply historical features for derivative and other
  non-directory records that are not represented by an EODHD exchange snapshot.

Every published factor contains provider evidence lineage. Unsupported asset-specific
factors are explicitly marked not applicable with a governed rationale; at least one
substantive provider-derived factor is still required for a signal to be published.
The resulting JSON is written atomically to the persistent provider-preselection path.
It has nomination evidence authority only and cannot qualify, size, authorize, execute,
or promote an investment.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import requests

from cio import CandidateAssetClass
from operations.comprehensive_market_discovery_legacy import (
    ComprehensiveMarketDiscoveryPolicy,
    DiscoveryCatalogRecord,
    DiscoveryMarketFeatures,
    default_market_probe,
)
from operations.provider_enriched_preselection import (
    DEFAULT_PROVIDER_PRESELECTION_PATH,
    PROVIDER_PRESELECTION_SCHEMA,
    REQUIRED_PROVIDER_FACTORS,
)
from operations.manual_cio_diagnostic import record_manual_cio_diagnostic_progress


_EODHD_API_BASE = "https://eodhd.com/api"
_EODHD_SOURCE_PATTERN = re.compile(
    r"symbol_directory:(?P<exchange>[^:]+):.*:(?P<code>[^:]+)$",
    re.IGNORECASE,
)
_PUBLICATION_METHOD_VERSION = "provider-preselection-runtime.v1"
_MAX_PROVIDER_IO_WORKERS = 4


class ProviderPreselectionPublicationError(RuntimeError):
    """Raised when no governed provider-factor publication can be produced."""


@dataclass(frozen=True, slots=True)
class ProviderPreselectionPublicationResult:
    path: Path
    available_at: datetime
    catalog_count: int
    signal_count: int
    reused: bool
    source_identifiers: tuple[str, ...]
    limitations: tuple[str, ...]

    @property
    def coverage_ratio(self) -> float:
        if self.catalog_count < 1:
            return 0.0
        return self.signal_count / self.catalog_count


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _first_number(payload: Mapping[str, object], *names: str) -> float | None:
    for name in names:
        value = _number(payload.get(name))
        if value is not None:
            return value
    return None


def _first_text(payload: Mapping[str, object], *names: str) -> str | None:
    for name in names:
        value = payload.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _clamp(value: float) -> float:
    return round(min(1.0, max(0.0, float(value))), 10)


def _directional_score(raw_value: float, *, scale: float) -> float:
    return _clamp(0.5 + 0.5 * math.tanh(float(raw_value) * scale))


def _liquidity_score(dollar_volume: float | None) -> float | None:
    if dollar_volume is None or dollar_volume <= 0.0:
        return None
    return _clamp((math.log10(max(dollar_volume, 1.0)) - 4.0) / 7.0)


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _publication_path(policy: object | None) -> Path:
    configured = (
        None
        if policy is None
        else getattr(policy, "provider_preselection_path", None)
    )
    value = (
        configured
        or os.getenv("CAPITAL_INTELLIGENCE_PROVIDER_PRESELECTION_PATH")
        or DEFAULT_PROVIDER_PRESELECTION_PATH
    )
    return Path(str(value)).expanduser()


def _catalog_fingerprint(records: Sequence[DiscoveryCatalogRecord]) -> str:
    return _hash(
        [
            (
                item.asset_class.value,
                item.symbol,
                item.provider_symbol,
                item.source_identifier,
            )
            for item in sorted(
                records,
                key=lambda record: (record.asset_class.value, record.symbol),
            )
        ]
    )


def _flatten_catalogs(
    catalogs: Mapping[CandidateAssetClass, Sequence[DiscoveryCatalogRecord]],
) -> tuple[DiscoveryCatalogRecord, ...]:
    by_key: dict[tuple[CandidateAssetClass, str], DiscoveryCatalogRecord] = {}
    for asset_class, values in catalogs.items():
        if not isinstance(asset_class, CandidateAssetClass):
            continue
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise ProviderPreselectionPublicationError(
                f"{asset_class.value} catalog must be a sequence"
            )
        for record in values:
            if not isinstance(record, DiscoveryCatalogRecord):
                raise ProviderPreselectionPublicationError(
                    f"{asset_class.value} catalog contains an invalid record"
                )
            by_key[(record.asset_class, record.symbol)] = record
    return tuple(
        by_key[key]
        for key in sorted(by_key, key=lambda item: (item[0].value, item[1]))
    )


def _existing_result(
    path: Path,
    *,
    as_of: datetime,
    fingerprint: str,
    catalog_count: int,
    freshness_days: int,
) -> ProviderPreselectionPublicationResult | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    if payload.get("schema_version") != PROVIDER_PRESELECTION_SCHEMA:
        return None
    if payload.get("catalog_fingerprint") != fingerprint:
        return None
    available_at = _parse_timestamp(payload.get("available_at"))
    if available_at is None or available_at > as_of:
        return None
    if (as_of - available_at).total_seconds() > freshness_days * 86_400:
        return None
    signals = payload.get("signals")
    if not isinstance(signals, Mapping) or not signals:
        return None
    sources = payload.get("source_identifiers", ())
    limitations = payload.get("limitations", ())
    return ProviderPreselectionPublicationResult(
        path=path,
        available_at=available_at,
        catalog_count=catalog_count,
        signal_count=len(signals),
        reused=True,
        source_identifiers=tuple(
            str(item) for item in sources if isinstance(item, str) and item.strip()
        ),
        limitations=tuple(
            str(item)
            for item in limitations
            if isinstance(item, str) and item.strip()
        ),
    )


def _source_exchange_and_code(
    record: DiscoveryCatalogRecord,
) -> tuple[str, str] | None:
    match = _EODHD_SOURCE_PATTERN.search(record.source_identifier)
    if match is None:
        return None
    exchange = match.group("exchange").strip().upper()
    code = match.group("code").strip().upper()
    return (exchange, code) if exchange and code else None


def _row_keys(payload: Mapping[str, object]) -> tuple[str, ...]:
    raw = _first_text(payload, "code", "Code", "symbol", "Symbol", "ticker")
    if raw is None:
        return ()
    normalized = raw.strip().upper()
    return tuple(
        dict.fromkeys(
            (
                normalized,
                normalized.split(".", 1)[0],
                normalized.replace("_", "-"),
                normalized.replace("/", "-"),
            )
        )
    )


def _bulk_snapshot(
    exchange: str,
    *,
    as_of: datetime,
    api_token: str,
    http_get: Callable[..., Any],
) -> tuple[tuple[Mapping[str, object], ...], datetime, str]:
    last_error: str | None = None
    for offset in range(8):
        requested_date = as_of.date() - timedelta(days=offset)
        try:
            response = http_get(
                f"{_EODHD_API_BASE}/eod-bulk-last-day/{exchange}",
                params={
                    "api_token": api_token,
                    "fmt": "json",
                    "filter": "extended",
                    "date": requested_date.isoformat(),
                },
                headers={
                    "User-Agent": "capital-intelligence-provider-preselection/1.0"
                },
                timeout=90,
            )
        except (OSError, requests.RequestException) as error:
            last_error = type(error).__name__
            continue
        status_code = int(getattr(response, "status_code", 0))
        if status_code in {401, 403}:
            raise ProviderPreselectionPublicationError(
                f"EODHD bulk EOD entitlement is unavailable for {exchange} "
                f"(HTTP {status_code})"
            )
        if status_code != 200:
            last_error = f"HTTP {status_code}"
            continue
        try:
            payload = response.json()
        except (TypeError, ValueError):
            last_error = "invalid_json"
            continue
        if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
            last_error = "invalid_payload_shape"
            continue
        rows = tuple(item for item in payload if isinstance(item, Mapping))
        if not rows:
            last_error = "empty_payload"
            continue
        observed_at = datetime.combine(
            requested_date,
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
        evidence = (
            f"eodhd-bulk-eod:{exchange}:{requested_date.isoformat()}:"
            f"{_hash(rows)}"
        )
        return rows, observed_at, evidence
    raise ProviderPreselectionPublicationError(
        f"EODHD bulk EOD snapshot is unavailable for {exchange}: "
        f"{last_error or 'unknown failure'}"
    )


def _factor_scored(
    *,
    score: float,
    raw_value: float,
    units: str,
    horizon_days: int,
    provider: str,
    methodology_version: str,
    observed_at: datetime,
    evidence_identifiers: Sequence[str],
) -> dict[str, object]:
    return {
        "applicability": "scored",
        "score": _clamp(score),
        "raw_value": float(raw_value),
        "units": units,
        "horizon_days": max(1, int(horizon_days)),
        "provider": provider,
        "methodology_version": methodology_version,
        "observed_at": observed_at.isoformat(),
        "evidence_identifiers": list(dict.fromkeys(evidence_identifiers)),
    }


def _factor_not_applicable(
    *,
    factor: str,
    provider: str,
    observed_at: datetime,
    evidence_identifiers: Sequence[str],
    rationale: str,
) -> dict[str, object]:
    return {
        "applicability": "not_applicable",
        "rationale": rationale,
        "provider": provider,
        "methodology_version": f"{_PUBLICATION_METHOD_VERSION}.{factor}-applicability",
        "observed_at": observed_at.isoformat(),
        "evidence_identifiers": list(dict.fromkeys(evidence_identifiers)),
    }


def _bulk_signal(
    record: DiscoveryCatalogRecord,
    row: Mapping[str, object],
    *,
    observed_at: datetime,
    evidence_identifier: str,
) -> dict[str, object] | None:
    row_evidence = (
        record.source_identifier,
        evidence_identifier,
        f"eodhd-bulk-row:{record.symbol}:{_hash(row)}",
    )
    price = _first_number(
        row,
        "adjusted_close",
        "adjustedClose",
        "adjusted-close",
        "close",
        "Close",
    )
    ema_50 = _first_number(
        row,
        "ema_50d",
        "ema50",
        "ema_50",
        "ema50d",
        "ema_50_days",
    )
    ema_200 = _first_number(
        row,
        "ema_200d",
        "ema200",
        "ema_200",
        "ema200d",
        "ema_200_days",
    )
    change_percent = _first_number(
        row,
        "change_p",
        "change_percent",
        "changePercent",
        "refund_1d_p",
    )
    eps = _first_number(row, "earnings_share", "eps", "EPS")
    dividend_yield = _first_number(
        row,
        "dividend_yield",
        "dividendYield",
        "yield",
    )
    average_volume = _first_number(
        row,
        "avgvol_200d",
        "avgvol200d",
        "average_volume_200d",
        "averageVolume200d",
        "volume",
        "Volume",
    )

    factors: dict[str, object] = {}
    if price is not None and price > 0.0 and ema_200 is not None and ema_200 > 0.0:
        raw_momentum = price / ema_200 - 1.0
        factors["momentum"] = _factor_scored(
            score=_directional_score(raw_momentum, scale=3.0),
            raw_value=raw_momentum,
            units="price-to-ema-200-return",
            horizon_days=200,
            provider="EODHD",
            methodology_version=f"{_PUBLICATION_METHOD_VERSION}.momentum-ema200",
            observed_at=observed_at,
            evidence_identifiers=row_evidence,
        )
    elif price is not None and price > 0.0 and ema_50 is not None and ema_50 > 0.0:
        raw_momentum = price / ema_50 - 1.0
        factors["momentum"] = _factor_scored(
            score=_directional_score(raw_momentum, scale=4.0),
            raw_value=raw_momentum,
            units="price-to-ema-50-return",
            horizon_days=50,
            provider="EODHD",
            methodology_version=f"{_PUBLICATION_METHOD_VERSION}.momentum-ema50",
            observed_at=observed_at,
            evidence_identifiers=row_evidence,
        )
    elif change_percent is not None:
        raw_momentum = change_percent / 100.0
        factors["momentum"] = _factor_scored(
            score=_directional_score(raw_momentum, scale=8.0),
            raw_value=raw_momentum,
            units="one-day-return",
            horizon_days=1,
            provider="EODHD",
            methodology_version=f"{_PUBLICATION_METHOD_VERSION}.momentum-1d",
            observed_at=observed_at,
            evidence_identifiers=row_evidence,
        )

    if ema_50 is not None and ema_50 > 0.0 and ema_200 is not None and ema_200 > 0.0:
        raw_improvement = ema_50 / ema_200 - 1.0
        factors["improving_conditions"] = _factor_scored(
            score=_directional_score(raw_improvement, scale=6.0),
            raw_value=raw_improvement,
            units="ema-50-to-ema-200-spread",
            horizon_days=150,
            provider="EODHD",
            methodology_version=(
                f"{_PUBLICATION_METHOD_VERSION}.improving-conditions-ema-spread"
            ),
            observed_at=observed_at,
            evidence_identifiers=row_evidence,
        )

    equity_like = record.instrument_type in {
        "common_stock",
        "preferred_stock",
        "reit",
    }
    if equity_like and price is not None and price > 0.0 and eps is not None:
        earnings_yield = eps / price
        factors["value"] = _factor_scored(
            score=_directional_score(earnings_yield, scale=10.0),
            raw_value=earnings_yield,
            units="earnings-yield",
            horizon_days=365,
            provider="EODHD",
            methodology_version=f"{_PUBLICATION_METHOD_VERSION}.value-earnings-yield",
            observed_at=observed_at,
            evidence_identifiers=row_evidence,
        )
    if dividend_yield is not None:
        normalized_yield = dividend_yield / 100.0 if abs(dividend_yield) > 1.0 else dividend_yield
        factors["carry"] = _factor_scored(
            score=_directional_score(normalized_yield, scale=10.0),
            raw_value=normalized_yield,
            units="annualized-distribution-yield",
            horizon_days=365,
            provider="EODHD",
            methodology_version=f"{_PUBLICATION_METHOD_VERSION}.carry-distribution-yield",
            observed_at=observed_at,
            evidence_identifiers=row_evidence,
        )

    if not factors:
        return None
    for factor in REQUIRED_PROVIDER_FACTORS:
        factors.setdefault(
            factor,
            _factor_not_applicable(
                factor=factor,
                provider="EODHD+CAPITAL_INTELLIGENCE_POLICY",
                observed_at=observed_at,
                evidence_identifiers=row_evidence,
                rationale=(
                    "The certified bulk provider snapshot does not contain an "
                    f"asset-specific {factor} measurement for this instrument; no "
                    "neutral score is substituted."
                ),
            ),
        )

    dollar_volume = (
        None
        if price is None or average_volume is None
        else max(0.0, price * average_volume)
    )
    payload: dict[str, object] = {
        "observed_at": observed_at.isoformat(),
        "eligible": True,
        "source_identifiers": list(row_evidence),
        "factors": factors,
    }
    liquidity = _liquidity_score(dollar_volume)
    if liquidity is not None:
        payload["liquidity_score"] = liquidity
    if price is not None and price > 0.0:
        payload["indicative_price"] = price
    return payload


def _exchange_bulk_signals(
    item: tuple[str, tuple[tuple[DiscoveryCatalogRecord, str], ...]],
    *,
    as_of: datetime,
    api_token: str,
    http_get: Callable[..., Any],
) -> tuple[
    str,
    tuple[tuple[str, dict[str, object]], ...],
    str | None,
    str | None,
]:
    """Collect one independent exchange while retaining deterministic publication.

    The returned payload contains only normalized signals and credential-safe failure
    detail. Raw provider rows remain local to this worker and are released before the
    result is joined, bounding memory to the worker cap instead of retaining every
    exchange snapshot at once.
    """

    exchange, members = item
    try:
        rows, observed_at, evidence_identifier = _bulk_snapshot(
            exchange,
            as_of=as_of,
            api_token=api_token,
            http_get=http_get,
        )
    except ProviderPreselectionPublicationError as error:
        return exchange, (), None, str(error)
    by_code: dict[str, Mapping[str, object]] = {}
    for row in rows:
        for key in _row_keys(row):
            by_code.setdefault(key, row)
    normalized: list[tuple[str, dict[str, object]]] = []
    for record, code in members:
        candidates = tuple(
            dict.fromkeys(
                (
                    code,
                    code.split(".", 1)[0],
                    record.provider_symbol.upper(),
                    record.provider_symbol.upper().split(".", 1)[0],
                )
            )
        )
        row = next((by_code[key] for key in candidates if key in by_code), None)
        if row is None:
            continue
        signal = _bulk_signal(
            record,
            row,
            observed_at=observed_at,
            evidence_identifier=evidence_identifier,
        )
        if signal is not None:
            normalized.append((record.symbol, signal))
    return exchange, tuple(normalized), evidence_identifier, None


def _fallback_probe_batches(
    records: Sequence[DiscoveryCatalogRecord],
    *,
    maximum_batches: int = _MAX_PROVIDER_IO_WORKERS,
) -> tuple[tuple[DiscoveryCatalogRecord, ...], ...]:
    """Partition fallback I/O without breaking provider-native batch requests."""

    ordered = tuple(records)
    if not ordered:
        return ()
    options = tuple(
        item for item in ordered if item.asset_class is CandidateAssetClass.OPTION
    )
    alpaca = tuple(
        item
        for item in ordered
        if item.asset_class is not CandidateAssetClass.OPTION
        and item.provider_kind == "alpaca"
    )
    ordinary = tuple(
        item
        for item in ordered
        if item.asset_class is not CandidateAssetClass.OPTION
        and item.provider_kind != "alpaca"
    )
    batches: list[tuple[DiscoveryCatalogRecord, ...]] = []
    if options:
        batches.append(options)
    if alpaca:
        batches.append(alpaca)
    remaining = max(1, int(maximum_batches) - len(batches))
    ordinary_batch_count = min(remaining, len(ordinary))
    if ordinary_batch_count:
        batch_size = (len(ordinary) + ordinary_batch_count - 1) // ordinary_batch_count
        batches.extend(
            ordinary[start : start + batch_size]
            for start in range(0, len(ordinary), batch_size)
        )
    return tuple(batch for batch in batches if batch)


def _feature_signal(
    record: DiscoveryCatalogRecord,
    features: DiscoveryMarketFeatures,
) -> dict[str, object]:
    evidence = tuple(
        dict.fromkeys((record.source_identifier, *features.evidence_identifiers))
    )
    raw_momentum = (
        0.15 * features.one_month_return
        + 0.20 * features.three_month_return
        + 0.25 * features.six_month_return
        + 0.40 * features.twelve_month_return
    )
    raw_improvement = (
        features.one_month_return
        - features.six_month_return / 6.0
    )
    provider = str(record.provider_kind).strip().upper() or "PROVIDER"
    factors = {
        "momentum": _factor_scored(
            score=_directional_score(raw_momentum, scale=3.0),
            raw_value=raw_momentum,
            units="weighted-total-return",
            horizon_days=252,
            provider=provider,
            methodology_version=f"{_PUBLICATION_METHOD_VERSION}.momentum-history",
            observed_at=features.observed_at,
            evidence_identifiers=evidence,
        ),
        "improving_conditions": _factor_scored(
            score=_directional_score(raw_improvement, scale=6.0),
            raw_value=raw_improvement,
            units="short-versus-medium-return-acceleration",
            horizon_days=126,
            provider=provider,
            methodology_version=(
                f"{_PUBLICATION_METHOD_VERSION}.improving-conditions-history"
            ),
            observed_at=features.observed_at,
            evidence_identifiers=evidence,
        ),
    }
    for factor in ("value", "carry"):
        factors[factor] = _factor_not_applicable(
            factor=factor,
            provider=f"{provider}+CAPITAL_INTELLIGENCE_POLICY",
            observed_at=features.observed_at,
            evidence_identifiers=evidence,
            rationale=(
                "The available certified provider history does not contain an "
                f"asset-specific {factor} measurement for this instrument; no "
                "neutral score is substituted."
            ),
        )
    return {
        "observed_at": features.observed_at.isoformat(),
        "eligible": True,
        "liquidity_score": _liquidity_score(
            features.average_daily_dollar_volume
        ),
        "quality_score": _clamp(
            0.5
            + 0.25 * min(1.0, features.history_bars / 504.0)
            + 0.25 * max(0.0, 1.0 - features.annualized_volatility)
        ),
        "indicative_price": features.price,
        "source_identifiers": list(evidence),
        "factors": factors,
    }


def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def ensure_provider_preselection_publication(
    catalogs: Mapping[CandidateAssetClass, Sequence[DiscoveryCatalogRecord]],
    *,
    as_of: datetime,
    policy: ComprehensiveMarketDiscoveryPolicy | None = None,
    http_get: Callable[..., Any] = requests.get,
    market_probe: Callable[
        [
            Sequence[DiscoveryCatalogRecord],
            datetime,
            ComprehensiveMarketDiscoveryPolicy,
        ],
        Mapping[str, DiscoveryMarketFeatures],
    ]
    | None = None,
) -> ProviderPreselectionPublicationResult:
    """Build or reuse the current provider-factor publication for complete catalogs."""

    timestamp = _aware(as_of, field_name="as_of")
    resolved = policy or ComprehensiveMarketDiscoveryPolicy()
    records = _flatten_catalogs(catalogs)
    if not records:
        raise ProviderPreselectionPublicationError(
            "provider preselection publication requires a nonempty catalog"
        )
    fingerprint = _catalog_fingerprint(records)
    path = _publication_path(resolved)
    freshness_days = int(getattr(resolved, "preselection_freshness_days", 3))
    existing = _existing_result(
        path,
        as_of=timestamp,
        fingerprint=fingerprint,
        catalog_count=len(records),
        freshness_days=freshness_days,
    )
    if existing is not None:
        return existing

    grouped: dict[str, list[tuple[DiscoveryCatalogRecord, str]]] = {}
    fallback_records: list[DiscoveryCatalogRecord] = []
    for record in records:
        identity = _source_exchange_and_code(record)
        if identity is None:
            fallback_records.append(record)
            continue
        exchange, code = identity
        grouped.setdefault(exchange, []).append((record, code))

    signals: dict[str, object] = {}
    sources: list[str] = []
    limitations: list[str] = []
    api_token = (
        os.getenv("CAPITAL_INTELLIGENCE_EODHD_API_TOKEN")
        or os.getenv("EODHD_API_TOKEN")
        or ""
    ).strip()
    if grouped and not api_token:
        limitations.append(
            "EODHD bulk factor publication was not attempted because its API token "
            "is unavailable."
        )
    if api_token:
        exchange_groups = tuple(
            (exchange, tuple(members))
            for exchange, members in sorted(grouped.items())
        )
        record_manual_cio_diagnostic_progress(
            "provider_preselection_bulk_snapshots",
            metrics={"configured_exchanges": len(exchange_groups)},
        )

        def collect_exchange(
            item: tuple[str, tuple[tuple[DiscoveryCatalogRecord, str], ...]],
        ) -> tuple[
            str,
            tuple[tuple[str, dict[str, object]], ...],
            str | None,
            str | None,
        ]:
            return _exchange_bulk_signals(
                item,
                as_of=timestamp,
                api_token=api_token,
                http_get=http_get,
            )

        if len(exchange_groups) > 1:
            with ThreadPoolExecutor(
                max_workers=min(_MAX_PROVIDER_IO_WORKERS, len(exchange_groups)),
                thread_name_prefix="provider-preselection-bulk",
            ) as executor:
                exchange_results = tuple(
                    executor.map(collect_exchange, exchange_groups)
                )
        else:
            exchange_results = tuple(map(collect_exchange, exchange_groups))
        for _exchange, normalized, evidence_identifier, error_detail in exchange_results:
            if error_detail is not None:
                limitations.append(error_detail)
                continue
            if evidence_identifier is not None:
                sources.append(evidence_identifier)
            for symbol, signal in normalized:
                signals[symbol] = signal
        record_manual_cio_diagnostic_progress(
            "provider_preselection_bulk_snapshots_complete",
            metrics={"evidence_complete_records": len(signals)},
        )

    probe_records = tuple(
        item for item in fallback_records if item.symbol not in signals
    )
    if probe_records:
        record_manual_cio_diagnostic_progress(
            "provider_preselection_fallback_probe",
            metrics={"catalog_records": len(probe_records)},
        )
        try:
            if market_probe is not None:
                features = market_probe(probe_records, timestamp, resolved)
            else:
                batches = _fallback_probe_batches(probe_records)

                def collect_batch(
                    batch: tuple[DiscoveryCatalogRecord, ...],
                ) -> Mapping[str, DiscoveryMarketFeatures]:
                    return default_market_probe(batch, timestamp, resolved)

                if len(batches) > 1:
                    with ThreadPoolExecutor(
                        max_workers=min(_MAX_PROVIDER_IO_WORKERS, len(batches)),
                        thread_name_prefix="provider-preselection-fallback",
                    ) as executor:
                        partial_features = tuple(executor.map(collect_batch, batches))
                else:
                    partial_features = tuple(map(collect_batch, batches))
                features = {}
                for record in probe_records:
                    for partial in partial_features:
                        if record.symbol in partial:
                            features[record.symbol] = partial[record.symbol]
                            break
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            limitations.append(
                "provider-native derivative/alternate factor probe failed: "
                f"{type(error).__name__}"
            )
            features = {}
        record_manual_cio_diagnostic_progress(
            "provider_preselection_fallback_probe_complete",
            metrics={"evidence_complete_records": len(features)},
        )
        for record in probe_records:
            item = features.get(record.symbol)
            if item is None:
                continue
            signals[record.symbol] = _feature_signal(record, item)
            sources.extend(item.evidence_identifiers)

    if not signals:
        raise ProviderPreselectionPublicationError(
            "no substantive provider factor signal could be produced for any "
            "certified market catalog record"
        )

    # The provider observations are at or before the decision cutoff. Retrieval may
    # finish seconds later, so publication availability is clamped to the existing live
    # query grace used by the canonical provider adapters instead of being future-known.
    available_at = timestamp
    source_identifiers = tuple(
        dict.fromkeys(
            (
                f"provider-preselection-runtime:{_PUBLICATION_METHOD_VERSION}:"
                f"{fingerprint}",
                *sources,
            )
        )
    )
    payload: dict[str, object] = {
        "schema_version": PROVIDER_PRESELECTION_SCHEMA,
        "methodology_version": _PUBLICATION_METHOD_VERSION,
        "available_at": available_at.isoformat(),
        "catalog_fingerprint": fingerprint,
        "catalog_count": len(records),
        "signal_count": len(signals),
        "source_identifiers": list(source_identifiers),
        "limitations": list(dict.fromkeys(limitations)),
        "signals": signals,
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }
    _atomic_write(path, payload)
    return ProviderPreselectionPublicationResult(
        path=path,
        available_at=available_at,
        catalog_count=len(records),
        signal_count=len(signals),
        reused=False,
        source_identifiers=source_identifiers,
        limitations=tuple(dict.fromkeys(limitations)),
    )


__all__ = [
    "ProviderPreselectionPublicationError",
    "ProviderPreselectionPublicationResult",
    "ensure_provider_preselection_publication",
]
