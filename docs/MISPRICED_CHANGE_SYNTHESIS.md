# Governed Mispriced-Change Synthesis

The platform already discovers candidates using point-in-time value, momentum, carry,
and improving-condition evidence, then requires asset-appropriate valuation or return-
driver evidence before the six specialists and CIO act. This layer adds the missing
cross-domain question: **is the market price failing to fully reflect an important change
in the asset's forward economics?**

## Decision path

```text
complete investable universe
→ provider-enriched value / momentum / carry / improving-condition preselection
→ complete candidate evidence and applicable valuation / return-driver analysis
→ forward evidence (trend, business economics, expectations, catalysts, regime, payoff)
→ mispriced-change interaction synthesis
→ existing six independent specialists
→ existing CIO qualification and cash / best-alternative comparison
→ existing portfolio construction and paper implementation
```

The synthesis does not create candidates, expand the eligible universe, lower screening
or CIO thresholds, issue portfolio actions, size positions, bypass evidence governance,
or authorize real money. Its only quantitative handoff is a bounded interaction residual
to the existing cross-asset forecast specialist. The underlying standalone trend,
fundamental, macro, and valuation effects are not re-added.

## What “future-state valuation” means

A security is not considered attractive merely because a trailing multiple is low. The
synthesis asks how much of a governed change in demand, margins, market share, capacity,
or other forward economics appears already reflected in price. A high trailing multiple
can therefore coexist with an attractive future-state setup when improving economics are
credible and insufficiently priced. Conversely, an apparently cheap asset is classified
as **value-trap risk** when business economics or trend evidence is deteriorating.

## Interaction dimensions

The v1 policy evaluates seven independently traceable dimensions: trend persistence,
future-state valuation, fundamental acceleration, expectations/revision gap, catalyst
support, regime fit, and payoff asymmetry. Missing evidence remains missing; the layer
does not substitute a neutral or synthetic value. Evidence coverage and evidence-origin
independence reduce confidence when the thesis relies on too few domains or repeatedly
counts the same upstream fact.

A **strong mispriced-change** state requires positive alignment among trend, future-state
valuation, and fundamental acceleration, sufficient cross-domain coverage, adequate
evidence independence, and no material negative expectations contradiction. A strong
trend without fundamental/future-state support is classified as **momentum only** rather
than automatically promoted. A cheap-looking setup with deteriorating trend or economics
is classified as **value-trap risk**.

## Governance and return adjustment

The synthesis interaction adjustment is hard-capped at +/-3 percentage points. It is an
interaction term only: the existing forward engines retain primary responsibility for
standalone expected-return effects. Mixed or incomplete synthesis produces no numerical
adjustment. Positive or negative interaction evidence is still challenged by the existing
cross-asset forecast specialist and remains subject to all current CIO, cash-hurdle,
portfolio-risk, liquidity, cost, construction, minimum-position, reconciliation, and
paper-only controls.

All synthesis evidence identifiers are inherited from the already-governed point-in-time
forward packet. No new unlineaged evidence is manufactured by this layer.
