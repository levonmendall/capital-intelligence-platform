# Business Cycle Intelligence Engine

## Purpose

PR28 adds the second reusable macro engine: a deterministic, point-in-time
assessment of **United States real-economy business-cycle conditions**.

The engine answers a narrow question:

> Is economic activity broadly expanding, mixed or slowing, contracting, or
> under severe stress based on evidence that was available at the decision time?

It is not a recession prediction service. It does not claim to identify market
turning points with certainty, and it cannot independently recommend or execute a
portfolio transaction.

## Shared analytical-engine contract

The engine uses `analytical-engine-result.v1`, introduced by PR27. Every result
publishes:

- engine and policy version;
- point-in-time `as_of` and generation timestamps;
- direction, score, confidence, weighted coverage, and data status;
- evidence with provider, series, observation date, release time, retrieval time,
  vintage, and quality state;
- contradictory evidence and missing-series risks;
- portfolio transmission channels; and
- review conditions.

## Inputs

The first policy version uses:

| Component | FRED series | Interpretation |
|---|---|---|
| Real gross domestic product | `GDPC1` | Sustained real output growth is supportive |
| Industrial production | `INDPRO` | Production growth is supportive |
| Real personal consumption | `PCEC96` | Real demand growth is supportive |
| Nonfarm payroll employment | `PAYEMS` | Employment growth is supportive |
| Unemployment rate | `UNRATE` | A rising unemployment rate is restrictive |
| Initial unemployment claims | `ICSA` | Rising claims are restrictive and can lead labor deterioration |
| Housing permits | `PERMIT` | Permit growth is a leading activity signal |

Each component has a versioned weight, comparison horizon, scoring direction, and
sensitivity in `business-cycle-policy.v1`.

## Outputs

The common directional result is:

- `expanding` — broad expansion or early recovery;
- `neutral` — slowdown or mixed conditions;
- `contracting` — broad activity contraction;
- `stressed` — severe contraction with material labor stress; or
- `unavailable` — no defensible point-in-time conclusion.

The 0–100 business-cycle score is an engine-specific analytical score. It is not
the Capital Intelligence Score and does not change the signature score in PR28.

Data status is reported separately:

- `current`;
- `incomplete`;
- `stale`; or
- `unavailable`.

Missing series reduce weighted coverage and confidence. Stale evidence lowers
quality. Contradictory labor, demand, production, and leading evidence remains
visible in the result.

## Committee and CIO use

The business-cycle result is persisted as point-in-time analytical evidence and is
available to the existing specialist and CIO process. It cannot independently create,
size, authorize, construct, or execute an investment action.

## Scheduling and persistence

Current production scheduling is owned by the canonical headless operating path. The
retired `LiquidityAwareCycleExecutor` and `AnalyticalEngineCycleExecutor` wrappers are
not part of the supported runtime and have been removed. Individual analytical engines,
their append-only stores, read-only API routes, and governed normalization, synthesis,
and evidence-governance records remain supported.

The analytical engine database remains included in encrypted backups, exposed as an
optional readiness component, and protected by append-only update and delete triggers.

## API

```text
GET /v1/business-cycle/latest
GET /v1/business-cycle/history?limit=30
```

The endpoints are read-only and use the same authentication boundary as other
intelligence routes.

## Commands

Run and persist the current engine:

```bash
python run_business_cycle.py
```

Run a historical point-in-time assessment without persisting it:

```bash
python run_business_cycle.py \
  --as-of 2026-01-31T20:00:00Z \
  --no-persist
```

## Validation boundaries

A result must not:

- use an observation released after its decision time;
- present missing or stale evidence as current;
- claim a recession probability, profit probability, or goal-success
  probability;
- alter the Capital Intelligence Score or committee weights in PR28;
- create a new primary dashboard; or
- recommend or execute a transaction by itself.
