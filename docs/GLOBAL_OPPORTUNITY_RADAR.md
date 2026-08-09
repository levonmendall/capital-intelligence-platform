# Global Opportunity Radar

## Objective

The Global Opportunity Radar operationalizes the principle that leadership can exist somewhere in the global liquid opportunity set even when the broad market is weak. Its job is to continuously search the complete point-in-time research universe, identify emerging and persistent bull regimes, map them to governed investable exposures, and route research attention into the existing opportunity/CIO process.

It does **not** create a new strategy or authority. The canonical portfolio objective, opportunity thresholds, six-specialist committee, CIO-only decision authority, construction constraints, cash hurdle, fail-closed evidence rules, and paper-only implementation remain unchanged.

## Canonical path

`complete global evidence -> Global Bull-Market & Rotation Radar -> Canonical Exposure Graph -> Persistent Opportunity Sweep -> existing Forward Opportunity Discovery / candidate evidence -> opportunity qualification -> Forward Decision Intelligence -> six specialists -> CIO -> construction -> paper implementation`

## Global Bull-Market & Rotation Radar

Every point-in-time instrument with complete market evidence is evaluated cross-sectionally across four horizons: one month, three months, six months and twelve months.

The radar score combines:

- multi-horizon trend;
- cross-sectional relative strength;
- economic-exposure and asset-class breadth;
- trend acceleration/deceleration;
- persistence across horizons;
- drawdown resilience;
- liquidity; and
- a disclosed price/volatility crowding proxy.

The crowding proxy is not represented as institutional positioning. Certified positioning, derivatives, fund-flow and dealer evidence continues to enter through Forward Research / Forward Decision Intelligence when those feeds are actually configured.

Each instrument is classified as one of:

- `emerging_bull`;
- `confirmed_bull`;
- `mature_bull`;
- `crowded_fragile_bull`;
- `deteriorating`; or
- `bear`.

A high radar score creates research attention only. It cannot make an instrument pass the cash hurdle, opportunity qualification, CIO qualification, or portfolio construction.

## Canonical Global Exposure Graph

The graph provides the governed bridge from economic leadership or causal transmission to actual instruments.

The baseline graph is built only from certified universe metadata:

`instrument -> asset class / economic exposure / country / currency / venue / underlying`

The graph schema also supports explicitly reviewed sector, industry, theme, issuer, product, supplier, customer and commodity relationships. Those relationships must be supplied with point-in-time evidence; they are never guessed from company names, text similarity, or market performance.

This makes the graph safe for second- and third-order opportunity mapping once the corresponding relationship data is activated.

The graph can supply `ResearchExposure` values directly to the existing `ForwardOpportunityDiscoveryEngine`, so event-to-market causal transmissions and non-event market leadership use the same governed research funnel rather than parallel trading logic.

## Persistent Opportunity Sweep

The persistent sweep runs on every complete paper-evidence build. It therefore does not require a discrete news event to discover a rotation.

Emerging, confirmed and mature bull regimes can be nominated for research. Crowded/fragile regimes can still be surfaced, but their research priority is reduced. Deteriorating and bear regimes are not positive research nominations.

A nomination:

- is `research_only`;
- has `authorizes_capital=False`;
- preserves point-in-time market lineage;
- enters the existing forward-intelligence channel as contextual market/forecast evidence;
- does not alter the candidate's pre-committee expected return; and
- cannot bypass opportunity qualification, specialists, CIO authority or construction.

## Production integration

The production paper-evidence facade retains the complete cross-sectional feature set for the duration of one evidence build. After the normal candidate evidence has been constructed, it runs the radar over the full available candidate set and builds the canonical exposure graph from the governed universe.

Every candidate receives its global rank, stage, relative strength and breadth as market evidence. Positive research nominations additionally receive a zero-return-impact Forward Intelligence signal so the existing Market and Cross-Asset Forecast specialists can explicitly consider and challenge the global leadership evidence.

The state is discarded after the cycle. Persistent learning remains downstream in the existing append-only evaluation systems; the radar does not silently rewrite its own policy or CIO thresholds.

## Data boundary

The radar works with whatever markets have complete certified evidence at the cycle timestamp. It does not make an unavailable market investable.

Full global effectiveness still depends on the provider/readiness architecture already defined for global reference data, prices and quotes, fundamentals, fixed income, derivatives, positioning, crypto and alternative/leading data. Missing or stale markets remain fail-closed instead of being scored from fabricated data.
