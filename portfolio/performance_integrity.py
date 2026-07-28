"""Integrity-certified wrapper for canonical mark-to-market publication."""

from __future__ import annotations

from math import isfinite
from pathlib import Path
from tempfile import TemporaryDirectory

from portfolio.integrity_specialist import (
    PortfolioIntegrityCertification,
    PortfolioIntegrityDisposition,
    PortfolioValuationExecutionIntegritySpecialist,
    SQLitePortfolioIntegrityCertificationStore,
)
from portfolio.performance import (
    PortfolioMarkToMarketService as _BasePortfolioMarkToMarketService,
)
from portfolio.performance import PortfolioPerformanceError
from portfolio.state import CanonicalPortfolioSnapshot, SQLiteCanonicalPortfolioStore


class PortfolioMarkToMarketService(_BasePortfolioMarkToMarketService):
    """Publish marks only after independent valuation-integrity certification."""

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
        default_path = Path(self.portfolio_store.path).with_name("portfolio_integrity.db")
        self.integrity_store = (
            integrity_store or SQLitePortfolioIntegrityCertificationStore(default_path)
        )
        if not isinstance(
            self.integrity_store,
            SQLitePortfolioIntegrityCertificationStore,
        ):
            raise TypeError(
                "integrity_store must be a SQLitePortfolioIntegrityCertificationStore"
            )

    def _certify_valuation(
        self,
        *,
        report,
        beginning: CanonicalPortfolioSnapshot,
        ending: CanonicalPortfolioSnapshot,
    ) -> PortfolioIntegrityCertification:
        checks: list[str] = []
        blocks: list[str] = []
        tolerance = self.policy.reconciliation_tolerance

        if beginning.portfolio_code != ending.portfolio_code:
            blocks.append("portfolio identity changed during valuation")
        else:
            checks.append("portfolio identity preserved")
        if beginning.base_currency != ending.base_currency:
            blocks.append("base currency changed during valuation")
        else:
            checks.append("base currency preserved")
        if abs(beginning.starting_capital - ending.starting_capital) > tolerance:
            blocks.append("starting capital changed during valuation")
        else:
            checks.append("starting capital preserved")
        if abs(beginning.cash_amount - ending.cash_amount) > tolerance:
            blocks.append("base-currency cash changed during mark-to-market")
        else:
            checks.append("base-currency cash preserved")
        if beginning.implementation_events != ending.implementation_events:
            blocks.append("implementation history changed during mark-to-market")
        else:
            checks.append("implementation history preserved")

        beginning_positions = {item.symbol: item for item in beginning.positions}
        ending_positions = {item.symbol: item for item in ending.positions}
        if set(beginning_positions) != set(ending_positions):
            blocks.append("position membership changed during mark-to-market")
        else:
            checks.append("position membership preserved")
        for symbol in sorted(set(beginning_positions) & set(ending_positions)):
            prior = beginning_positions[symbol]
            current = ending_positions[symbol]
            if abs(prior.quantity - current.quantity) > self.integrity_specialist.quantity_tolerance:
                blocks.append(f"{symbol} quantity changed during mark-to-market")
            if abs(prior.average_cost - current.average_cost) > self.integrity_specialist.quantity_tolerance:
                blocks.append(f"{symbol} average cost changed during mark-to-market")
            if prior.average_cost_base != current.average_cost_base:
                blocks.append(f"{symbol} preserved base cost changed during mark-to-market")
            if current.updated_at > report.as_of:
                blocks.append(f"{symbol} valuation timestamp is future-dated")
            values = (
                current.quantity,
                current.average_cost,
                current.mark_price,
                current.cost_basis,
                current.market_value,
                current.unrealized_gain,
            )
            if not all(isfinite(float(value)) for value in values):
                blocks.append(f"{symbol} valuation contains a non-finite value")
            if current.mark_price <= 0.0:
                blocks.append(f"{symbol} mark price is not positive")
        if not any(
            "quantity changed" in item
            or "average cost changed" in item
            or "base cost changed" in item
            or "valuation timestamp" in item
            or "non-finite" in item
            or "mark price" in item
            for item in blocks
        ):
            checks.append(
                "shares, cost basis, marks, market value, and unrealized gain/loss are valid"
            )

        beginning_balances = {
            item.currency: (item.amount, item.cost_basis_base)
            for item in beginning.currency_balances
        }
        ending_balances = {
            item.currency: (item.amount, item.cost_basis_base)
            for item in ending.currency_balances
        }
        if beginning_balances != ending_balances:
            blocks.append("currency amounts or preserved costs changed during valuation")
        else:
            checks.append("currency amounts and preserved costs are unchanged")

        difference = float(report.reconciliation_difference)
        if report.complete is not True:
            blocks.append("valuation report is incomplete")
        elif not isfinite(difference) or abs(difference) > tolerance:
            blocks.append("valuation reconciliation difference exceeds tolerance")
        elif abs(float(report.accounting_residual)) > tolerance:
            blocks.append("portfolio accounting residual exceeds tolerance")
        else:
            checks.append("NAV and accounting reconciliation passed")

        disposition = (
            PortfolioIntegrityDisposition.CERTIFIED
            if not blocks
            else PortfolioIntegrityDisposition.HELD
        )
        return PortfolioIntegrityCertification(
            identifier=f"portfolio-integrity:{ending.portfolio_code}:{report.identifier}",
            execution_identifier=report.identifier,
            completed_at=report.as_of,
            beginning_snapshot_identifier=beginning.identifier,
            ending_snapshot_identifier=ending.identifier,
            disposition=disposition,
            checks=tuple(checks),
            blocks=tuple(blocks),
            reconciliation_difference=difference,
            specialist_version=self.integrity_specialist.version,
        )

    @staticmethod
    def _publish(
        *,
        store: SQLiteCanonicalPortfolioStore,
        beginning: CanonicalPortfolioSnapshot,
        ending: CanonicalPortfolioSnapshot,
    ) -> None:
        store.verify_integrity()
        latest = store.latest(beginning.portfolio_code)
        if latest is None:
            raise PortfolioPerformanceError(
                "canonical portfolio disappeared before certified valuation publication"
            )
        if latest.identifier == ending.identifier:
            return
        if latest.identifier != beginning.identifier:
            raise PortfolioPerformanceError(
                "canonical portfolio changed before certified valuation publication"
            )
        store.append(ending)
        store.verify_integrity()

    def mark(self, *, portfolio, profiles, as_of):
        real_store = self.portfolio_store
        with TemporaryDirectory(prefix="capital-intelligence-valuation-integrity-") as directory:
            staging = SQLiteCanonicalPortfolioStore(
                Path(directory) / "canonical_portfolio_staging.db"
            )
            staging.append(portfolio)
            self.portfolio_store = staging
            try:
                report = super().mark(
                    portfolio=portfolio,
                    profiles=profiles,
                    as_of=as_of,
                )
                ending = staging.latest(portfolio.portfolio_code)
            finally:
                self.portfolio_store = real_store

        if ending is None:
            raise PortfolioPerformanceError(
                "mark-to-market did not produce an ending portfolio snapshot"
            )
        existing = self.integrity_store.latest(report.identifier)
        if (
            existing is not None
            and existing.ending_snapshot_identifier == ending.identifier
        ):
            if not existing.certified:
                raise PortfolioPerformanceError(
                    "portfolio valuation and execution integrity specialist held "
                    "valuation publication: " + "; ".join(existing.blocks)
                )
            self._publish(store=real_store, beginning=portfolio, ending=ending)
            return report

        certification = self._certify_valuation(
            report=report,
            beginning=portfolio,
            ending=ending,
        )
        self.integrity_store.append(certification)
        self.integrity_store.verify_integrity()
        if not certification.certified:
            raise PortfolioPerformanceError(
                "portfolio valuation and execution integrity specialist held "
                "valuation publication: " + "; ".join(certification.blocks)
            )
        self._publish(store=real_store, beginning=portfolio, ending=ending)
        return report


__all__ = ["PortfolioMarkToMarketService"]
