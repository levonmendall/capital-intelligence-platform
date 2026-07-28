"""Retry adapter with independent portfolio-integrity certification.

A partially implemented portfolio has a different NAV from the portfolio used by
construction. The base fill engine accepts trade weights, so a resumed attempt
must re-express each unfinished trade weight against the current NAV while keeping
the original requested base-currency amount.

The base executor is deliberately run against a temporary canonical portfolio
store. Its proposed ending snapshot is published to the real canonical store only
after the non-voting Portfolio Valuation & Execution Integrity Specialist certifies
shares, cash, transaction costs, marks, NAV, and reconciliation.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Mapping

from portfolio.construction_models import PortfolioConstructionResult, TradeSide
from portfolio.integrity_specialist import (
    PortfolioValuationExecutionIntegritySpecialist,
    SQLitePortfolioIntegrityCertificationStore,
)
from portfolio.multi_asset_controls import MultiAssetInstrumentProfile
from portfolio.multi_asset_execution import (
    MultiAssetExecutionError,
    MultiAssetExecutionStatus,
    MultiAssetPaperExecutionOrchestrator as _BaseOrchestrator,
)
from portfolio.state import CanonicalPortfolioSnapshot, SQLiteCanonicalPortfolioStore

_WEIGHT_QUANTUM = Decimal("0.000000000001")


class MultiAssetPaperExecutionOrchestrator(_BaseOrchestrator):
    """Execute retries and publish only specialist-certified portfolio state."""

    def __init__(
        self,
        *args,
        integrity_specialist: PortfolioValuationExecutionIntegritySpecialist | None = None,
        integrity_store: SQLitePortfolioIntegrityCertificationStore | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.integrity_specialist = (
            integrity_specialist
            or PortfolioValuationExecutionIntegritySpecialist(
                cash_tolerance=self.policy.reconciliation_tolerance
            )
        )
        if not isinstance(
            self.integrity_specialist,
            PortfolioValuationExecutionIntegritySpecialist,
        ):
            raise TypeError(
                "integrity_specialist must be a "
                "PortfolioValuationExecutionIntegritySpecialist"
            )
        default_integrity_path = Path(self.portfolio_store.path).with_name(
            "portfolio_integrity.db"
        )
        self.integrity_store = (
            integrity_store
            or SQLitePortfolioIntegrityCertificationStore(default_integrity_path)
        )
        if not isinstance(
            self.integrity_store,
            SQLitePortfolioIntegrityCertificationStore,
        ):
            raise TypeError(
                "integrity_store must be a SQLitePortfolioIntegrityCertificationStore"
            )

    def _adjusted_construction(
        self,
        *,
        construction: PortfolioConstructionResult,
        portfolio: CanonicalPortfolioSnapshot,
        previous,
    ) -> PortfolioConstructionResult:
        adjusted = construction
        if previous is None or previous.status in {
            MultiAssetExecutionStatus.COMPLETED,
            MultiAssetExecutionStatus.NO_ACTION,
        }:
            return adjusted
        if portfolio.nav <= 0.0:
            raise MultiAssetExecutionError(
                "execution retry requires a positive canonical portfolio NAV"
            )
        prior_by_symbol = {item.symbol: item for item in previous.order_results}
        representation_guard = Decimal(
            str(self.policy.reconciliation_tolerance)
        ) / Decimal("2")
        adjusted_trades = []
        for trade in construction.trades:
            prior = prior_by_symbol.get(trade.symbol)
            if prior is None:
                adjusted_trades.append(trade)
                continue
            guarded_notional = (
                Decimal(str(prior.requested_base_amount)) + representation_guard
            )
            weight_decimal = (
                guarded_notional / Decimal(str(portfolio.nav))
            ).quantize(_WEIGHT_QUANTUM, rounding=ROUND_CEILING)
            weight = float(weight_decimal)
            if weight <= 0.0 or weight > 1.0:
                raise MultiAssetExecutionError(
                    "original execution notional cannot be represented against "
                    "the retry portfolio NAV"
                )
            if trade.side is TradeSide.BUY:
                from_weight = 0.0
                to_weight = weight
            else:
                from_weight = weight
                to_weight = 0.0
            adjusted_trades.append(
                replace(
                    trade,
                    from_weight=from_weight,
                    to_weight=to_weight,
                    trade_weight=weight,
                )
            )
        return replace(construction, trades=tuple(adjusted_trades))

    @staticmethod
    def _new_fills(batch, previous) -> tuple:
        previous_ids = (
            set() if previous is None else {item.identifier for item in previous.fills}
        )
        return tuple(item for item in batch.fills if item.identifier not in previous_ids)

    @staticmethod
    def _publish_certified_snapshot(
        *,
        store: SQLiteCanonicalPortfolioStore,
        beginning: CanonicalPortfolioSnapshot,
        ending: CanonicalPortfolioSnapshot,
    ) -> None:
        store.verify_integrity()
        latest = store.latest(beginning.portfolio_code)
        if latest is None:
            raise MultiAssetExecutionError(
                "canonical portfolio disappeared before certified publication"
            )
        if latest.identifier == ending.identifier:
            return
        if latest.identifier != beginning.identifier:
            raise MultiAssetExecutionError(
                "canonical portfolio changed before integrity-certified publication"
            )
        store.append(ending)
        store.verify_integrity()

    def execute(
        self,
        *,
        construction: PortfolioConstructionResult,
        decision_identifier: str,
        portfolio: CanonicalPortfolioSnapshot,
        profiles: Mapping[str, MultiAssetInstrumentProfile],
        as_of: datetime,
    ):
        batch_identifier = f"multi-asset-execution:{construction.request_identifier}"
        previous = self.store.latest_batch(batch_identifier)
        adjusted = self._adjusted_construction(
            construction=construction,
            portfolio=portfolio,
            previous=previous,
        )

        real_portfolio_store = self.portfolio_store
        with TemporaryDirectory(prefix="capital-intelligence-integrity-") as directory:
            staging_store = SQLiteCanonicalPortfolioStore(
                Path(directory) / "canonical_portfolio_staging.db"
            )
            staging_store.append(portfolio)
            self.portfolio_store = staging_store
            try:
                batch = super().execute(
                    construction=adjusted,
                    decision_identifier=decision_identifier,
                    portfolio=portfolio,
                    profiles=profiles,
                    as_of=as_of,
                )
            finally:
                self.portfolio_store = real_portfolio_store

        existing = self.integrity_store.latest(batch.identifier)
        if (
            existing is not None
            and existing.ending_snapshot_identifier == batch.ending_snapshot.identifier
        ):
            if not existing.certified:
                raise MultiAssetExecutionError(
                    "portfolio valuation and execution integrity specialist held "
                    "publication: " + "; ".join(existing.blocks)
                )
            self._publish_certified_snapshot(
                store=real_portfolio_store,
                beginning=portfolio,
                ending=batch.ending_snapshot,
            )
            return batch

        certification = self.integrity_specialist.review_execution(
            execution_identifier=batch.identifier,
            beginning=portfolio,
            ending=batch.ending_snapshot,
            fills=self._new_fills(batch, previous),
            reconciliation=batch.reconciliation,
            completed_at=batch.attempted_at,
            attempt=batch.attempt,
        )
        self.integrity_store.append(certification)
        self.integrity_store.verify_integrity()
        if not certification.certified:
            raise MultiAssetExecutionError(
                "portfolio valuation and execution integrity specialist held "
                "publication: " + "; ".join(certification.blocks)
            )

        self._publish_certified_snapshot(
            store=real_portfolio_store,
            beginning=portfolio,
            ending=batch.ending_snapshot,
        )
        return batch


__all__ = ["MultiAssetPaperExecutionOrchestrator"]
