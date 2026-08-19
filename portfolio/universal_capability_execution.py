"""Universal Capability Graph enforcement at the canonical paper-fill boundary.

The legacy multi-asset executor already owns sessions, quotes, liquidity, cash,
positions, fills, accounting, and reconciliation. Replacing that mature ledger would
create unnecessary execution risk. This subclass makes the universal paper contract
an authoritative invariant exactly where all required execution quantities are known.

New/increased exposure requires either the long-standing bootstrap authority or an
active append-only instrument capability certification. Reductions/exits retain the
existing owned-instrument continuity path so loss of a capability can never trap the
portfolio in a degraded position.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from governance.instrument_paper_eligibility import (
    SQLiteInstrumentPaperEligibilityStore,
)
from governance.market_participation import CanonicalMarketParticipationAuthority
from operations.universal_capability_graph import (
    AssetFamily,
    CapabilityEvaluation,
    family_for_instrument,
)
from operations.universal_paper_contract import (
    DEFAULT_LIFECYCLE_ADAPTERS,
    NormalizedInvestmentView,
    PaperOrderIntent,
    translate_paper_intent,
)
from portfolio.construction_models import TradeSide
from portfolio.multi_asset_execution import (
    MultiAssetExecutionError,
    MultiAssetPaperExecutionOrchestrator,
)


class UniversalCapabilityPaperExecutionOrchestrator(
    MultiAssetPaperExecutionOrchestrator
):
    """Require universal capability/quantity invariants for every paper fill."""

    @property
    def capability_database_path(self) -> Path:
        return Path(self.portfolio_store.path).expanduser().with_name(
            "instrument-paper-eligibility.db"
        )

    def _active_certification(self, profile, *, at):
        store = SQLiteInstrumentPaperEligibilityStore(self.capability_database_path)
        store.verify_integrity()
        return store.active(profile.instrument_identifier, evaluated_at=at)

    @staticmethod
    def _evaluation_from_authority(profile, *, at, certification=None):
        family = family_for_instrument(profile.asset_class, profile.instrument_type)
        if family is None:
            raise MultiAssetExecutionError(
                f"{profile.symbol} has no universal paper lifecycle adapter"
            )
        if family not in DEFAULT_LIFECYCLE_ADAPTERS:
            raise MultiAssetExecutionError(
                f"{profile.symbol} asset family {family.value} has no paper adapter"
            )
        if certification is None:
            proof = {
                "bootstrap_authority": f"bootstrap-paper-authority:{profile.instrument_identifier}"
            }
        else:
            if certification.instrument_identifier != profile.instrument_identifier:
                raise MultiAssetExecutionError("capability certification identity mismatch")
            if certification.symbol != profile.symbol:
                raise MultiAssetExecutionError("capability certification symbol mismatch")
            if certification.asset_class is not profile.asset_class:
                raise MultiAssetExecutionError("capability certification asset-class mismatch")
            if certification.venue != profile.venue:
                raise MultiAssetExecutionError("capability certification venue mismatch")
            if certification.instrument_type != profile.instrument_type:
                raise MultiAssetExecutionError("capability certification structure mismatch")
            proof = {
                "instrument_paper_eligibility": certification.identifier,
                "market_data": certification.market_data_certification_identifier,
                "identity": certification.identity_certification_identifier,
                "evidence": certification.evidence_certification_identifier,
                "valuation": certification.valuation_model_version,
                "trading_calendar": certification.trading_calendar_certification_identifier,
                "transaction_costs": certification.transaction_cost_model_version,
                "liquidity": certification.liquidity_model_version,
                "accounting": certification.accounting_model_version,
                "execution": certification.execution_model_version,
                "risk": certification.risk_model_version,
                "portfolio_construction": certification.portfolio_construction_model_version,
                "custody_settlement": certification.custody_settlement_identifier,
            }
        return CapabilityEvaluation(
            instrument_identifier=profile.instrument_identifier,
            asset_family=family,
            evaluated_at=at,
            discovered=True,
            identified=True,
            evidence_qualified=True,
            analytically_supported=True,
            lifecycle_valid=True,
            paper_executable=True,
            certifiable=True,
            missing_capabilities=(),
            blockers=(),
            proof_identifiers=proof,
        )

    def _universal_execution_evaluation(self, profile, *, trade, attempted_at):
        certification = self._active_certification(profile, at=attempted_at)
        if certification is not None:
            return self._evaluation_from_authority(
                profile,
                at=attempted_at,
                certification=certification,
            )
        bootstrap = CanonicalMarketParticipationAuthority.load(
            capability_database_path=self.capability_database_path,
        ).allocatable_instrument_identifiers
        if profile.instrument_identifier in bootstrap:
            return self._evaluation_from_authority(profile, at=attempted_at)
        if trade.side is TradeSide.BUY:
            raise MultiAssetExecutionError(
                f"{profile.symbol} cannot increase exposure without an active Universal Capability Graph paper certification"
            )
        # Exit continuity: the canonical executor independently verifies exact owned
        # identity and the eligible-universe publication. A suspended capability is
        # allowed to reduce/exit but cannot create new exposure.
        return None

    def _fill_trade(self, *, trade, profile, quote, attempted_at, **kwargs):
        evaluation = self._universal_execution_evaluation(
            profile,
            trade=trade,
            attempted_at=attempted_at,
        )
        family = family_for_instrument(profile.asset_class, profile.instrument_type)
        resolved_quote = quote
        # Direct fixed-income quotes conventionally express percent of par. The legacy
        # ledger wants currency per face-value unit, while the universal adapter itself
        # knows the percent-of-par convention. Normalize only the ledger quote here and
        # retain the original quote for the independent universal-contract check below.
        if family is AssetFamily.FIXED_INCOME:
            resolved_quote = replace(
                quote,
                bid=quote.bid * 0.01,
                ask=quote.ask * 0.01,
                last=quote.last * 0.01,
            )
        fill, result, cash, position = super()._fill_trade(
            trade=trade,
            profile=profile,
            quote=resolved_quote,
            attempted_at=attempted_at,
            **kwargs,
        )
        if fill is None or evaluation is None:
            return fill, result, cash, position

        # The universal adapter receives the market convention, not the ledger's
        # normalized fixed-income unit price. For all other families these are equal.
        reference_price = (
            quote.bid if fill.side is TradeSide.SELL else quote.ask
            if family is AssetFamily.FIXED_INCOME
            else fill.fill_price_local
        )
        # Parenthesize explicitly because the conditional above spans two quote sides.
        if family is AssetFamily.FIXED_INCOME:
            reference_price = quote.bid if fill.side is TradeSide.SELL else quote.ask
        else:
            reference_price = fill.fill_price_local

        intent = PaperOrderIntent(
            instrument_identifier=profile.instrument_identifier,
            target_notional=fill.gross_amount_local,
            side=fill.side.value,
        )
        view = NormalizedInvestmentView(
            instrument_identifier=profile.instrument_identifier,
            asset_family=evaluation.asset_family,
            reference_price=reference_price,
            contract_multiplier=profile.contract_multiplier,
            trading_currency=profile.price_currency,
            settlement_currency=profile.settlement_currency,
        )
        instruction = translate_paper_intent(intent, view, evaluation)
        if abs(abs(instruction.signed_quantity) - fill.quantity) > 1e-8:
            raise MultiAssetExecutionError(
                f"{profile.symbol} fill quantity violates the universal paper-order contract"
            )
        if (instruction.signed_quantity > 0.0) != (fill.side is TradeSide.BUY):
            raise MultiAssetExecutionError(
                f"{profile.symbol} fill side violates the universal paper-order contract"
            )
        return fill, result, cash, position


__all__ = ["UniversalCapabilityPaperExecutionOrchestrator"]
