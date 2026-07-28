"""Independent multi-venue crypto quote validation for controlled paper use."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from data.market import MarketDataQuery, MarketDataType, MarketQuote
from providers.crypto_venues import CryptoVenueBindingRegistry


@dataclass(frozen=True, slots=True)
class CryptoVenuePairAssessment:
    instrument_id: str
    coinbase_midpoint: float | None
    kraken_midpoint: float | None
    midpoint_divergence_bps: float | None
    ready: bool
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "coinbase_midpoint": self.coinbase_midpoint,
            "kraken_midpoint": self.kraken_midpoint,
            "midpoint_divergence_bps": self.midpoint_divergence_bps,
            "ready": self.ready,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True, slots=True)
class CryptoVenueValidationReport:
    evaluated_at: datetime
    complete: bool
    pair_count: int
    ready_pair_count: int
    assessments: tuple[CryptoVenuePairAssessment, ...]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "crypto-venue-validation-report.v1",
            "evaluated_at": self.evaluated_at.isoformat(),
            "complete": self.complete,
            "pair_count": self.pair_count,
            "ready_pair_count": self.ready_pair_count,
            "assessments": [item.to_dict() for item in self.assessments],
            "blockers": list(self.blockers),
            "provider_certification_granted": False,
            "paper_test_readiness_granted": False,
            "custody_authority_granted": False,
            "execution_authority_granted": False,
            "real_money_authorized": False,
        }


def _quote(provider, query: MarketDataQuery) -> MarketQuote:
    batch = provider.fetch(query)
    if len(batch.records) != 1 or not isinstance(batch.records[0], MarketQuote):
        raise ValueError("venue validation requires exactly one MarketQuote")
    quote = batch.records[0]
    if quote.bid <= 0 or quote.ask <= 0 or quote.bid > quote.ask:
        raise ValueError("venue quote is non-positive or crossed")
    if quote.provenance.observed_at > query.as_of:
        raise ValueError("venue quote is future-known")
    return quote


def validate_crypto_venues(
    *,
    bindings: CryptoVenueBindingRegistry,
    coinbase_provider,
    kraken_provider,
    evaluated_at: datetime,
    maximum_midpoint_divergence_bps: float = 250.0,
    maximum_quote_age_seconds: float = 120.0,
) -> CryptoVenueValidationReport:
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    if maximum_midpoint_divergence_bps <= 0:
        raise ValueError("maximum_midpoint_divergence_bps must be positive")
    if maximum_quote_age_seconds <= 0:
        raise ValueError("maximum_quote_age_seconds must be positive")
    assessments: list[CryptoVenuePairAssessment] = []
    global_blockers: list[str] = []
    for binding in bindings.bindings:
        blockers: list[str] = []
        coinbase_midpoint = None
        kraken_midpoint = None
        divergence = None
        try:
            coinbase_query = MarketDataQuery(
                instrument_id=binding.instrument_id,
                data_type=MarketDataType.QUOTE,
                as_of=evaluated_at,
                venue="COINBASE",
                limit=1,
            )
            coinbase = _quote(coinbase_provider, coinbase_query)
            if (
                evaluated_at - coinbase.provenance.observed_at
            ).total_seconds() > maximum_quote_age_seconds:
                blockers.append("Coinbase quote is stale")
            coinbase_midpoint = (coinbase.bid + coinbase.ask) / 2.0
        except Exception as error:
            blockers.append(f"Coinbase validation failed: {error}")
        try:
            kraken_query = MarketDataQuery(
                instrument_id=binding.instrument_id,
                data_type=MarketDataType.QUOTE,
                as_of=evaluated_at,
                venue="KRAKEN",
                limit=1,
            )
            kraken = _quote(kraken_provider, kraken_query)
            if (
                evaluated_at - kraken.provenance.observed_at
            ).total_seconds() > maximum_quote_age_seconds:
                blockers.append("Kraken quote is stale")
            kraken_midpoint = (kraken.bid + kraken.ask) / 2.0
        except Exception as error:
            blockers.append(f"Kraken validation failed: {error}")
        if coinbase_midpoint is not None and kraken_midpoint is not None:
            center = (coinbase_midpoint + kraken_midpoint) / 2.0
            divergence = (
                abs(coinbase_midpoint - kraken_midpoint) / center * 10_000.0
            )
            if divergence > maximum_midpoint_divergence_bps:
                blockers.append(
                    "cross-venue midpoint divergence exceeds policy: "
                    f"{divergence:.2f} bps"
                )
        ready = not blockers
        if not ready:
            global_blockers.append(f"{binding.instrument_id}: " + "; ".join(blockers))
        assessments.append(
            CryptoVenuePairAssessment(
                instrument_id=binding.instrument_id,
                coinbase_midpoint=coinbase_midpoint,
                kraken_midpoint=kraken_midpoint,
                midpoint_divergence_bps=divergence,
                ready=ready,
                blockers=tuple(blockers),
            )
        )
    if not assessments:
        global_blockers.append("no crypto venue bindings were configured")
    return CryptoVenueValidationReport(
        evaluated_at=evaluated_at,
        complete=bool(assessments) and not global_blockers,
        pair_count=len(assessments),
        ready_pair_count=sum(item.ready for item in assessments),
        assessments=tuple(assessments),
        blockers=tuple(global_blockers),
    )


__all__ = [
    "CryptoVenuePairAssessment",
    "CryptoVenueValidationReport",
    "validate_crypto_venues",
]
