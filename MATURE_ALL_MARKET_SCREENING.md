# Mature All-Market Screening

## Objective

Allow the platform to discover and evaluate opportunities across classified liquid
public markets without confusing research access with authority to allocate the
portfolio.

The mature path uses three separate gates:

1. **Screening admission** — broad research access.
2. **Committee and CIO research eligibility** — full analytical consideration.
3. **Investment and implementation authority** — unchanged strict authorization.

## Screening admission

A classified instrument may enter preliminary screening when the point-in-time
security master supplies:

- a stable instrument identity;
- an active, unambiguous primary listing;
- point-in-time market metrics available by the knowledge cutoff; and
- a recognized asset-class classification.

Screening admission does not require the market to have completed its full paper
execution, custody, settlement, lifecycle, or construction certification. It also
does not represent a recommendation.

Unclassified instruments remain fail-closed. Instruments with no active listing or
no usable point-in-time metrics are quarantined with an explicit exclusion reason.
By default, one instrument-level metric gap no longer fails the entire screening
cycle.

## Research-only committee and CIO review

The strict recommendation-universe policy is reapplied after candidate creation.
Candidates from markets that are not yet authorized for direct recommendation may
still enter the `exploration` lane when they independently clear all non-authority
controls, including:

- evidence quality and evidence-dimension requirements;
- candidate liquidity scoring;
- downside limits;
- implementation-cost limits;
- scenario and robustness integrity;
- probability and opportunity comparisons; and
- point-in-time opportunity-cost consistency.

The qualification record preserves the original strict universe assessment and its
reasons. Research-only admission therefore cannot be mistaken for investment
authority.

## Investment authority remains strict

No change is made to the CIO's sole investment authority, portfolio construction,
or paper implementation controls. A market that remains intelligence-only or
ineligible under the strict recommendation policy cannot receive a new allocation.
It must first obtain the complete asset-class capability approval covering identity,
market data, valuation, expected return, liquidity, costs, portfolio risk,
execution, custody and settlement, thesis, evaluation, and any required contract,
margin, lifecycle, or roll models.

## Operational behavior

The public `screening` package now defaults to the mature wrappers:

- `FullUniverseScreeningRequest` defaults to instrument-level metric quarantine
  (`require_complete_metric_coverage=False`).
- `FullUniverseScreeningOrchestrator` injects the broad screening-admission builder.
- The screening opportunity engine may route strong non-authorized candidates to
  research-only exploration while preserving strict allocation blocks.

Explicit callers may still inject the original strict builder, strict opportunity
engine, or complete-metric-coverage requirement.

## Governance invariants

This change does **not**:

- lower CIO investment thresholds;
- authorize a new asset class for portfolio allocation;
- change the canonical strategy;
- bypass evidence vetoes or implementation blocks;
- add live-money capability; or
- permit an unclassified instrument to proceed.

It broadens what the organization can investigate while keeping what it can own
strictly governed.
