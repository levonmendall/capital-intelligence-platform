# Canonical Daily Intelligence Experience

## Purpose

The daily experience answers one question when the user opens the product:

> What should I know about the market and my portfolio today?

It is an application assembly layer. It does not rescore evidence, change a
committee decision, select an unconstrained position size, or execute a trade.

## Canonical cycle

`application.DailyCapitalIntelligenceService` runs the existing institutional
chain once:

```text
Point-in-time evidence
    -> economic regime
    -> governed committee decision
    -> optional material-change comparison
    -> optional portfolio-fit result
    -> Capital Intelligence Score
    -> Environment Brief
    -> CIO Decision Card
    -> DailyCapitalIntelligenceSnapshot
```

Every opening-screen field shares the same decision timestamp and governed
source identifiers. The dashboard cannot combine a score from one run with an
environment or committee conclusion from another.

## Opening screen

The primary surface remains intentionally small:

```text
Today's Capital Intelligence
82  Strong
Environment: Constructive
Risk: Moderate
Committee: 6-0 Favor Risk Assets
Portfolio impact: Consider holding more diversified risk assets.
What changed?: No meaningful portfolio-relevant change.
```

The four primary application areas are:

1. **Today** — the score, environment, risk, committee, portfolio impact, and
   the simplest explanation of what changed.
2. **Environment** — the concise Environment Brief and supporting economic
   evidence.
3. **Portfolio** — mandate holdings, portfolio context, and paper activity.
4. **History** — score history, Decision Replay entry points, and the paper
   trade journal.

## Honest operating states

Each snapshot discloses one state:

| State | Meaning |
| --- | --- |
| `current` | Evidence is complete and inside the configured freshness window. |
| `incomplete` | The cycle completed, but evidence coverage or quality is limited. |
| `stale` | The result is older than the configured maximum age. |
| `unavailable` | No requested canonical evidence could be loaded. |

A stale, incomplete, or unavailable cycle is never relabeled as current.
Material-change alerts remain controlled by the existing monitoring policy.
Score movement alone does not create an alert.

## History

`SQLiteDailySnapshotStore` keeps an append-only record of completed daily
presentation snapshots. It supports:

- score change from the prior snapshot;
- ordered score history for a restrained trend view;
- material-change and alert status;
- Decision Replay identifiers associated with the cycle; and
- deterministic client payloads for later API delivery.

Database triggers reject update and delete operations. Re-appending the exact
same immutable snapshot is idempotent; reusing an identifier for different
content is rejected.

## Boundaries

- The legacy allocation path remains available for compatibility while callers
  migrate.
- The Streamlit app is the first client of the canonical snapshot service.
- FastAPI, authentication, user-specific delivery channels, and deployment are
  separate application milestones.
- Historical score trends are context, not a trading signal or performance
  promise.
