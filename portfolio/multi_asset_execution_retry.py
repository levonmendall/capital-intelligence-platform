"""Retry adapter that preserves the original construction notional.

A partially implemented portfolio has a different NAV from the portfolio used by
construction. The base fill engine accepts trade weights, so a resumed attempt
must re-express each unfinished trade weight against the current NAV while keeping
the original requested base-currency amount. This adapter changes no canonical
target weight, decision, ranking, or construction identifier.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal, ROUND_CEILING
from typing import Mapping

from portfolio.construction_models import PortfolioConstructionResult, TradeSide
from portfolio.multi_asset_controls import MultiAssetInstrumentProfile
from portfolio.multi_asset_execution import (
    MultiAssetExecutionError,
    MultiAssetExecutionStatus,
    MultiAssetPaperExecutionOrchestrator as _BaseOrchestrator,
)
from portfolio.state import CanonicalPortfolioSnapshot

_WEIGHT_QUANTUM = Decimal("0.000000000001")


class MultiAssetPaperExecutionOrchestrator(_BaseOrchestrator):
    """Execute retries using the original recorded base-currency notional."""

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
        adjusted = construction
        if previous is not None and previous.status not in {
            MultiAssetExecutionStatus.COMPLETED,
            MultiAssetExecutionStatus.NO_ACTION,
        }:
            if portfolio.nav <= 0.0:
                raise MultiAssetExecutionError(
                    "execution retry requires a positive canonical portfolio NAV"
                )
            prior_by_symbol = {
                item.symbol: item for item in previous.order_results
            }
            adjusted_trades = []
            for trade in construction.trades:
                prior = prior_by_symbol.get(trade.symbol)
                if prior is None:
                    adjusted_trades.append(trade)
                    continue
                weight_decimal = (
                    Decimal(str(prior.requested_base_amount))
                    / Decimal(str(portfolio.nav))
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
            adjusted = replace(construction, trades=tuple(adjusted_trades))
        return super().execute(
            construction=adjusted,
            decision_identifier=decision_identifier,
            portfolio=portfolio,
            profiles=profiles,
            as_of=as_of,
        )


__all__ = ["MultiAssetPaperExecutionOrchestrator"]
