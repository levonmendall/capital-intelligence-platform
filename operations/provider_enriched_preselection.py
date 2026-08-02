"""Fail-closed provider-enriched factor inputs for market preselection.

The merit-sleeve selector must not manufacture value, momentum, carry, or
improving-condition scores from catalog ordering or metadata. The canonical runtime
therefore consumes point-in-time provider evidence for every factor that is applicable
to an instrument. A provider may explicitly mark a factor not applicable only with a
governed rationale, methodology, timestamp, and immutable evidence lineage. Missing,
stale, future-known, unprovenanced, or silently omitted factors make the affected
instrument ineligible; they never create a neutral or synthetic score.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from operations.market_discovery_preselection import (
    CatalogScreeningSignal,
    default_catalog_screening_signals,
)


PROVIDER_PRESELECTION_SCHEMA = "capital-intelligence-provider-preselection.v1"
DEFAULT_PROVIDER_PRESELECTION_PATH = Path(
    "database/provider-enriched-preselection.json"
)
REQUIRED_PROVIDER_FACTORS = (
    "value",
    "momentum",
    "carry",
    "improving_conditions",
)
_SCORE_FIELD_BY_FACTOR = {
    "value": "value_score",
    "momentum": "momentum_score",
    "carry": "carry_score",
    "improving_conditions": "improving_conditions_score",
}
_FACTOR_APPLICABILITY_SCORED = "scored"
_FACTOR_APPLICABILITY_NOT_APPLICABLE = "not_applicable"


class ProviderEnrichedPreselectionError(RuntimeError):
    """Raised when a provider factor publication is structurally invalid."""


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _timestamp(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ProviderEnrichedPreselectionError(f"{field_name} is required")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise ProviderEnrichedPreselectionError(
            f"{field_name} must be an ISO-8601 timestamp"
        ) from error
    return _aware(parsed, field_name=field_name)


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderEnrichedPreselectionError(f"{field_name} is required")
    return value.strip()


def _score(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderEnrichedPreselectionError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ProviderEnrichedPreselectionError(
            f"{field_name} must be finite and between 0 and 1"
        )
    return round(result, 10)


def _raw_value(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderEnrichedPreselectionError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ProviderEnrichedPreselectionError(f"{field_name} must be finite")
    return result


def _positive_integer(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProviderEnrichedPreselectionError(
            f"{field_name} must be a positive integer"
        )
    return value


def _string_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ProviderEnrichedPreselectionError(f"{field_name} must be a sequence")
    result = tuple(
        dict.fromkeys(str(item).strip() for item in value if str(item).strip())
    )
    if not result:
        raise ProviderEnrichedPreselectionError(f"{field_name} cannot be empty")
    return result


def _path(policy: object | None) -> Path:
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


def _required_factors(policy: object | None) -> tuple[str, ...]:
    value = (
        REQUIRED_PROVIDER_FACTORS
        if policy is None
        else tuple(
            getattr(
                policy,
                "required_provider_preselection_factors",
                REQUIRED_PROVIDER_FACTORS,
            )
        )
    )
    if not value or len(set(value)) != len(value):
        raise ProviderEnrichedPreselectionError(
            "required provider preselection factors must be unique and non-empty"
        )
    unsupported = tuple(item for item in value if item not in _SCORE_FIELD_BY_FACTOR)
    if unsupported:
        raise ProviderEnrichedPreselectionError(
            "unsupported provider preselection factors: " + ", ".join(unsupported)
        )
    return value


def _factor_identifier(
    *,
    factor: str,
    provider: str,
    methodology_version: str,
    payload: Mapping[str, object],
    applicability: str = _FACTOR_APPLICABILITY_SCORED,
) -> str:
    digest = hashlib.sha256(
        json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    prefix = (
        "provider-factor-not-applicable"
        if applicability == _FACTOR_APPLICABILITY_NOT_APPLICABLE
        else "provider-factor"
    )
    return f"{prefix}:{factor}:{provider.lower()}:{methodology_version}:{digest}"


def _load(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ProviderEnrichedPreselectionError(
            f"provider preselection publication is unavailable at {path}"
        ) from error
    except json.JSONDecodeError as error:
        raise ProviderEnrichedPreselectionError(
            "provider preselection publication is not valid JSON"
        ) from error
    if not isinstance(payload, Mapping):
        raise ProviderEnrichedPreselectionError(
            "provider preselection publication must be a JSON object"
        )
    return payload


def _unavailable(
    signal: CatalogScreeningSignal,
    *reasons: str,
) -> CatalogScreeningSignal:
    return replace(
        signal,
        eligible=False,
        exclusion_reasons=tuple(
            dict.fromkeys((*signal.exclusion_reasons, *reasons))
        ),
    )


def validate_provider_enriched_signals(
    records: Sequence[object],
    signals: Mapping[str, CatalogScreeningSignal],
    *,
    required_factors: Sequence[str] = REQUIRED_PROVIDER_FACTORS,
) -> Mapping[str, CatalogScreeningSignal]:
    """Require scored or explicitly-not-applicable evidence for every factor.

    The required factor set is a governance coverage set, not a demand that every
    instrument receive every score. Each factor must either contain a substantive score
    with provider lineage or a provider-certified ``not_applicable`` determination. At
    least one substantive factor must be scored for every new opportunity.
    """

    normalized = {
        str(symbol).strip().upper(): signal for symbol, signal in signals.items()
    }
    baseline = default_catalog_screening_signals(records, datetime.now(timezone.utc))
    result: dict[str, CatalogScreeningSignal] = {}
    for record in records:
        symbol = str(getattr(record, "symbol", "")).strip().upper()
        signal = normalized.get(symbol)
        if signal is None:
            result[symbol] = _unavailable(
                baseline[symbol],
                "provider_enriched_preselection_signal_unavailable",
            )
            continue
        reasons: list[str] = []
        substantive_count = 0
        for factor in required_factors:
            field_name = _SCORE_FIELD_BY_FACTOR.get(str(factor))
            if field_name is None:
                raise ProviderEnrichedPreselectionError(
                    f"unsupported provider factor {factor!r}"
                )
            value = getattr(signal, field_name)
            scored_prefix = f"provider-factor:{factor}:"
            not_applicable_prefix = f"provider-factor-not-applicable:{factor}:"
            scored_lineage = any(
                identifier.startswith(scored_prefix)
                for identifier in signal.evidence_identifiers
            )
            not_applicable_lineage = any(
                identifier.startswith(not_applicable_prefix)
                for identifier in signal.evidence_identifiers
            )
            if value is not None:
                substantive_count += 1
                if not scored_lineage:
                    reasons.append(f"provider_factor_{factor}_unprovenanced")
                if not_applicable_lineage:
                    reasons.append(f"provider_factor_{factor}_applicability_conflict")
            elif not not_applicable_lineage:
                reasons.append(f"provider_factor_{factor}_unavailable")
        if substantive_count < 1:
            reasons.append("provider_substantive_factor_set_empty")
        result[symbol] = signal if not reasons else _unavailable(signal, *reasons)
    return result


def provider_enriched_catalog_screening_signals(
    records: Sequence[object],
    as_of: datetime,
    policy: object | None = None,
) -> Mapping[str, CatalogScreeningSignal]:
    """Load and validate the canonical point-in-time provider factor publication."""

    timestamp = _aware(as_of, field_name="as_of")
    baseline = default_catalog_screening_signals(records, timestamp, policy)
    required = _required_factors(policy)
    try:
        payload = _load(_path(policy))
        if payload.get("schema_version") != PROVIDER_PRESELECTION_SCHEMA:
            raise ProviderEnrichedPreselectionError(
                "unsupported provider preselection schema"
            )
        available_at = _timestamp(
            payload.get("available_at"), field_name="available_at"
        )
        if available_at > timestamp:
            raise ProviderEnrichedPreselectionError(
                "provider preselection publication is future-known"
            )
        freshness_days = int(
            getattr(policy, "preselection_freshness_days", 3)
            if policy is not None
            else 3
        )
        if (timestamp - available_at).total_seconds() > freshness_days * 86_400:
            raise ProviderEnrichedPreselectionError(
                "provider preselection publication is stale"
            )
        publication_sources = _string_tuple(
            payload.get("source_identifiers", ()),
            field_name="source_identifiers",
        )
        published_signals = payload.get("signals")
        if not isinstance(published_signals, Mapping):
            raise ProviderEnrichedPreselectionError(
                "provider preselection signals must be a symbol mapping"
            )
        normalized_publication = {
            str(symbol).strip().upper(): value
            for symbol, value in published_signals.items()
        }
    except (ProviderEnrichedPreselectionError, TypeError, ValueError) as error:
        reason = (
            "provider_enriched_preselection_publication_invalid:"
            f"{type(error).__name__}"
        )
        return {
            symbol: _unavailable(signal, reason)
            for symbol, signal in baseline.items()
        }

    result: dict[str, CatalogScreeningSignal] = {}
    for record in records:
        symbol = str(getattr(record, "symbol", "")).strip().upper()
        provider_symbol = str(
            getattr(record, "provider_symbol", symbol)
        ).strip().upper()
        base = baseline[symbol]
        raw = normalized_publication.get(symbol) or normalized_publication.get(
            provider_symbol
        )
        if not isinstance(raw, Mapping):
            result[symbol] = _unavailable(
                base,
                "provider_enriched_preselection_signal_unavailable",
            )
            continue

        errors: list[str] = []
        factor_scores: dict[str, float | None] = {
            factor: None for factor in required
        }
        factor_observed: list[datetime] = []
        evidence_identifiers = list(base.evidence_identifiers)
        evidence_identifiers.extend(publication_sources)
        raw_sources = raw.get("source_identifiers", ())
        if raw_sources:
            try:
                evidence_identifiers.extend(
                    _string_tuple(
                        raw_sources,
                        field_name=f"signals.{symbol}.source_identifiers",
                    )
                )
            except ProviderEnrichedPreselectionError:
                errors.append("provider_signal_source_lineage_invalid")
        try:
            signal_observed_at = _timestamp(
                raw.get("observed_at"),
                field_name=f"signals.{symbol}.observed_at",
            )
            if signal_observed_at > available_at or signal_observed_at > timestamp:
                raise ProviderEnrichedPreselectionError(
                    "signal observation is future-known"
                )
        except ProviderEnrichedPreselectionError:
            signal_observed_at = available_at
            errors.append("provider_signal_observed_at_invalid")

        factors = raw.get("factors")
        if not isinstance(factors, Mapping):
            factors = {}
            errors.append("provider_factor_payload_unavailable")
        for factor in required:
            block = factors.get(factor)
            if not isinstance(block, Mapping):
                errors.append(f"provider_factor_{factor}_unavailable")
                continue
            applicability = str(
                block.get("applicability", _FACTOR_APPLICABILITY_SCORED)
            ).strip().lower()
            try:
                provider = _text(
                    block.get("provider"),
                    field_name=f"signals.{symbol}.factors.{factor}.provider",
                )
                methodology = _text(
                    block.get("methodology_version"),
                    field_name=(
                        f"signals.{symbol}.factors.{factor}.methodology_version"
                    ),
                )
                observed_at = _timestamp(
                    block.get("observed_at"),
                    field_name=f"signals.{symbol}.factors.{factor}.observed_at",
                )
                if observed_at > available_at or observed_at > timestamp:
                    raise ProviderEnrichedPreselectionError(
                        "factor observation is future-known"
                    )
                source_identifiers = _string_tuple(
                    block.get("evidence_identifiers", ()),
                    field_name=(
                        f"signals.{symbol}.factors.{factor}.evidence_identifiers"
                    ),
                )
                if applicability == _FACTOR_APPLICABILITY_NOT_APPLICABLE:
                    _text(
                        block.get("rationale"),
                        field_name=(
                            f"signals.{symbol}.factors.{factor}.rationale"
                        ),
                    )
                    if block.get("score") is not None:
                        raise ProviderEnrichedPreselectionError(
                            "not-applicable factors cannot carry a score"
                        )
                    score = None
                elif applicability == _FACTOR_APPLICABILITY_SCORED:
                    score = _score(
                        block.get("score"),
                        field_name=f"signals.{symbol}.factors.{factor}.score",
                    )
                    _raw_value(
                        block.get("raw_value"),
                        field_name=f"signals.{symbol}.factors.{factor}.raw_value",
                    )
                    _text(
                        block.get("units"),
                        field_name=f"signals.{symbol}.factors.{factor}.units",
                    )
                    _positive_integer(
                        block.get("horizon_days"),
                        field_name=(
                            f"signals.{symbol}.factors.{factor}.horizon_days"
                        ),
                    )
                else:
                    raise ProviderEnrichedPreselectionError(
                        "factor applicability must be scored or not_applicable"
                    )
            except ProviderEnrichedPreselectionError:
                errors.append(f"provider_factor_{factor}_invalid")
                continue
            factor_scores[factor] = score
            factor_observed.append(observed_at)
            evidence_identifiers.extend(source_identifiers)
            evidence_identifiers.append(
                _factor_identifier(
                    factor=factor,
                    provider=provider,
                    methodology_version=methodology,
                    payload=block,
                    applicability=applicability,
                )
            )

        try:
            liquidity_score = (
                base.liquidity_score
                if raw.get("liquidity_score") is None
                else min(
                    float(base.liquidity_score or 0.0),
                    _score(
                        raw.get("liquidity_score"),
                        field_name=f"signals.{symbol}.liquidity_score",
                    ),
                )
            )
            quality_score = (
                base.quality_score
                if raw.get("quality_score") is None
                else _score(
                    raw.get("quality_score"),
                    field_name=f"signals.{symbol}.quality_score",
                )
            )
            indicative_price = raw.get("indicative_price")
            if indicative_price is not None:
                indicative_price = _raw_value(
                    indicative_price,
                    field_name=f"signals.{symbol}.indicative_price",
                )
                if indicative_price <= 0.0:
                    raise ProviderEnrichedPreselectionError(
                        "indicative price must be positive"
                    )
        except ProviderEnrichedPreselectionError:
            liquidity_score = base.liquidity_score
            quality_score = base.quality_score
            indicative_price = base.indicative_price
            errors.append("provider_signal_summary_invalid")

        observed_at = min(
            (signal_observed_at, *factor_observed)
            if factor_observed
            else (signal_observed_at,)
        )
        signal = CatalogScreeningSignal(
            symbol=symbol,
            observed_at=observed_at,
            eligible=bool(raw.get("eligible", True)) and base.eligible and not errors,
            liquidity_score=liquidity_score,
            quality_score=quality_score,
            value_score=factor_scores.get("value"),
            momentum_score=factor_scores.get("momentum"),
            carry_score=factor_scores.get("carry"),
            improving_conditions_score=factor_scores.get(
                "improving_conditions"
            ),
            indicative_price=indicative_price,
            evidence_identifiers=tuple(dict.fromkeys(evidence_identifiers)),
            exclusion_reasons=tuple(
                dict.fromkeys((*base.exclusion_reasons, *errors))
            ),
        )
        result[symbol] = signal

    return validate_provider_enriched_signals(
        records,
        result,
        required_factors=required,
    )


__all__ = [
    "DEFAULT_PROVIDER_PRESELECTION_PATH",
    "PROVIDER_PRESELECTION_SCHEMA",
    "ProviderEnrichedPreselectionError",
    "REQUIRED_PROVIDER_FACTORS",
    "provider_enriched_catalog_screening_signals",
    "validate_provider_enriched_signals",
]
