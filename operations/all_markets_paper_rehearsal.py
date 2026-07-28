"""Deterministic mechanical rehearsal for every classified paper asset class.

This rehearsal does not assert external provider readiness or investment quality.
It proves that all classified liquid public-market families can traverse the
certified universe, session, quote, contract-multiplier, cross-currency cash,
portfolio-state, and reconciliation boundaries without live-order authority.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from cio import CandidateAssetClass
from governance.asset_class_scope import AssetClassApprovalState, TradingSessionModel
from governance.eligible_universe import (
    CertifiedEligibleUniversePublication,
    EligibleUniverseCertificationState,
    SQLiteCertifiedEligibleUniverseStore,
)
from operations.universal_paper_availability import ALL_CLASSIFIED_ASSET_CLASSES
from portfolio.construction_models import (
    ConstructionStatus,
    PortfolioConstructionResult,
    TradeProposal,
    TradeSide,
)
from portfolio.multi_asset_controls import MultiAssetInstrumentProfile
from portfolio.multi_asset_execution import (
    InstrumentSession,
    InstrumentSessionStatus,
    MultiAssetExecutionStatus,
    MultiAssetPaperExecutionOrchestrator,
    MultiAssetQuote,
    SQLiteMultiAssetPaperExecutionStore,
)
from portfolio.state import CanonicalPortfolioSnapshot, SQLiteCanonicalPortfolioStore


@dataclass(frozen=True, slots=True)
class RehearsalInstrument:
    symbol: str
    asset_class: CandidateAssetClass
    venue: str
    country_code: str
    instrument_type: str
    price_currency: str
    settlement_currency: str
    bid: float
    ask: float
    last: float
    fx_rate_to_base: float
    contract_multiplier: float
    session_model: TradingSessionModel

    @property
    def instrument_identifier(self) -> str:
        return f"instrument:{self.asset_class.value}:{self.venue}:{self.symbol}"

    @property
    def approval_identifier(self) -> str:
        return f"approval:{self.asset_class.value}:mechanical-rehearsal"


_INSTRUMENTS = (
    RehearsalInstrument(
        "AAPL", CandidateAssetClass.US_EQUITY, "NASDAQ", "US",
        "common_stock", "USD", "USD", 199.90, 200.10, 200.00, 1.0, 1.0,
        TradingSessionModel.EXCHANGE_LOCAL,
    ),
    RehearsalInstrument(
        "SPY", CandidateAssetClass.US_ETF, "NYSEARCA", "US",
        "fund", "USD", "USD", 599.90, 600.10, 600.00, 1.0, 1.0,
        TradingSessionModel.EXCHANGE_LOCAL,
    ),
    RehearsalInstrument(
        "BIL", CandidateAssetClass.CASH_EQUIVALENT, "NYSEARCA", "US",
        "fund", "USD", "USD", 91.49, 91.51, 91.50, 1.0, 1.0,
        TradingSessionModel.EXCHANGE_LOCAL,
    ),
    RehearsalInstrument(
        "SHEL", CandidateAssetClass.INTERNATIONAL_EQUITY, "LSE", "GB",
        "common_stock", "GBP", "GBP", 19.95, 20.05, 20.00, 1.25, 1.0,
        TradingSessionModel.EXCHANGE_LOCAL,
    ),
    RehearsalInstrument(
        "UST10", CandidateAssetClass.FIXED_INCOME, "TRACE", "US",
        "bond", "USD", "USD", 97.90, 98.10, 98.00, 1.0, 1.0,
        TradingSessionModel.DEALER_24_5,
    ),
    RehearsalInstrument(
        "GCZ6", CandidateAssetClass.COMMODITY, "CME", "US",
        "future", "USD", "USD", 49.90, 50.10, 50.00, 1.0, 10.0,
        TradingSessionModel.EXCHANGE_LOCAL,
    ),
    RehearsalInstrument(
        "EURUSD", CandidateAssetClass.FX, "EBS", "GLOBAL",
        "spot", "USD", "USD", 1.099, 1.101, 1.100, 1.0, 1.0,
        TradingSessionModel.CONTINUOUS_24_5,
    ),
    RehearsalInstrument(
        "BTC-USD", CandidateAssetClass.CRYPTO, "COINBASE", "GLOBAL",
        "token", "USD", "USD", 49_900.0, 50_100.0, 50_000.0, 1.0, 1.0,
        TradingSessionModel.CONTINUOUS_24_7,
    ),
    RehearsalInstrument(
        "PLD", CandidateAssetClass.REAL_ESTATE, "NYSE", "US",
        "common_stock", "USD", "USD", 99.90, 100.10, 100.00, 1.0, 1.0,
        TradingSessionModel.EXCHANGE_LOCAL,
    ),
    RehearsalInstrument(
        "ESZ6", CandidateAssetClass.FUTURE, "CME", "US",
        "future", "USD", "USD", 49.90, 50.10, 50.00, 1.0, 10.0,
        TradingSessionModel.EXCHANGE_LOCAL,
    ),
    RehearsalInstrument(
        "SPY-C", CandidateAssetClass.OPTION, "CBOE", "US",
        "option", "USD", "USD", 1.95, 2.05, 2.00, 1.0, 100.0,
        TradingSessionModel.EXCHANGE_LOCAL,
    ),
    RehearsalInstrument(
        "VXZ6", CandidateAssetClass.VOLATILITY, "CFE", "US",
        "future", "USD", "USD", 19.90, 20.10, 20.00, 1.0, 100.0,
        TradingSessionModel.EXCHANGE_LOCAL,
    ),
    RehearsalInstrument(
        "ALT", CandidateAssetClass.ALTERNATIVE, "NYSEARCA", "US",
        "fund", "USD", "USD", 49.90, 50.10, 50.00, 1.0, 1.0,
        TradingSessionModel.EXCHANGE_LOCAL,
    ),
)


def _reset_rehearsal_state(root: Path) -> None:
    for name in ("eligible-universe.db", "portfolio.db", "execution.db"):
        database = root / name
        for suffix in ("", "-shm", "-wal", "-journal"):
            candidate = Path(f"{database}{suffix}")
            if candidate.exists():
                candidate.unlink()


class _SessionProvider:
    def session(
        self,
        profile: MultiAssetInstrumentProfile,
        *,
        session_model: TradingSessionModel,
        as_of: datetime,
    ) -> InstrumentSession:
        return InstrumentSession(
            instrument_identifier=profile.instrument_identifier,
            venue=profile.venue,
            session_model=session_model,
            as_of=as_of,
            status=InstrumentSessionStatus.OPEN,
            source_identifier=(
                f"rehearsal-session:{profile.venue}:{as_of.isoformat()}"
            ),
        )


class _QuoteProvider:
    def __init__(self, quotes: Mapping[str, MultiAssetQuote]) -> None:
        self.quotes_by_symbol = dict(quotes)

    def quotes(
        self,
        profiles: tuple[MultiAssetInstrumentProfile, ...],
        *,
        as_of: datetime,
    ) -> dict[str, MultiAssetQuote]:
        return {
            profile.symbol: self.quotes_by_symbol[profile.symbol]
            for profile in profiles
        }


def _profile(value: RehearsalInstrument) -> MultiAssetInstrumentProfile:
    derivative = value.instrument_type in {"future", "option", "perpetual"}
    return MultiAssetInstrumentProfile(
        symbol=value.symbol,
        instrument_identifier=value.instrument_identifier,
        asset_class=value.asset_class,
        venue=value.venue,
        country_code=value.country_code,
        price_currency=value.price_currency,
        settlement_currency=value.settlement_currency,
        approval_identifier=value.approval_identifier,
        approval_state=AssetClassApprovalState.PAPER_ELIGIBLE,
        unlevered=True,
        spot_only=value.asset_class in {
            CandidateAssetClass.CRYPTO,
            CandidateAssetClass.FX,
        },
        custody_settlement_identifier=(
            f"custody:{value.asset_class.value}:mechanical-rehearsal"
        ),
        execution_model_version=(
            f"execution:{value.asset_class.value}:mechanical-rehearsal"
        ),
        instrument_type=value.instrument_type,
        gross_leverage=1.0,
        defined_risk=True,
        margin_required=derivative,
        contract_multiplier=value.contract_multiplier,
        contract_model_version=("contract:rehearsal" if derivative else None),
        margin_model_version=("margin:rehearsal" if derivative else None),
        lifecycle_model_version=("lifecycle:rehearsal" if derivative else None),
        roll_model_version=(
            "roll:rehearsal"
            if value.instrument_type in {"future", "perpetual"}
            else None
        ),
        trading_session_model=value.session_model,
    )


def _quote(value: RehearsalInstrument, *, as_of: datetime) -> MultiAssetQuote:
    return MultiAssetQuote(
        symbol=value.symbol,
        instrument_identifier=value.instrument_identifier,
        venue=value.venue,
        observed_at=as_of,
        bid=value.bid,
        ask=value.ask,
        last=value.last,
        available_base_notional=25_000_000.0,
        price_currency=value.price_currency,
        fx_rate_to_base=value.fx_rate_to_base,
        fx_observed_at=as_of,
        quote_source_identifier=f"rehearsal-quote:{value.symbol}",
        fx_source_identifier=f"rehearsal-fx:{value.price_currency}:USD",
        quote_certification_identifier=f"cert:rehearsal:{value.symbol}",
    )


@dataclass(frozen=True, slots=True)
class AllMarketsPaperRehearsalReport:
    identifier: str
    evaluated_at: datetime
    status: str
    expected_asset_classes: tuple[str, ...]
    filled_asset_classes: tuple[str, ...]
    fill_count: int
    ending_cash: float
    ending_nav: float
    reconciliation_difference: float
    blockers: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return self.status == "passed" and not self.blockers

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "all-markets-paper-rehearsal.v2",
            "identifier": self.identifier,
            "evaluated_at": self.evaluated_at.isoformat(),
            "status": self.status,
            "expected_asset_classes": list(self.expected_asset_classes),
            "filled_asset_classes": list(self.filled_asset_classes),
            "fill_count": self.fill_count,
            "ending_cash": self.ending_cash,
            "ending_nav": self.ending_nav,
            "reconciliation_difference": self.reconciliation_difference,
            "blockers": list(self.blockers),
            "fixture_data_only": True,
            "all_classified_asset_classes_covered": (
                self.expected_asset_classes == self.filled_asset_classes
            ),
            "external_data_ready": False,
            "live_order_routing_authorized": False,
            "real_money_authorized": False,
        }


def run_all_markets_paper_rehearsal(
    *,
    evaluated_at: datetime,
    working_directory: str | Path | None = None,
) -> AllMarketsPaperRehearsalReport:
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    expected = tuple(
        sorted(item.value for item in ALL_CLASSIFIED_ASSET_CLASSES)
    )
    configured = tuple(sorted(item.asset_class.value for item in _INSTRUMENTS))
    blockers: list[str] = []
    if configured != expected:
        blockers.append(
            "rehearsal instruments do not exactly cover every classified asset class"
        )
    root_context = (
        tempfile.TemporaryDirectory(prefix="capital-intelligence-rehearsal-")
        if working_directory is None
        else None
    )
    root = Path(
        root_context.name if root_context is not None else working_directory
    ).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    _reset_rehearsal_state(root)
    try:
        profiles = {item.symbol: _profile(item) for item in _INSTRUMENTS}
        quotes = {
            item.symbol: _quote(item, as_of=evaluated_at)
            for item in _INSTRUMENTS
        }
        class_weight = 0.01
        trades = tuple(
            TradeProposal(
                symbol=item.symbol,
                side=TradeSide.BUY,
                from_weight=0.0,
                to_weight=class_weight,
                trade_weight=class_weight,
                estimated_cost_return=0.001,
                reason="universal asset-class mechanical rehearsal",
            )
            for item in _INSTRUMENTS
        )
        publication_identifier = "eligible-universe:all-markets-rehearsal"
        construction = PortfolioConstructionResult(
            request_identifier="construction:all-markets-rehearsal",
            as_of=evaluated_at - timedelta(minutes=1),
            status=ConstructionStatus.FEASIBLE,
            policy_version="portfolio-construction.v1",
            target_cash_weight=round(1.0 - class_weight * len(_INSTRUMENTS), 8),
            target_weights=tuple(
                (item.symbol, class_weight) for item in _INSTRUMENTS
            ),
            trades=trades,
            turnover=round(class_weight * len(_INSTRUMENTS), 8),
            estimated_cost_return=0.001,
            expected_return_before=0.05,
            expected_return_after_cost=0.049,
            expected_return_improvement=0.01,
            constraints=(),
            blocks=(),
            eligible_universe_publication_identifier=publication_identifier,
            instrument_identifiers=tuple(
                (item.symbol, item.instrument_identifier)
                for item in _INSTRUMENTS
            ),
        )
        universe_store = SQLiteCertifiedEligibleUniverseStore(
            root / "eligible-universe.db"
        )
        universe_store.append(
            CertifiedEligibleUniversePublication(
                identifier=publication_identifier,
                published_at=evaluated_at - timedelta(minutes=2),
                as_of=evaluated_at - timedelta(minutes=1),
                knowledge_cutoff=evaluated_at - timedelta(minutes=3),
                security_master_catalog_identifier="catalog:rehearsal",
                security_master_snapshot_identifier="snapshot:rehearsal",
                policy_version="recommendation-universe.v1",
                certification_identifier="certification:all-markets-rehearsal",
                certification_state=EligibleUniverseCertificationState.APPROVED,
                certification_expires_at=evaluated_at + timedelta(days=1),
                eligible_instrument_identifiers=tuple(
                    item.instrument_identifier for item in _INSTRUMENTS
                ),
                source_versions=(("rehearsal-fixture", "v2"),),
                model_versions=(("execution", "mechanical-rehearsal.v2"),),
                instrument_approval_identifiers=tuple(
                    (item.instrument_identifier, item.approval_identifier)
                    for item in _INSTRUMENTS
                ),
            )
        )
        portfolio = CanonicalPortfolioSnapshot(
            identifier="portfolio:all-markets-rehearsal:beginning",
            portfolio_code="COMPOUNDING",
            display_name="Compounding",
            constraint_profile="institutional",
            as_of=evaluated_at - timedelta(minutes=1),
            starting_capital=250_000.0,
            cash_amount=250_000.0,
            positions=(),
            source_identifiers=("rehearsal:beginning",),
        )
        portfolio_store = SQLiteCanonicalPortfolioStore(root / "portfolio.db")
        portfolio_store.append(portfolio)
        execution_store = SQLiteMultiAssetPaperExecutionStore(root / "execution.db")
        batch = MultiAssetPaperExecutionOrchestrator(
            session_provider=_SessionProvider(),
            quote_provider=_QuoteProvider(quotes),
            store=execution_store,
            portfolio_store=portfolio_store,
            universe_store=universe_store,
        ).execute(
            construction=construction,
            decision_identifier="decision:all-markets-rehearsal",
            portfolio=portfolio,
            profiles=profiles,
            as_of=evaluated_at,
        )
        filled = tuple(sorted({item.asset_class.value for item in batch.fills}))
        if batch.status not in {
            MultiAssetExecutionStatus.COMPLETED,
            MultiAssetExecutionStatus.PARTIAL,
        }:
            blockers.append(f"execution batch status is {batch.status.value}")
        missing = sorted(set(expected) - set(filled))
        if missing:
            blockers.append("asset classes without fills: " + ", ".join(missing))
        if not batch.reconciliation.reconciled:
            blockers.append("portfolio reconciliation failed")
        if batch.ending_snapshot.cash_amount < 0:
            blockers.append("ending paper cash is negative")
        return AllMarketsPaperRehearsalReport(
            identifier=f"all-markets-paper-rehearsal:{evaluated_at.isoformat()}",
            evaluated_at=evaluated_at,
            status="passed" if not blockers else "failed",
            expected_asset_classes=expected,
            filled_asset_classes=filled,
            fill_count=len(batch.fills),
            ending_cash=batch.ending_snapshot.cash_amount,
            ending_nav=batch.ending_snapshot.nav,
            reconciliation_difference=batch.reconciliation.difference,
            blockers=tuple(blockers),
        )
    finally:
        if root_context is not None:
            root_context.cleanup()


__all__ = [
    "AllMarketsPaperRehearsalReport",
    "run_all_markets_paper_rehearsal",
]
