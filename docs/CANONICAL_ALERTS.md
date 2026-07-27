# Canonical CIO Alerts

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

The active notification system is event-driven. It does not alert on a score, score delta, committee vote, conviction trend, or personal objective.

## Event topics

Accounts may subscribe to six canonical topics:

- `cio_decision` — a final CIO action or abstention;
- `thesis` — a living thesis is created, materially reviewed, weakened, invalidated, or compared with a replacement;
- `opportunity` — the complete qualified opportunity set changes or no superior use of capital exists;
- `implementation` — portfolio construction or paper implementation is feasible, partial, blocked, failed, or reconciled;
- `evidence` — decision-time evidence is frozen, becomes stale, conflicts, or fails an integrity/SLO gate; and
- `daily_briefing` — the journal-backed Daily Capital Intelligence briefing.

Every alert preserves the source event identifier and evidence references. Delivery preferences select event topics and channels only. There is no confidence-change threshold.

## Production flow

After `CanonicalCIOCycle` succeeds, `ScheduledCanonicalCIOWorker` translates the immutable cycle result into canonical events. `AlertDeliveryService` applies account topic/channel preferences, persists deduplicated deliveries, and records suppressed events and delivery attempts. Alert failure is retryable and cannot modify the CIO decision, thesis, construction, or evidence.

Legacy score and conviction alert models remain compatibility-only for archived rows and offline tests. They are not used by `run_scheduler.py`, the authenticated preference API, or the active UI.
