"""Safe cost-aware portfolio construction under explicit constraints.

The engine produces executable paper-trade proposals. It never executes trades,
never consumes investor goals, and never derives position size from CIO
confidence. Funding changes are evaluated transactionally and are committed only
when they enable a feasible approved allocation.
"""

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


_EPSILON = 1e-9


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
    """Convert approved CIO decisions into feasible, non-executing trades."""

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

        current = {
            item.symbol: item.current_weight for item in request.positions
        }
        target = dict(current)
        assets = self._asset_states(request)
        intents = {item.symbol: item for item in request.intents}
        reasons: dict[str, list[str]] = {
            symbol: [] for symbol in assets
        }
        funding_for: dict[str, list[str]] = {
            symbol: [] for symbol in assets
        }
        blocks: list[str] = []

        self._apply_reductions(
            request=request,
            target=target,
            assets=assets,
            reasons=reasons,
            blocks=blocks,
        )
        self._apply_positive_allocations(
            request=request,
            target=target,
            assets=assets,
            intents=intents,
            reasons=reasons,
            funding_for=funding_for,
            blocks=blocks,
        )

        target = {
            symbol: round(weight, 8)
            for symbol, weight in target.items()
            if weight > _EPSILON
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
        constraints = self._constraint_checks(
            request=request,
            target=target,
            target_cash=target_cash,
            assets=assets,
            turnover=turnover,
            cost=cost,
        )
        unsatisfied = tuple(item for item in constraints if not item.satisfied)

        # A construction result labelled executable must never contain a target
        # that fails its own controls. Fall back to the current portfolio rather
        # than exposing blocked trades as if they could be implemented.
        if unsatisfied:
            blocks.extend(item.detail for item in unsatisfied)
            target = dict(current)
            target_cash = request.cash_weight
            trades = ()
            turnover = 0.0
            cost = 0.0
            constraints = self._constraint_checks(
                request=request,
                target=target,
                target_cash=target_cash,
                assets=assets,
                turnover=turnover,
                cost=cost,
            )

        blocks = list(dict.fromkeys(blocks))
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

        if trades and blocks:
            status = ConstructionStatus.PARTIAL
        elif trades:
            status = ConstructionStatus.FEASIBLE
        elif blocks:
            status = ConstructionStatus.BLOCKED
        else:
            status = ConstructionStatus.NO_ACTION

        return PortfolioConstructionResult(
            request_identifier=request.identifier,
            as_of=request.as_of,
            status=status,
            policy_version=self.policy.version,
            target_cash_weight=target_cash,
            target_weights=tuple(sorted(target.items())),
            trades=tuple(trades),
            turnover=turnover,
            estimated_cost_return=cost,
            expected_return_before=before,
            expected_return_after_cost=after_cost,
            expected_return_improvement=round(after_cost - before, 8),
            constraints=constraints,
            blocks=tuple(blocks),
        )

    def _apply_reductions(
        self,
        *,
        request: PortfolioConstructionRequest,
        target: dict[str, float],
        assets: dict[str, _AssetState],
        reasons: dict[str, list[str]],
        blocks: list[str],
    ) -> None:
        ordered = sorted(
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
        for intent in ordered:
            starting = target.get(intent.symbol, 0.0)
            requested = intent.requested_target_weight or 0.0
            if requested > starting + _EPSILON:
                blocks.append(
                    f"{intent.symbol} {intent.action.value} target exceeds its current weight"
                )
                continue
            desired_reduction = starting - requested
            if desired_reduction <= _EPSILON:
                continue
            feasible_reduction = self._maximum_feasible_reduction(
                request=request,
                symbol=intent.symbol,
                target=target,
                assets=assets,
                desired_reduction=desired_reduction,
            )
            if feasible_reduction <= _EPSILON:
                blocks.append(
                    f"{intent.symbol} cannot be reduced within turnover, cost, and liquidity constraints"
                )
                continue
            target[intent.symbol] = round(
                starting - feasible_reduction,
                8,
            )
            reasons.setdefault(intent.symbol, []).append(
                f"CIO {intent.action.value} decision targeted {requested:.2%}"
            )
            if feasible_reduction + _EPSILON < desired_reduction:
                blocks.append(
                    f"{intent.symbol} was only partially reduced to {target[intent.symbol]:.2%}"
                )

    def _apply_positive_allocations(
        self,
        *,
        request: PortfolioConstructionRequest,
        target: dict[str, float],
        assets: dict[str, _AssetState],
        intents: dict[str, ConstructionIntent],
        reasons: dict[str, list[str]],
        funding_for: dict[str, list[str]],
        blocks: list[str],
    ) -> None:
        ordered = sorted(
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
        for intent in ordered:
            starting = target.get(intent.symbol, 0.0)
            requested = intent.requested_target_weight or 0.0
            position_limit = min(
                requested,
                intent.maximum_position_weight,
                self.policy.maximum_position_weight,
            )
            if position_limit <= starting + _EPSILON:
                blocks.append(
                    f"{intent.symbol} has no positive allocation within its position limit"
                )
                continue
            desired_delta = position_limit - starting

            # First allocate only what current cash and constraints allow.
            cash_delta = self._maximum_feasible_increase(
                request=request,
                symbol=intent.symbol,
                target=target,
                assets=assets,
                desired_delta=desired_delta,
            )
            best_target = dict(target)
            best_reasons = self._copy_lists(reasons)
            best_funding = self._copy_lists(funding_for)
            best_delta = cash_delta

            if cash_delta + _EPSILON < desired_delta:
                trial_target = dict(target)
                trial_reasons = self._copy_lists(reasons)
                trial_funding = self._copy_lists(funding_for)
                reductions = self._raise_cash_transactionally(
                    request=request,
                    intent=intent,
                    target=trial_target,
                    assets=assets,
                    intents=intents,
                    reasons=trial_reasons,
                    funding_for=trial_funding,
                    requested_shortfall=desired_delta - cash_delta,
                )
                funded_delta = self._maximum_feasible_increase(
                    request=request,
                    symbol=intent.symbol,
                    target=trial_target,
                    assets=assets,
                    desired_delta=desired_delta,
                )
                if funded_delta > best_delta + _EPSILON:
                    trial_target[intent.symbol] = round(
                        starting + funded_delta,
                        8,
                    )
                    self._restore_excess_funding(
                        request=request,
                        target=trial_target,
                        assets=assets,
                        reductions=reductions,
                    )
                    # Recalculate after restoration and retain only a target that
                    # remains feasible as a complete transaction.
                    actual_delta = (
                        trial_target.get(intent.symbol, 0.0) - starting
                    )
                    if actual_delta > best_delta + _EPSILON and self._is_feasible(
                        request=request,
                        target=trial_target,
                        assets=assets,
                    ):
                        best_target = trial_target
                        best_reasons = trial_reasons
                        best_funding = trial_funding
                        best_delta = actual_delta

            if best_delta <= _EPSILON:
                blocks.append(
                    f"{intent.symbol} cannot be allocated without violating portfolio constraints"
                )
                continue
            if best_target is target or best_target == target:
                best_target = dict(target)
                best_target[intent.symbol] = round(starting + best_delta, 8)
            target.clear()
            target.update(best_target)
            reasons.clear()
            reasons.update(best_reasons)
            funding_for.clear()
            funding_for.update(best_funding)
            reasons.setdefault(intent.symbol, []).append(
                f"CIO {intent.action.value} decision allocated in opportunity rank {intent.priority_rank}"
            )
            if best_delta + _EPSILON < desired_delta:
                blocks.append(
                    f"{intent.symbol} was partially allocated at {target[intent.symbol]:.2%} versus requested {requested:.2%}"
                )

    def _raise_cash_transactionally(
        self,
        *,
        request: PortfolioConstructionRequest,
        intent: ConstructionIntent,
        target: dict[str, float],
        assets: dict[str, _AssetState],
        intents: dict[str, ConstructionIntent],
        reasons: dict[str, list[str]],
        funding_for: dict[str, list[str]],
        requested_shortfall: float,
    ) -> tuple[tuple[str, float], ...]:
        reductions: list[tuple[str, float]] = []
        remaining = requested_shortfall
        protected_positive = {
            symbol
            for symbol, value in intents.items()
            if value.action in {CIOAction.BUY, CIOAction.INCREASE}
        }
        candidates = sorted(
            (
                asset
                for symbol, asset in assets.items()
                if symbol != intent.symbol
                and symbol not in protected_positive
                and asset.funding_eligible
                and target.get(symbol, 0.0) > asset.minimum_weight
                and intent.expected_return - asset.expected_return
                >= self.policy.minimum_replacement_edge
            ),
            key=lambda asset: (
                asset.expected_return,
                -target.get(asset.symbol, 0.0),
                asset.symbol,
            ),
        )
        for asset in candidates:
            if remaining <= _EPSILON:
                break
            before = target.get(asset.symbol, 0.0)
            reducible = before - asset.minimum_weight
            if reducible <= _EPSILON:
                continue
            desired = min(reducible, remaining)
            feasible = self._maximum_feasible_reduction(
                request=request,
                symbol=asset.symbol,
                target=target,
                assets=assets,
                desired_reduction=desired,
            )
            if feasible <= _EPSILON:
                continue
            target[asset.symbol] = round(before - feasible, 8)
            reductions.append((asset.symbol, feasible))
            remaining -= feasible
            reasons.setdefault(asset.symbol, []).append(
                f"Explicit funding source for higher expected-return candidate {intent.symbol}"
            )
            funding_for.setdefault(asset.symbol, []).append(intent.symbol)
        return tuple(reductions)

    def _restore_excess_funding(
        self,
        *,
        request: PortfolioConstructionRequest,
        target: dict[str, float],
        assets: dict[str, _AssetState],
        reductions: tuple[tuple[str, float], ...],
    ) -> None:
        extra_cash = max(
            0.0,
            self._cash_weight(target) - self.policy.minimum_cash_weight,
        )
        for symbol, reduction in reversed(reductions):
            if extra_cash <= _EPSILON:
                break
            restoration = min(reduction, extra_cash)
            before = target.get(symbol, 0.0)
            proposal = dict(target)
            proposal[symbol] = round(before + restoration, 8)
            if self._is_feasible(
                request=request,
                target=proposal,
                assets=assets,
            ):
                target.clear()
                target.update(proposal)
                extra_cash -= restoration

    def _maximum_feasible_increase(
        self,
        *,
        request: PortfolioConstructionRequest,
        symbol: str,
        target: dict[str, float],
        assets: dict[str, _AssetState],
        desired_delta: float,
    ) -> float:
        return self._binary_search_change(
            request=request,
            symbol=symbol,
            target=target,
            assets=assets,
            desired_change=desired_delta,
        )

    def _maximum_feasible_reduction(
        self,
        *,
        request: PortfolioConstructionRequest,
        symbol: str,
        target: dict[str, float],
        assets: dict[str, _AssetState],
        desired_reduction: float,
    ) -> float:
        return self._binary_search_change(
            request=request,
            symbol=symbol,
            target=target,
            assets=assets,
            desired_change=-desired_reduction,
        )

    def _binary_search_change(
        self,
        *,
        request: PortfolioConstructionRequest,
        symbol: str,
        target: dict[str, float],
        assets: dict[str, _AssetState],
        desired_change: float,
    ) -> float:
        magnitude = abs(desired_change)
        direction = 1.0 if desired_change >= 0.0 else -1.0
        starting = target.get(symbol, 0.0)

        # Prefer the exact requested change when it is feasible. This avoids
        # returning a value infinitesimally below a binding boundary.
        exact = round(magnitude, 8)
        exact_proposal = dict(target)
        exact_proposal[symbol] = round(
            starting + direction * exact,
            10,
        )
        if (
            exact_proposal[symbol] >= -_EPSILON
            and self._is_feasible(
                request=request,
                target=exact_proposal,
                assets=assets,
            )
        ):
            return exact

        low = 0.0
        high = magnitude
        for _ in range(55):
            middle = (low + high) / 2.0
            proposal = dict(target)
            proposal[symbol] = round(starting + direction * middle, 10)
            if proposal[symbol] < -_EPSILON:
                high = middle
                continue
            if self._is_feasible(
                request=request,
                target=proposal,
                assets=assets,
            ):
                low = middle
            else:
                high = middle

        # Quantization can move the rounded result just beyond a binding
        # limit. Step down by one weight quantum until the returned change is
        # demonstrably feasible under the same complete constraint set.
        candidate = round(low, 8)
        while candidate > 0.0:
            proposal = dict(target)
            proposal[symbol] = round(
                starting + direction * candidate,
                10,
            )
            if self._is_feasible(
                request=request,
                target=proposal,
                assets=assets,
            ):
                return candidate
            candidate = round(max(0.0, candidate - 0.00000001), 8)
        return 0.0

    def _is_feasible(
        self,
        *,
        request: PortfolioConstructionRequest,
        target: dict[str, float],
        assets: dict[str, _AssetState],
    ) -> bool:
        if any(weight < -_EPSILON for weight in target.values()):
            return False
        cash = self._cash_weight(target)
        if cash + _EPSILON < self.policy.minimum_cash_weight:
            return False
        if self._turnover(request, target) > self.policy.maximum_turnover + _EPSILON:
            return False
        if self._cost(request, target, assets) > self.policy.maximum_total_cost_return + _EPSILON:
            return False
        current = {
            item.symbol: item.current_weight for item in request.positions
        }
        for symbol, weight in target.items():
            effective_position_limit = max(
                self.policy.maximum_position_weight,
                current.get(symbol, 0.0),
            )
            if weight > effective_position_limit + _EPSILON:
                return False
            trade_weight = abs(weight - current.get(symbol, 0.0))
            if trade_weight > self._liquidity_trade_limit(
                assets[symbol].average_daily_dollar_volume,
                request.portfolio_value,
            ) + _EPSILON:
                return False
        for symbol in set(current).difference(target):
            if current[symbol] > self._liquidity_trade_limit(
                assets[symbol].average_daily_dollar_volume,
                request.portfolio_value,
            ) + _EPSILON:
                return False
        current_sectors = self._sector_weights(current, assets)
        for sector, weight in self._sector_weights(target, assets).items():
            effective_limit = max(
                self.policy.sector_limit(sector),
                current_sectors.get(sector, 0.0),
            )
            if weight > effective_limit + _EPSILON:
                return False
        current_buckets = self._correlation_weights(current, assets)
        for bucket, weight in self._correlation_weights(target, assets).items():
            effective_limit = max(
                self.policy.correlation_limit(bucket),
                current_buckets.get(bucket, 0.0),
            )
            if weight > effective_limit + _EPSILON:
                return False
        current_factors = self._factor_exposures(current, assets)
        for factor, exposure in self._factor_exposures(target, assets).items():
            policy_limit = self.policy.factor_limit(factor)
            if policy_limit is None:
                continue
            effective_limit = max(
                policy_limit,
                abs(current_factors.get(factor, 0.0)),
            )
            if abs(exposure) > effective_limit + _EPSILON:
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
                satisfied=target_cash + _EPSILON >= self.policy.minimum_cash_weight,
                value=target_cash,
                limit=self.policy.minimum_cash_weight,
                detail=(
                    f"target cash {target_cash:.2%} must be at least "
                    f"{self.policy.minimum_cash_weight:.2%}"
                ),
            ),
            ConstraintCheck(
                name="maximum_turnover",
                satisfied=turnover <= self.policy.maximum_turnover + _EPSILON,
                value=turnover,
                limit=self.policy.maximum_turnover,
                detail=(
                    f"turnover {turnover:.2%} must not exceed "
                    f"{self.policy.maximum_turnover:.2%}"
                ),
            ),
            ConstraintCheck(
                name="maximum_total_cost",
                satisfied=cost <= self.policy.maximum_total_cost_return + _EPSILON,
                value=cost,
                limit=self.policy.maximum_total_cost_return,
                detail=(
                    f"estimated implementation cost {cost:.2%} must not exceed "
                    f"{self.policy.maximum_total_cost_return:.2%}"
                ),
            ),
        ]
        current = {
            item.symbol: item.current_weight for item in request.positions
        }
        for symbol, weight in sorted(target.items()):
            effective_position_limit = max(
                self.policy.maximum_position_weight,
                current.get(symbol, 0.0),
            )
            checks.append(
                ConstraintCheck(
                    name=f"position:{symbol}",
                    satisfied=weight <= effective_position_limit + _EPSILON,
                    value=weight,
                    limit=effective_position_limit,
                    detail=(
                        f"{symbol} target {weight:.2%} must not exceed "
                        f"the effective {effective_position_limit:.2%} limit"
                    ),
                )
            )
            trade_weight = abs(weight - current.get(symbol, 0.0))
            trade_limit = self._liquidity_trade_limit(
                assets[symbol].average_daily_dollar_volume,
                request.portfolio_value,
            )
            checks.append(
                ConstraintCheck(
                    name=f"liquidity:{symbol}",
                    satisfied=trade_weight <= trade_limit + _EPSILON,
                    value=trade_weight,
                    limit=trade_limit,
                    detail=(
                        f"{symbol} trade {trade_weight:.2%} must not exceed "
                        f"the {trade_limit:.2%} execution-liquidity limit"
                    ),
                )
            )
        current_sectors = self._sector_weights(current, assets)
        for sector, weight in sorted(self._sector_weights(target, assets).items()):
            policy_limit = self.policy.sector_limit(sector)
            limit = max(policy_limit, current_sectors.get(sector, 0.0))
            checks.append(
                ConstraintCheck(
                    name=f"sector:{sector}",
                    satisfied=weight <= limit + _EPSILON,
                    value=weight,
                    limit=limit,
                    detail=(
                        f"{sector} exposure {weight:.2%} must not exceed "
                        f"the effective {limit:.2%} limit"
                    ),
                )
            )
        current_buckets = self._correlation_weights(current, assets)
        for bucket, weight in sorted(
            self._correlation_weights(target, assets).items()
        ):
            policy_limit = self.policy.correlation_limit(bucket)
            limit = max(policy_limit, current_buckets.get(bucket, 0.0))
            checks.append(
                ConstraintCheck(
                    name=f"correlation:{bucket}",
                    satisfied=weight <= limit + _EPSILON,
                    value=weight,
                    limit=limit,
                    detail=(
                        f"{bucket} correlated exposure {weight:.2%} must not "
                        f"exceed the effective {limit:.2%} limit"
                    ),
                )
            )
        current_factors = self._factor_exposures(current, assets)
        for factor, exposure in sorted(
            self._factor_exposures(target, assets).items()
        ):
            policy_limit = self.policy.factor_limit(factor)
            if policy_limit is None:
                continue
            limit = max(
                policy_limit,
                abs(current_factors.get(factor, 0.0)),
            )
            checks.append(
                ConstraintCheck(
                    name=f"factor:{factor}",
                    satisfied=abs(exposure) <= limit + _EPSILON,
                    value=abs(exposure),
                    limit=limit,
                    detail=(
                        f"absolute {factor} exposure {abs(exposure):.2%} must "
                        f"not exceed the effective {limit:.2%} limit"
                    ),
                )
            )
        return tuple(checks)

    def _asset_states(
        self,
        request: PortfolioConstructionRequest,
    ) -> dict[str, _AssetState]:
        values = {
            item.symbol: self._from_position(item)
            for item in request.positions
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
                minimum_weight=(
                    0.0 if existing is None else existing.minimum_weight
                ),
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

    def _trades(
        self,
        *,
        current: dict[str, float],
        target: dict[str, float],
        assets: dict[str, _AssetState],
        reasons: dict[str, list[str]],
        funding_for: dict[str, list[str]],
    ) -> tuple[TradeProposal, ...]:
        values: list[TradeProposal] = []
        for symbol in sorted(set(current) | set(target)):
            before = current.get(symbol, 0.0)
            after = target.get(symbol, 0.0)
            change = after - before
            if abs(change) <= _EPSILON:
                continue
            asset = assets[symbol]
            trade_weight = abs(change)
            values.append(
                TradeProposal(
                    symbol=symbol,
                    side=(
                        TradeSide.BUY if change > 0.0 else TradeSide.SELL
                    ),
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
                    funding_for=tuple(
                        dict.fromkeys(funding_for.get(symbol, ()))
                    ),
                )
            )
        return tuple(values)

    @staticmethod
    def _copy_lists(
        source: dict[str, list[str]],
    ) -> dict[str, list[str]]:
        return {key: list(values) for key, values in source.items()}

    @staticmethod
    def _cash_weight(target: dict[str, float]) -> float:
        return round(1.0 - sum(target.values()), 10)

    @staticmethod
    def _turnover(
        request: PortfolioConstructionRequest,
        target: dict[str, float],
    ) -> float:
        current = {
            item.symbol: item.current_weight for item in request.positions
        }
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
        current = {
            item.symbol: item.current_weight for item in request.positions
        }
        return round(
            sum(
                abs(target.get(symbol, 0.0) - current.get(symbol, 0.0))
                * assets[symbol].total_cost_bps
                / 10_000
                for symbol in set(current) | set(target)
            ),
            8,
        )

    def _liquidity_trade_limit(
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
            + sum(
                weight * assets[symbol].expected_return
                for symbol, weight in weights.items()
            ),
            8,
        )


__all__ = ["PortfolioConstructionEngine"]