# Forward Decision Intelligence v2

## Purpose

Forward Decision Intelligence v2 is the canonical advisory layer between governed opportunity evidence and the existing six-specialist/CIO process. It asks four questions for every serious candidate:

1. What is likely to happen next?
2. What does the market already expect?
3. What could change the outcome or path before the thesis resolves?
4. Is the probability-weighted opportunity superior to competing uses of portfolio capital?

It does **not** create a seventh specialist, authorize capital, weaken qualification standards, force deployment, or bypass portfolio construction. CIO-only authority, fail-closed evidence, paper-only execution, point-in-time lineage, and independent construction remain unchanged.

## Canonical dimensions

Every candidate context classifies all of the following dimensions as `available`, `partial`, `unavailable`, or `not_applicable` according to an asset-class applicability matrix:

- economic / liquidity / credit / policy / market regime;
- fundamental trajectory;
- market expectations versus governed internal expectations;
- catalysts and scheduled events;
- earnings-event expectations for applicable equities;
- derivatives and options-implied information;
- flows, ownership, crowding, leverage and positioning;
- cross-asset confirmation or contradiction;
- liquidity and market microstructure;
- reflexivity and forced-flow risk;
- structural/value-chain transmission;
- corporate actions;
- real-world and alternative leading indicators;
- path, drawdown and time risk;
- portfolio opportunity cost and competing uses of capital;
- forecast calibration and learning.

Unavailable evidence is never fabricated. A missing applicable domain is explicitly recorded as unavailable and remains visible to the Evidence/Governance specialist.

## Expectations and catalysts

The centerpiece is the expectations gap: the system distinguishes whether an outcome is objectively favorable from whether it is favorable **relative to what the market appears to price**. The same contract applies to earnings, inflation, central-bank decisions, inventories, product launches, regulatory decisions, elections, protocol changes, and other material events.

Known catalysts can carry a probability-weighted scenario distribution. Events inside a configurable window are classified as an event cluster so the Market, Cross-Asset Forecast, and Portfolio/Risk specialists can challenge interaction risk rather than treating each event independently.

## Distribution and timing

A governed return distribution can record expected and geometric return, probabilities of positive return / beating cash / beating the best alternative, expected maximum drawdown, tail loss, and return percentiles. This supplements rather than replaces the existing canonical CIO economics.

Decision timing is explicitly advisory: `act_now`, `wait_for_event`, `reassess`, or `no_timing_edge`. Timing cannot itself issue a BUY, INCREASE, REDUCE, or EXIT action.

## Thesis monitoring

An approved thesis can identify what must remain true, what evidence should be monitored, and which conditions invalidate the thesis. This makes background monitoring candidate-specific instead of treating all news as equally important.

## Six-specialist routing

The common context is routed differently to the existing roles:

- **Macro & Economic:** regime, expectations, macro catalysts, cross-asset and structural transmission.
- **Market Strategist:** expectations, catalysts, derivatives, positioning, cross-asset confirmation, microstructure and reflexivity.
- **Cross-Asset Forecast:** the complete forward packet, event interactions and distribution evidence.
- **Fundamental & Valuation:** fundamentals, expectations, earnings, catalysts, structural transmission, corporate actions and leading indicators.
- **Portfolio & Risk:** catalysts, derivatives, positioning, microstructure, reflexivity, path risk and portfolio opportunity cost.
- **Evidence & Governance:** all dimensions, evidence coverage, missing domains and calibration.

The v2 context only adds evidence, assumptions, risks, change conditions, limitations, lineage and advisory narrative. It does **not** directly change specialist expected-return impact, position, confidence, scenario adjustments, CIO thresholds, or construction limits. Quantitative economic changes continue to require the existing governed `ForwardSignal` / `ForwardScenario` contracts.

## Asset-class applicability

A common packet is retained across equities, ETFs, fixed income, commodities, FX, crypto, real estate, futures, options, volatility, alternatives and cash equivalents, but irrelevant dimensions are explicitly `not_applicable`. This prevents an FX candidate from failing because it has no earnings date while still requiring relevant regime, expectations, derivatives, positioning, cross-asset, path-risk and portfolio evidence.

## Production persistence

`ForwardDecisionContext` is serialized inside the existing `ForwardIntelligenceBundle`. Its evidence identifiers are included in the bundle lineage so production storage, replay and historical evaluation preserve the exact information available at the decision timestamp.

The active production-context reconstruction must pass persisted forward intelligence into `CandidateCycleContext`; otherwise stored forward evidence would not reach specialist synthesis. v2 treats this as a required runtime invariant.

## Provider boundary

The contracts support earnings calendars, consensus/dispersion, options surfaces and flow interpretation, institutional positioning, alternative data, corporate actions, macro-event expectations and other sources when certified data is present. The code does not invent provider subscriptions, credentials, coverage, buyer/seller classification, dealer Greeks, consensus estimates or historical observations. Missing data remains unavailable until governed collection and certification supply it.
