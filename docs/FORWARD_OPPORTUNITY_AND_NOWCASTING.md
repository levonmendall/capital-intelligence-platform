# Forward Opportunity Discovery and Nowcasting

## Purpose

This layer completes the forward-looking research path around Forward Decision Intelligence v2 without creating a seventh specialist or any new investment authority.

Canonical path:

`global information -> event/change detection -> causal transmission -> forward opportunity hypotheses -> existing opportunity qualification -> Forward Decision Intelligence v2 -> six specialists -> committee synthesis -> CIO -> construction -> paper implementation -> calibration and missed-opportunity learning`

## Forward Opportunity Discovery

`ForwardOpportunityDiscoveryEngine` consumes an already governed `EventMarketAssessment` and an explicitly mapped set of eligible investable exposures. It converts causal transmissions into ranked research hypotheses. It does not infer an instrument from a name or ticker and cannot authorize capital. Every hypothesis is marked `research_only=True` and `authorizes_capital=False`; it must enter the existing qualification funnel before specialist or CIO consideration.

The repository does not currently maintain a canonical exposure-to-instrument taxonomy for generic causal targets such as `commodity_consumers` or `growth_equities`. The discovery engine therefore requires an explicit governed `ResearchExposure` mapping rather than inventing securities from text. This is intentional: adding a guessed mapping would silently broaden the investable universe and create false research candidates.

## Certified expectations intelligence

`ExpectationsIntelligenceEngine` accepts point-in-time observations for analyst EPS/revenue expectations, revisions, dispersion, company guidance, macro consensus, policy probabilities, yield/inflation expectations, options-implied expectations, credit-implied expectations, commodity curves and event probabilities.

When certified observations exist, they enrich the canonical expectations-gap dimension. When they do not exist, the current disclosed price/flow expectations proxy remains the fallback rather than fabricating consensus evidence.

Provider-neutral landing-zone dataset types are available for `expectations` and `event_expectations` so future certified providers do not leak vendor schemas into decision contracts.

## Governed nowcasting

`GovernedNowcastingEngine` combines point-in-time leading observations into probabilistic pre-release estimates for CPI, payrolls, GDP, retail sales, industrial production, company revenue/earnings/margins, inventories and commodity supply/demand.

Nowcasts are evidence, not decisions. They carry uncertainty, confidence and source lineage and enrich the existing `leading_alternative_data` dimension only for asset classes where that dimension applies.

Provider-neutral landing-zone support is available through the `leading_indicators` dataset type.

## Institutional positioning and derivatives

The existing market-flow proxy remains available, but `PositioningIntelligenceEngine` can now consume certified ETF/fund flows, futures positioning, short interest, borrow utilization/cost, options volume/open interest/opening-closing/skew/term structure, dealer gamma/vanna/charm, CTA positioning, volatility-control exposure, cross-border flows and crypto funding/open-interest/liquidation evidence.

Certified evidence upgrades the positioning dimension and, when derivative evidence is present, the derivatives dimension. Missing institutional feeds remain explicitly unavailable/partial rather than being inferred from price and volume.

Provider-neutral dataset types are `positioning` and `derivative_positioning`.

## Quantitative value of waiting

`ValueOfWaitingEngine` compares the expected value of acting now with waiting for information resolution using:

- expected return available now;
- downside exposed while uncertainty is unresolved;
- probability that the event resolves uncertainty;
- upside likely lost while waiting;
- expected post-event entry drag;
- transaction costs;
- alternative return while capital waits;
- thesis decay.

The result maps to the existing advisory timing postures (`act_now`, `wait_for_event`, `reassess`). It cannot issue an order or override qualification, CIO or construction. The calculation activates only when a governed caller supplies point-in-time `ValueOfWaitingInputs`; the system does not invent event-resolution probabilities or post-event entry costs when those inputs are absent.

## Production persistence and configured providers

`build_predictive_market_intelligence` accepts optional `ForwardResearchEvidence`. Certified research evidence enriches the existing `ForwardDecisionContext`, persists through the existing `ForwardIntelligenceBundle`, joins evidence lineage, and is routed through the same six-specialist advisory path.

`ConfiguredForwardResearchProvider` uses the repository's existing configuration-driven dataset transport. A binding referenced by `CAPITAL_INTELLIGENCE_FORWARD_RESEARCH_DATASET_BINDING` can activate any configured combination of expectations, event expectations, positioning, derivative positioning and leading-indicator datasets without adding vendor-specific schemas to investment logic.

The active `production_paper_evidence` facade creates this provider at the start of each production evidence build. When configured, each candidate receives certified research evidence before the predictive/FDI bundle is persisted. A configured feed that fails retrieval or validation fails closed; when no binding is configured, the provider remains absent and the current proxy/unavailable behavior is unchanged.

Provider interfaces are production-wired, but the code does not claim that external consensus, dealer, institutional-flow or alternative-data subscriptions exist until an actual certified binding and credentials are supplied.

## Governance invariants

This work does not:

- add a specialist or voting engine;
- change CIO-only investment authority;
- create a trade directly from an event or hypothesis;
- lower screening or CIO qualification thresholds;
- weaken the cash hurdle;
- bypass independent portfolio construction;
- permit live-money execution;
- use information not available at the decision timestamp;
- automatically change policy from later outcomes.

Calibration, decision learning and missed-opportunity learning remain downstream governance/evaluation systems and do not silently rewrite current policy.
