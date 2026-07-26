"""Deterministic expected-return portfolio construction under explicit constraints."""

from __future__ import annotations

from dataclasses import dataclass

from cio import CIOAction
from portfolio.construction_models import (
    ConstructionIntent,
    ConstructionStatus,
    ConstraintCheck,
    PortfolioAsset,
    PortfolioConstructionPolicy,
    PortfolioConstructionRequest,
    PortfolioConstructionResult,
    TradeProposal,
    TradeSide,
)


@dataclass(frozen=True, slots=True)
class _AssetState:
    symbol: str
    expected_return: float
    sector: str
    factor_loadings: tuple[tuple[str, float], ...]
    correlation_bucket: str
    average_daily_dollar_volume: float
    transaction_cost_bps: float
    slippage_bps: float
    minimum_weight: float
    funding_eligible: bool

    @property
    def total_cost_bps(self) -> float:
        return self.transaction_cost_bps + self.slippage_bps


class PortfolioConstructionEngine:
    """Allocate approved CIO expressions without executing trades.

    Positive allocations are considered in opportunity priority order. Cash is
    used first. Explicitly funding-eligible holdings may then be reduced only
    when the approved candidate offers the configured minimum expected-return
    edge. All changes remain bounded by position, liquidity, sector, factor,
    correlation, cash, turnover, and cost constraints.
    """

    def __init__(
        self,
        policy: PortfolioConstructionPolicy | None = None,
    ) -> None:
        self.policy = policy or PortfolioConstructionPolicy()

    def construct(
        self,
        request: PortfolioConstructionRequest,
    ) -> PortfolioConstructionResult:
        if not isinstance(request, PortfolioConstructionRequest):
            raise TypeError("request must be a PortfolioConstructionRequest")

        current = {item.symbol: item.current_weight for item in request.positions}
        target = dict(current)
        assets = self._asset_states(request)
        reasons: dict[str, list[str]] = {symbol: [] for symbol in assets}
        funding_for: dict[str, list[str]] = {symbol: [] for symbol in assets}
        blocks: list[str] = []
        intents = {item.symbol: item for item in request.intents}

        negative = sorted(
            (
                item
                for item in request.intents
                if item.action in {CIOAction.EXIT, CIOAction.REDUCE}
            ),
            key=lambda item: (
                0 if item.action is CIOAction.EXIT else 1,
                item.priority_rank,
                item.symbol,
            ),
        )
        for intent in negative:
            starting = target.get(intent.symbol, 0.0)
            requested = intent.requested_target_weight or 0.0
            if requested > starting + 0.000001:
                blocks.append(
                    f"{intent.symbol} {intent.action.value} target exceeds current weight"
                )
                continue
            target[intent.symbol] = requested
            reasons.setdefault(intent.symbol, []).append(
                f"CIO {intent.action.value} decision requested {requested:.2%}"
            )

        positive = sorted(
            (
                item
                for item in request.intents
                if item.action in {CIOAction.BUY, CIOAction.INCREASE}
            ),
            key=lambda item: (
                item.priority_rank,
                -item.opportunity_edge,
                -item.expected_return,
                item.symbol,
            ),
        )
        for intent in positive:
            starting = target.get(intent.symbol, 0.0)
            requested = intent.requested_target_weight or 0.0
            liquidity_limit = self._liquidity_weight_limit(
                intent.average_daily_dollar_volume,
                request.portfolio_value,
            )
            allowed_target = min(
                requested,
                intent.maximum_position_weight,
                self.policy.maximum_position_weight,
                liquidity_limit,
            )
            if allowed_target <= starting + 0.0000001:
                blocks.append(
                    f"{intent.symbol} has no feasible positive allocation after position and liquidity limits"
                )
                continue
            desired_delta = allowed_target - starting
            available_cash = self._cash_weight(target) - self.policy.minimum_cash_weight
            if available_cash < desired_delta:
                self._raise_cash(
                    request=request,
                    intent=intent,
                    target=target,
                    assets=assets,
                    intents=intents,
                    reasons=reasons,
                    funding_for=funding_for,
                    required_cash=desired_delta - max(0.0, available_cash),
                )
            feasible_delta = self._maximum_feasible_delta(
                request=request,
                symbol=intent.symbol,
                target=target,
                assets=assets,
                desired_delta=desired_delta,
            )
            if feasible_delta <= 0.0000001:
                blocks.append(
                    f"{intent.symbol} cannot be allocated without violating portfolio constraints"
                )
                continue
            target[intent.symbol] = round(starting + feasible_delta, 8)
            reasons.setdefault(intent.symbol, []).append(
                f"CIO {intent.action.value} decision allocated in opportunity rank {intent.priority_rank}"
            )
            if feasible_delta + 0.000001 < desired_delta:
                blocks.append(
                    f"{intent.symbol} was partially allocated at {target[intent.symbol]:.2%} versus requested {requested:.2%}"
                )

        target = {
            symbol: round(weight, 8)
            for symbol, weight in target.items()
            if weight > 0.00000001
        }
        target_cash = round(1.0 - sum(target.values()), 8)
        trades = self._trades(
            current=current,
            target=target,
            assets=assets,
            reasons=reasons,
            funding_for=funding_for,
        )
        turnover = round(sum(item.trade_weight for item in trades), 8)
        cost = round(sum(item.estimated_cost_return for item in trades), 8)
        before = self._expected_return(
            weights=current,
            cash_weight=request.cash_weight,
            assets=assets,
            cash_return=request.cash_expected_return,
        )
        after_gross = self._expected_return(
            weights=target,
            cash_weight=target_cash,
            assets=assets,
            cash_return=request.cash_expected_return,
        )
        after_cost = round(after_gross - cost, 8)
        constraints = self._constraint_checks(
            request=request,
            target=target,
            target_cash=target_cash,
            assets=assets,
            turnover=turnover,
            cost=cost,
        )
        unsatisfied = tuple(item for item in constraints if not item.satisfied)
        blocks.extend(item.detail for item in unsatisfied)
        blocks = list(dict.fromkeys(blocks))

        if unsatisfied:
            status = ConstructionStatus.BLOCKED
        elif blocks and trades:
            status = ConstructionStatus.PARTIAL
        elif blocks:
            status = ConstructionStatus.BLOCKED
        elif trades:
            status = ConstructionStatus.FEASIBLE
        else:
            status = ConstructionStatus.NO_ACTION

        return PortfolioConstructionResult(
            request_identifier=request.identifier,
            as_of=request.as_of,
            status=status,
            policy_version=self.policy.version,
            target_cash_weight=target_cash,
            target_weights=tuple(sorted(target.items())),
            trades=trades,
            turnover=turnover,
            estimated_cost_return=cost,
            expected_return_before=before,
            expected_return_after_cost=after_cost,
            expected_return_improvement=round(after_cost - before, 8),
            constraints=constraints,
            blocks=tuple(blocks),
        )

    def _asset_states(
        self,
        request: PortfolioConstructionRequest,
    ) -> dict[str, _AssetState]:
        values: dict[str, _AssetState] = {
            item.symbol: self._from_position(item) for item in request.positions
        }
        for intent in request.intents:
            existing = values.get(intent.symbol)
            values[intent.symbol] = _AssetState(
                symbol=intent.symbol,
                expected_return=intent.expected_return,
                sector=intent.sector,
                factor_loadings=intent.factor_loadings,
                correlation_bucket=intent.correlation_bucket,
                average_daily_dollar_volume=intent.average_daily_dollar_volume,
                transaction_cost_bps=intent.transaction_cost_bps,
                slippage_bps=intent.slippage_bps,
                minimum_weight=(0.0 if existing is None else existing.minimum_weight),
                funding_eligible=(
                    False if existing is None else existing.funding_eligible
                ),
            )
        return values

    @staticmethod
    def _from_position(item: PortfolioAsset) -> _AssetState:
        return _AssetState(
            symbol=item.symbol,
            expected_return=item.expected_return,
            sector=item.sector,
            factor_loadings=item.factor_loadings,
            correlation_bucket=item.correlation_bucket,
            average_daily_dollar_volume=item.average_daily_dollar_volume,
            transaction_cost_bps=item.transaction_cost_bps,
            slippage_bps=item.slippage_bps,
            minimum_weight=item.minimum_weight,
            funding_eligible=item.funding_eligible,
        )

    def _raise_cash(
        self,
        *,
        request: PortfolioConstructionRequest,
        intent: ConstructionIntent,
        target: dict[str, float],
        assets: dict[str, _AssetState],
        intents: dict[str, ConstructionIntent],
        reasons: dict[str, list[str]],
        funding_for: dict[str, list[str]],
        required_cash: float,
    ) -> None:
        remaining = required_cash
        funding_candidates = sorted(
            (
                asset
                for symbol, asset in assets.items()
                if symbol != intent.symbol
                and asset.funding_eligible
                and target.get(symbol, 0.0) > asset.minimum_weight
                and symbol not in {
                    key
                    for key, value in intents.items()
                    if value.action in {CIOAction.BUY, CIOAction.INCREASE}
                }
                and intent.expected_return - asset.expected_return
                >= self.policy.minimum_replacement_edge
            ),
            key=lambda asset: (
                asset.expected_return,
                target.get(asset.symbol, 0.0),
                asset.symbol,
            ),
        )
        for asset in funding_candidates:
            if remaining <= 0.0000001:
                break
            current_target = target.get(asset.symbol, 0.0)
            reducible = current_target - asset.minimum_weight
            if reducible <= 0.0:
                continue
            turnover_room = max(
                0.0,
                self.policy.maximum_turnover
                - self._turnover(request, target),
            )
            reduction = min(reducible, remaining, turnover_room)
            if reduction <= 0.0000001:
                break
            target[asset.symbol] = round(current_target - reduction, 8)
            remaining -= reduction
            reasons.setdefault(asset.symbol, []).append(
                f"Funding source for higher expected-return candidate {intent.symbol}"
            )
            funding_for.setdefault(asset.symbol, []).append(intent.symbol)

    def _maximum_feasible_delta(
        self,
        *,
        request: PortfolioConstructionRequest,
        symbol: str,
        target: dict[str, float],
        assets: dict[str, _AssetState],
        desired_delta: float,
    ) -> float:
        low = 0.0
        high = desired_delta
        for _ in range(50):
            middle = (low + high) / 2.0
            proposal = dict(target)
            proposal[symbol] = proposal.get(symbol, 0.0) + middle
            if self._is_feasible(
                request=request,
                target=proposal,
                assets=assets,
            ):
                low = middle
            else:
                high = middle
        return round(low, 8)

    def _is_feasible(
        self,
        *,
        request: PortfolioConstructionRequest,
        target: dict[str, float],
        assets: dict[str, _AssetState],
    ) -> bool:
        cash = self._cash_weight(target)
        if cash + 0.000001 < self.policy.minimum_cash_weight:
            return False
        if self._turnover(request, target) > self.policy.maximum_turnover + 0.000001:
            return False
        if self._cost(request, target, assets) > self.policy.maximum_total_cost_return + 0.000001:
            return False
        for symbol, weight in target.items():
            asset = assets[symbol]
            liquidity_limit = self._liquidity_weight_limit(
                asset.average_daily_dollar_volume,
                request.portfolio_value,
            )
            if weight > min(
                self.policy.maximum_position_weight,
                liquidity_limit,
            ) + 0.000001:
                return False
        for sector, weight in self._sector_weights(target, assets).items():
            if weight > self.policy.sector_limit(sector) + 0.000001:
                return False
        for bucket, weight in self._correlation_weights(target, assets).items():
            if weight > self.policy.correlation_limit(bucket) + 0.000001:
                return False
        for factor, exposure in self._factor_exposures(target, assets).items():
            limit = self.policy.factor_limit(factor)
            if limit is not None and abs(exposure) > limit + 0.000001:
                return False
        return True

    def _constraint_checks(
        self,
        *,
        request: PortfolioConstructionRequest,
        target: dict[str, float],
        target_cash: float,
        assets: dict[str, _AssetState],
        turnover: float,
        cost: float,
    ) -> tuple[ConstraintCheck, ...]:
        checks: list[ConstraintCheck] = [
            ConstraintCheck(
                name="minimum_cash",
                satisfied=target_cash + 0.000001 >= self.policy.minimum_cash_weight,
                value=target_cash,
                limit=self.policy.minimum_cash_weight,
                detail=(
                    f"target cash {target_cash:.2%} must be at least "
                    f"{self.policy.minimum_cash_weight:.2%}"
                ),
            ),
            ConstraintCheck(
                name="maximum_turnover",
                satisfied=turnover <= self.policy.maximum_turnover + 0.000001,
                value=turnover,
                limit=self.policy.maximum_turnover,
                detail=(
                    f"turnover {turnover:.2%} must not exceed "
                    f"{self.policy.maximum_turnover:.2%}"
                ),
            ),
            ConstraintCheck(
                name="maximum_total_cost",
                satisfied=cost <= self.policy.maximum_total_cost_return + 0.000001,
                value=cost,
                limit=self.policy.maximum_total_cost_return,
                detail=(
                    f"estimated implementation cost {cost:.2%} must not exceed "
                    f"{self.policy.maximum_total_cost_return:.2%}"
                ),
            ),
        ]
        for symbol, weight in sorted(target.items()):
            asset = assets[symbol]
            limit = min(
                self.policy.maximum_position_weight,
                self._liquidity_weight_limit(
                    asset.average_daily_dollar_volume,
                    request.portfolio_value,
                ),
            )
            checks.append(
                ConstraintCheck(
                    name=f"position:{symbol}",
                    satisfied=weight <= limit + 0.000001,
                    value=weight,
                    limit=limit,
                    detail=f"{symbol} target {weight:.2%} must not exceed {limit:.2%}",
                )
            )
        for sector, weight in sorted(self._sector_weights(target, assets).items()):
            limit = self.policy.sector_limit(sector)
            checks.append(
                ConstraintCheck(
                    name=f"sector:{sector}",
                    satisfied=weight <= limit + 0.000001,
                    value=weight,
                    limit=limit,
                    detail=f"{sector} exposure {weight:.2%} must not exceed {limit:.2%}",
                )
            )
        for bucket, weight in sorted(
            self._correlation_weights(target, assets).items()
        ):
            limit = self.policy.correlation_limit(bucket)
            checks.append(
                ConstraintCheck(
                    name=f"correlation:{bucket}",
                    satisfied=weight <= limit + 0.000001,
                    value=weight,
                    limit=limit,
                    detail=f"{bucket} correlated exposure {weight:.2%} must not exceed {limit:.2%}",
                )
            )
        for factor, exposure in sorted(
            self._factor_exposures(target, assets).items()
        ):
            limit = self.policy.factor_limit(factor)
            if limit is None:
                continue
            checks.append(
                ConstraintCheck(
                    name=f"factor:{factor}",
                    satisfied=abs(exposure) <= limit + 0.000001,
                    value=abs(exposure),
                    limit=limit,
                    detail=f"absolute {factor} exposure {abs(exposure):.2%} must not exceed {limit:.2%}",
                )
            )
        return tuple(checks)

    def _trades(
        self,
        *,
        current: dict[str, float],
        target: dict[str, float],
        assets: dict[str, _AssetState],
        reasons: dict[str, list[str]],
        funding_for: dict[str, list[str]],
    ) -> tuple[TradeProposal, ...]:
        trades: list[TradeProposal] = []
        for symbol in sorted(set(current) | set(target)):
            before = current.get(symbol, 0.0)
            after = target.get(symbol, 0.0)
            change = after - before
            if abs(change) <= 0.0000001:
                continue
            asset = assets[symbol]
            trade_weight = abs(change)
            trades.append(
                TradeProposal(
                    symbol=symbol,
                    side=(TradeSide.BUY if change > 0.0 else TradeSide.SELL),
                    from_weight=before,
                    to_weight=after,
                    trade_weight=trade_weight,
                    estimated_cost_return=round(
                        trade_weight * asset.total_cost_bps / 10_000,
                        8,
                    ),
                    reason=(
                        "; ".join(reasons.get(symbol, ()))
                        or "Portfolio construction constraint adjustment"
                    ),
                    funding_for=tuple(dict.fromkeys(funding_for.get(symbol, ()))),
                )
            )
        return tuple(trades)

    @staticmethod
    def _cash_weight(target: dict[str, float]) -> float:
        return round(1.0 - sum(target.values()), 8)

    @staticmethod
    def _turnover(
        request: PortfolioConstructionRequest,
        target: dict[str, float],
    ) -> float:
        current = {item.symbol: item.current_weight for item in request.positions}
        return round(
            sum(
                abs(target.get(symbol, 0.0) - current.get(symbol, 0.0))
                for symbol in set(current) | set(target)
            ),
            8,
        )

    @staticmethod
    def _cost(
        request: PortfolioConstructionRequest,
        target: dict[str, float],
        assets: dict[str, _AssetState],
    ) -> float:
        current = {item.symbol: item.current_weight for item in request.positions}
        return round(
            sum(
                abs(target.get(symbol, 0.0) - current.get(symbol, 0.0))
                * assets[symbol].total_cost_bps
                / 10_000
                for symbol in set(current) | set(target)
            ),
            8,
        )

    def _liquidity_weight_limit(
        self,
        average_daily_dollar_volume: float,
        portfolio_value: float,
    ) -> float:
        executable_value = (
            average_daily_dollar_volume
            * self.policy.maximum_daily_volume_participation
            * self.policy.execution_days
        )
        return round(min(1.0, executable_value / portfolio_value), 8)

    @staticmethod
    def _sector_weights(
        weights: dict[str, float],
        assets: dict[str, _AssetState],
    ) -> dict[str, float]:
        values: dict[str, float] = {}
        for symbol, weight in weights.items():
            sector = assets[symbol].sector
            values[sector] = values.get(sector, 0.0) + weight
        return {key: round(value, 8) for key, value in values.items()}

    @staticmethod
    def _correlation_weights(
        weights: dict[str, float],
        assets: dict[str, _AssetState],
    ) -> dict[str, float]:
        values: dict[str, float] = {}
        for symbol, weight in weights.items():
            bucket = assets[symbol].correlation_bucket
            values[bucket] = values.get(bucket, 0.0) + weight
        return {key: round(value, 8) for key, value in values.items()}

    @staticmethod
    def _factor_exposures(
        weights: dict[str, float],
        assets: dict[str, _AssetState],
    ) -> dict[str, float]:
        values: dict[str, float] = {}
        for symbol, weight in weights.items():
            for factor, loading in assets[symbol].factor_loadings:
                values[factor] = values.get(factor, 0.0) + weight * loading
        return {key: round(value, 8) for key, value in values.items()}

    @staticmethod
    def _expected_return(
        *,
        weights: dict[str, float],
        cash_weight: float,
        assets: dict[str, _AssetState],
        cash_return: float,
    ) -> float:
        return round(
            cash_weight * cash_return
            + sum(weight * assets[symbol].expected_return for symbol, weight in weights.items()),
            8,
        )


__all__ = ["PortfolioConstructionEngine"]