"""Persistent option-contract reference readiness without reusing decision evidence.

Option identity is slow-changing relative to a CIO cycle, while option bars, volume,
liquidity, and the underlying price used for selection are decision-time evidence. This
module prewarms a deliberately wider Alpaca contract-definition envelope before the
bounded CIO child starts and lets the existing resumable provider reuse that envelope
only when it provably contains the current requested strike and expiration scope.

Historical option bars remain exact-epoch checkpoints in ``resumable_options_discovery``.
No price, bar, volume, ranking, threshold, or execution evidence is persisted here.
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Mapping, MutableMapping, Sequence

from cio import CandidateAssetClass
from operations.generalized_reference_readiness import (
    load_asset_reference_component,
    store_asset_reference_component,
)
from operations.resumable_options_discovery import (
    ResumableOptionsProvider,
    _adapt_primary_definition,
    _definition_from_payload,
    _definition_payload,
)
from operations import reference_readiness as _reference
from providers.alpaca_indicative_options import AlpacaIndicativeOptionsProvider
from providers.alpaca_paper import (
    AlpacaPaperClient,
    AlpacaPaperProviderError,
    create_alpaca_paper_client,
)
from providers.redundant_options import RedundantOptionDefinition


_REFERENCE_SCOPE_PREFIX = "contract-definitions"
_REFERENCE_MONEYNESS_LIMIT = 0.35
_EXPIRATION_BUFFER_DAYS = 7
_PRICE_HISTORY_DAYS = 15
_MAX_PREWARM_WORKERS = 4


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _scope(underlying: str) -> str:
    return f"{_REFERENCE_SCOPE_PREFIX}-{str(underlying).strip().upper()}"


def _reference_config_fingerprint(
    *,
    underlying: str,
    maximum_days_to_expiry: int,
) -> str:
    return _reference._fingerprint(
        {
            "asset_class": CandidateAssetClass.OPTION.value,
            "underlying": str(underlying).strip().upper(),
            "reference_moneyness_limit": _REFERENCE_MONEYNESS_LIMIT,
            "reference_minimum_days_to_expiry": 1,
            "reference_maximum_days_to_expiry": maximum_days_to_expiry,
        }
    )


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _positive(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result > 0.0 else None


def _latest_underlying_prices(
    client: AlpacaPaperClient,
    underlyings: Sequence[str],
    *,
    as_of: datetime,
) -> Mapping[str, float]:
    histories = client.historical_bars(
        underlyings,
        start=as_of - timedelta(days=_PRICE_HISTORY_DAYS),
        end=as_of,
        timeframe="1Day",
    )
    result: dict[str, float] = {}
    for underlying in underlyings:
        latest_at: datetime | None = None
        latest_price: float | None = None
        for raw in histories.get(underlying, ()):
            if not isinstance(raw, Mapping):
                continue
            observed = _timestamp(raw.get("t"))
            close = _positive(raw.get("c"))
            if observed is None or close is None or observed > as_of:
                continue
            if latest_at is None or observed > latest_at:
                latest_at = observed
                latest_price = close
        if latest_price is not None:
            result[underlying] = latest_price
    return result


def _metadata_dates(
    *,
    as_of: datetime,
    maximum_days_to_expiry: int,
) -> tuple[date, date]:
    return (
        (as_of + timedelta(days=1)).date(),
        (as_of + timedelta(days=maximum_days_to_expiry + 1)).date(),
    )


def _component_covers_request(
    payload: Mapping[str, object],
    *,
    underlying_price: float,
    as_of: datetime,
    minimum_days_to_expiry: int,
    maximum_days_to_expiry: int,
    desired_moneyness_limit: float,
) -> bool:
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        return False
    try:
        strike_lower = float(metadata["strike_lower"])
        strike_upper = float(metadata["strike_upper"])
        expiration_gte = date.fromisoformat(str(metadata["expiration_gte"]))
        expiration_lte = date.fromisoformat(str(metadata["expiration_lte"]))
    except (KeyError, TypeError, ValueError):
        return False
    desired_lower = underlying_price * (1.0 - desired_moneyness_limit)
    desired_upper = underlying_price * (1.0 + desired_moneyness_limit)
    if desired_lower < strike_lower - 1e-9 or desired_upper > strike_upper + 1e-9:
        return False
    requested_gte = (as_of + timedelta(days=minimum_days_to_expiry)).date()
    requested_lte = (as_of + timedelta(days=maximum_days_to_expiry + 1)).date()
    return expiration_gte <= requested_gte and expiration_lte >= requested_lte


def _definitions_from_component(
    payload: Mapping[str, object],
    *,
    underlying_price: float,
    as_of: datetime,
    minimum_days_to_expiry: int,
    maximum_days_to_expiry: int,
    desired_moneyness_limit: float,
) -> tuple[RedundantOptionDefinition, ...] | None:
    if not _component_covers_request(
        payload,
        underlying_price=underlying_price,
        as_of=as_of,
        minimum_days_to_expiry=minimum_days_to_expiry,
        maximum_days_to_expiry=maximum_days_to_expiry,
        desired_moneyness_limit=desired_moneyness_limit,
    ):
        return None
    raw_records = payload.get("records")
    if not isinstance(raw_records, Sequence) or isinstance(raw_records, (str, bytes)):
        return None
    definitions: list[RedundantOptionDefinition] = []
    for raw in raw_records:
        if not isinstance(raw, Mapping):
            return None
        try:
            definition = _definition_from_payload(raw)
        except (KeyError, TypeError, ValueError):
            return None
        days = (definition.expiration_at - as_of).days
        if not minimum_days_to_expiry <= days <= maximum_days_to_expiry:
            continue
        if definition.strike <= 0.0:
            continue
        if abs(definition.strike / underlying_price - 1.0) > desired_moneyness_limit:
            continue
        definitions.append(definition)
    definitions.sort(
        key=lambda item: (
            item.expiration_at,
            item.option_right,
            item.strike,
            item.symbol,
        )
    )
    return tuple(definitions)


def _load_reusable_definitions(
    values: Mapping[str, str],
    *,
    underlying: str,
    underlying_price: float,
    as_of: datetime,
    minimum_days_to_expiry: int,
    maximum_days_to_expiry: int,
    desired_moneyness_limit: float,
) -> tuple[RedundantOptionDefinition, ...] | None:
    normalized = str(underlying).strip().upper()
    payload = load_asset_reference_component(
        values,
        asset_class=CandidateAssetClass.OPTION,
        as_of=as_of,
        scope=_scope(normalized),
        coverage=(normalized,),
    )
    if payload is None:
        return None
    return _definitions_from_component(
        payload,
        underlying_price=underlying_price,
        as_of=as_of,
        minimum_days_to_expiry=minimum_days_to_expiry,
        maximum_days_to_expiry=maximum_days_to_expiry,
        desired_moneyness_limit=desired_moneyness_limit,
    )


def prewarm_option_reference_definitions(
    values: MutableMapping[str, str],
    *,
    as_of: datetime,
    config,
    policy,
    force_refresh: bool = False,
    quote_client: AlpacaPaperClient | None = None,
    option_provider: AlpacaIndicativeOptionsProvider | None = None,
) -> Mapping[str, int]:
    """Prewarm wider option-definition envelopes before the bounded CIO clock."""

    timestamp = _aware(as_of, field_name="as_of")
    underlyings = tuple(
        dict.fromkeys(
            str(item).strip().upper()
            for item in config.option_underlyings
            if str(item).strip()
        )
    )
    if not underlyings:
        return {"configured_underlyings": 0, "ready_underlyings": 0, "reused_underlyings": 0}
    try:
        client = quote_client or create_alpaca_paper_client()
        prices = _latest_underlying_prices(client, underlyings, as_of=timestamp)
    except (AlpacaPaperProviderError, OSError, TypeError, ValueError):
        return {
            "configured_underlyings": len(underlyings),
            "ready_underlyings": 0,
            "reused_underlyings": 0,
        }

    desired_limit = 0.20
    reference_maximum_days = int(policy.option_maximum_days_to_expiry) + _EXPIRATION_BUFFER_DAYS
    ready = 0
    reused = 0
    missing: list[tuple[str, float]] = []
    for underlying in underlyings:
        price = prices.get(underlying)
        if price is None:
            continue
        if not force_refresh:
            cached = _load_reusable_definitions(
                values,
                underlying=underlying,
                underlying_price=price,
                as_of=timestamp,
                minimum_days_to_expiry=int(policy.option_minimum_days_to_expiry),
                maximum_days_to_expiry=int(policy.option_maximum_days_to_expiry),
                desired_moneyness_limit=desired_limit,
            )
            if cached is not None:
                ready += 1
                reused += 1
                continue
        missing.append((underlying, price))

    if missing:
        provider = option_provider or AlpacaIndicativeOptionsProvider(
            moneyness_limit=_REFERENCE_MONEYNESS_LIMIT
        )
        if provider.configured:
            def collect(item: tuple[str, float]) -> bool:
                underlying, price = item
                raw = provider.definitions(
                    underlying,
                    underlying_price=price,
                    as_of=timestamp,
                    minimum_days_to_expiry=1,
                    maximum_days_to_expiry=reference_maximum_days,
                )
                definitions = tuple(_adapt_primary_definition(definition) for definition in raw)
                if not definitions:
                    return False
                expiration_gte, expiration_lte = _metadata_dates(
                    as_of=timestamp,
                    maximum_days_to_expiry=reference_maximum_days,
                )
                store_asset_reference_component(
                    values,
                    asset_class=CandidateAssetClass.OPTION,
                    scope=_scope(underlying),
                    captured_at=timestamp,
                    config_fingerprint=_reference_config_fingerprint(
                        underlying=underlying,
                        maximum_days_to_expiry=reference_maximum_days,
                    ),
                    coverage=(underlying,),
                    records=tuple(_definition_payload(definition) for definition in definitions),
                    metadata={
                        "collector": "alpaca_indicative_option_chain",
                        "reference_only": True,
                        "anchor_price": price,
                        "reference_moneyness_limit": _REFERENCE_MONEYNESS_LIMIT,
                        "strike_lower": price * (1.0 - _REFERENCE_MONEYNESS_LIMIT),
                        "strike_upper": price * (1.0 + _REFERENCE_MONEYNESS_LIMIT),
                        "expiration_gte": expiration_gte.isoformat(),
                        "expiration_lte": expiration_lte.isoformat(),
                    },
                )
                return True

            worker_count = min(_MAX_PREWARM_WORKERS, len(missing))
            try:
                with ThreadPoolExecutor(
                    max_workers=worker_count,
                    thread_name_prefix="option-reference",
                ) as executor:
                    outcomes = tuple(executor.map(collect, missing))
                ready += sum(1 for outcome in outcomes if outcome)
            except (OSError, TypeError, ValueError, RuntimeError):
                # Existing independently qualified components remain available. A live
                # prewarm failure never replaces the exact-epoch router's fail-closed
                # provider behavior inside the CIO cycle.
                pass

    return {
        "configured_underlyings": len(underlyings),
        "ready_underlyings": ready,
        "reused_underlyings": reused,
    }


class PersistentReferenceOptionsProvider(ResumableOptionsProvider):
    """Resumable provider that prefers a complete fresh definition reference envelope."""

    persistent_option_reference = True

    def _definitions(
        self,
        *,
        underlying: str,
        underlying_price: float,
        as_of: datetime,
        minimum_days_to_expiry: int,
        maximum_days_to_expiry: int,
        request: Mapping[str, object],
        directory,
    ) -> tuple[RedundantOptionDefinition, ...]:
        desired_moneyness = float(
            getattr(getattr(self.delegate, "primary", None), "_moneyness_limit", 0.20)
        )
        if not math.isfinite(desired_moneyness) or not 0.0 < desired_moneyness <= 1.0:
            desired_moneyness = 0.20
        reusable = _load_reusable_definitions(
            self._values,
            underlying=underlying,
            underlying_price=underlying_price,
            as_of=as_of,
            minimum_days_to_expiry=minimum_days_to_expiry,
            maximum_days_to_expiry=maximum_days_to_expiry,
            desired_moneyness_limit=desired_moneyness,
        )
        if reusable is not None:
            return reusable
        return super()._definitions(
            underlying=underlying,
            underlying_price=underlying_price,
            as_of=as_of,
            minimum_days_to_expiry=minimum_days_to_expiry,
            maximum_days_to_expiry=maximum_days_to_expiry,
            request=request,
            directory=directory,
        )


def install_persistent_option_reference(core_module) -> None:
    """Inject reusable definitions ahead of the exact-epoch option-history provider."""

    catalog_module = core_module._base
    current = catalog_module.default_catalog_probe
    if bool(getattr(current, "persistent_option_reference", False)):
        return

    def reference_ready_default_catalog_probe(as_of, **kwargs):
        if kwargs.get("databento_options_provider") is None:
            kwargs["databento_options_provider"] = PersistentReferenceOptionsProvider()
        return current(as_of, **kwargs)

    reference_ready_default_catalog_probe.persistent_option_reference = True
    reference_ready_default_catalog_probe.__name__ = current.__name__
    catalog_module.default_catalog_probe = reference_ready_default_catalog_probe


__all__ = [
    "PersistentReferenceOptionsProvider",
    "install_persistent_option_reference",
    "prewarm_option_reference_definitions",
]
