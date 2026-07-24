"""Canonical immutable inputs for portfolio-fit governance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite


class AssetBucket(str, Enum):
    """Top-level portfolio exposure buckets."""

    EQUITY = "equity"
    FIXED_INCOME = "fixed_income"
    CASH = "cash"
    COMMODITY = "commodity"
    FX = "fx"
    CRYPTO = "crypto"
    ALTERNATIVE = "alternative"


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware_datetime(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _ratio(
    value: object,
    *,
    field_name: str,
) -> float:
    if isinstance(value, bool) or not isinstance(
        value,
        (int, float),
    ):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized) or not 0.0 <= normalized <= 1.0:
        raise ValueError(
            f"{field_name} must be between 0.0 and 1.0"
        )
    return round(normalized, 6)


def _text_tuple(
    value: object,
    *,
    field_name: str,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    normalized = tuple(
        _required_text(item, field_name=field_name)
        for item in value
    )
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return normalized


@dataclass(frozen=True, slots=True)
class AssetBucketLimit:
    """Maximum mandate weight for one asset bucket."""

    bucket: AssetBucket
    maximum_weight: float

    def __post_init__(self) -> None:
        if not isinstance(self.bucket, AssetBucket):
            raise TypeError("bucket must be an AssetBucket")
        object.__setattr__(
            self,
            "maximum_weight",
            _ratio(
                self.maximum_weight,
                field_name="maximum_weight",
            ),
        )


@dataclass(frozen=True, slots=True)
class PortfolioPosition:
    """One current exposure used by the fit gate."""

    identifier: str
    bucket: AssetBucket
    weight: float
    risk_budget_usage: float
    liquidity_score: float
    exposure_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identifier",
            _required_text(
                self.identifier,
                field_name="identifier",
            ),
        )
        if not isinstance(self.bucket, AssetBucket):
            raise TypeError("bucket must be an AssetBucket")
        if self.bucket is AssetBucket.CASH:
            raise ValueError(
                "cash belongs in PortfolioSnapshot.cash_weight"
            )
        for field_name in (
            "weight",
            "risk_budget_usage",
            "liquidity_score",
        ):
            object.__setattr__(
                self,
                field_name,
                _ratio(
                    getattr(self, field_name),
                    field_name=field_name,
                ),
            )
        object.__setattr__(
            self,
            "exposure_tags",
            _text_tuple(
                self.exposure_tags,
                field_name="exposure_tags",
            ),
        )


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    """Complete point-in-time weights and risk use for one portfolio."""

    identifier: str
    as_of: datetime
    nav: float
    cash_weight: float
    risk_budget_used: float
    positions: tuple[PortfolioPosition, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identifier",
            _required_text(
                self.identifier,
                field_name="identifier",
            ),
        )
        _aware_datetime(self.as_of, field_name="as_of")
        if isinstance(self.nav, bool) or not isinstance(
            self.nav,
            (int, float),
        ):
            raise TypeError("nav must be numeric")
        nav = float(self.nav)
        if not isfinite(nav) or nav <= 0:
            raise ValueError("nav must be positive and finite")
        object.__setattr__(self, "nav", round(nav, 2))
        for field_name in ("cash_weight", "risk_budget_used"):
            object.__setattr__(
                self,
                field_name,
                _ratio(
                    getattr(self, field_name),
                    field_name=field_name,
                ),
            )
        if not isinstance(self.positions, tuple) or not all(
            isinstance(item, PortfolioPosition)
            for item in self.positions
        ):
            raise TypeError(
                "positions must contain PortfolioPosition values"
            )
        identifiers = [
            position.identifier for position in self.positions
        ]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(
                "position identifiers must be unique"
            )
        total_weight = self.cash_weight + sum(
            position.weight for position in self.positions
        )
        if abs(total_weight - 1.0) > 0.0001:
            raise ValueError(
                "position weights and cash_weight must sum to 1.0"
            )

    def position_weight(self, identifier: str) -> float:
        """Return current weight for one instrument or exposure."""

        normalized = _required_text(
            identifier,
            field_name="identifier",
        )
        return next(
            (
                position.weight
                for position in self.positions
                if position.identifier == normalized
            ),
            0.0,
        )

    def bucket_weight(self, bucket: AssetBucket) -> float:
        """Return current total weight for one asset bucket."""

        if not isinstance(bucket, AssetBucket):
            raise TypeError("bucket must be an AssetBucket")
        if bucket is AssetBucket.CASH:
            return self.cash_weight
        return round(
            sum(
                position.weight
                for position in self.positions
                if position.bucket is bucket
            ),
            6,
        )

    def overlapping_positions(
        self,
        exposure_tags: tuple[str, ...],
    ) -> tuple[PortfolioPosition, ...]:
        """Return positions sharing at least one proposal exposure tag."""

        tags = set(
            _text_tuple(
                exposure_tags,
                field_name="exposure_tags",
            )
        )
        if not tags:
            return ()
        return tuple(
            position
            for position in self.positions
            if tags.intersection(position.exposure_tags)
        )


@dataclass(frozen=True, slots=True)
class PortfolioMandate:
    """Versioned constraints governing portfolio expression."""

    identifier: str
    version: str
    maximum_position_weight: float
    minimum_cash_weight: float
    maximum_risk_budget: float
    minimum_liquidity_score: float
    bucket_limits: tuple[AssetBucketLimit, ...]
    prohibited_identifiers: tuple[str, ...] = ()
    prohibited_exposure_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("identifier", "version"):
            object.__setattr__(
                self,
                field_name,
                _required_text(
                    getattr(self, field_name),
                    field_name=field_name,
                ),
            )
        for field_name in (
            "maximum_position_weight",
            "minimum_cash_weight",
            "maximum_risk_budget",
            "minimum_liquidity_score",
        ):
            object.__setattr__(
                self,
                field_name,
                _ratio(
                    getattr(self, field_name),
                    field_name=field_name,
                ),
            )
        if not isinstance(self.bucket_limits, tuple) or not all(
            isinstance(item, AssetBucketLimit)
            for item in self.bucket_limits
        ):
            raise TypeError(
                "bucket_limits must contain AssetBucketLimit values"
            )
        buckets = [item.bucket for item in self.bucket_limits]
        if len(buckets) != len(set(buckets)):
            raise ValueError(
                "bucket_limits cannot contain duplicate buckets"
            )
        for field_name in (
            "prohibited_identifiers",
            "prohibited_exposure_tags",
        ):
            object.__setattr__(
                self,
                field_name,
                _text_tuple(
                    getattr(self, field_name),
                    field_name=field_name,
                ),
            )

    def maximum_bucket_weight(
        self,
        bucket: AssetBucket,
    ) -> float:
        """Return the explicit limit or the unconstrained maximum."""

        if not isinstance(bucket, AssetBucket):
            raise TypeError("bucket must be an AssetBucket")
        return next(
            (
                item.maximum_weight
                for item in self.bucket_limits
                if item.bucket is bucket
            ),
            1.0,
        )


@dataclass(frozen=True, slots=True)
class PortfolioProposal:
    """One non-executing portfolio expression of a committee decision."""

    identifier: str
    source_decision_identifier: str
    target_identifier: str
    bucket: AssetBucket
    requested_weight_delta: float
    estimated_risk_budget_delta: float
    liquidity_score: float
    exposure_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "identifier",
            "source_decision_identifier",
            "target_identifier",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(
                    getattr(self, field_name),
                    field_name=field_name,
                ),
            )
        if not isinstance(self.bucket, AssetBucket):
            raise TypeError("bucket must be an AssetBucket")
        if self.bucket is AssetBucket.CASH:
            raise ValueError(
                "cash is the funding reserve, not a proposal bucket"
            )
        for field_name in (
            "requested_weight_delta",
            "estimated_risk_budget_delta",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(
                value,
                (int, float),
            ):
                raise TypeError(f"{field_name} must be numeric")
            normalized = float(value)
            if not isfinite(normalized) or not -1.0 <= normalized <= 1.0:
                raise ValueError(
                    f"{field_name} must be between -1.0 and 1.0"
                )
            object.__setattr__(
                self,
                field_name,
                round(normalized, 6),
            )
        if self.requested_weight_delta == 0.0:
            raise ValueError(
                "requested_weight_delta cannot be zero"
            )
        if (
            self.requested_weight_delta
            * self.estimated_risk_budget_delta
            < 0
        ):
            raise ValueError(
                "weight and risk deltas cannot have opposite signs"
            )
        object.__setattr__(
            self,
            "liquidity_score",
            _ratio(
                self.liquidity_score,
                field_name="liquidity_score",
            ),
        )
        object.__setattr__(
            self,
            "exposure_tags",
            _text_tuple(
                self.exposure_tags,
                field_name="exposure_tags",
            ),
        )


__all__ = [
    "AssetBucket",
    "AssetBucketLimit",
    "PortfolioMandate",
    "PortfolioPosition",
    "PortfolioProposal",
    "PortfolioSnapshot",
]
