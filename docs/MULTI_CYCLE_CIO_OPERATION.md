# Multi-cycle CIO operation

## Objective

The CIO continuously monitors markets but changes the portfolio only when a new, evidence-complete assessment identifies a material risk-adjusted improvement. Frequent evaluation must not become frequent trading.

## Production cadence

All times use `America/Los_Angeles`.

| Process | Cadence | Authority |
| --- | --- | --- |
| Runtime operator poll | Every 60 seconds | Operational only |
| Live materiality scan | Every 5 minutes while the regular U.S. market is open | May request a full CIO reassessment; cannot recommend or trade |
| Opening CIO review | 7:00 AM | Full canonical CIO authority |
| Midday CIO review | 10:00 AM | Full canonical CIO authority |
| Pre-close CIO review | 12:45 PM | Full canonical CIO authority |
| After-close opportunity review | 1:15 PM | Research and outcome measurement only; no construction or execution authority |

Public-information collection remains on its governed 30-minute cadence. A newly persisted public record can request a reassessment when it increases the governed record set, but the record itself cannot authorize a trade.

## Initial materiality triggers

The five-minute scanner requests a full canonical review when any of the following occurs:

- VTI or VXUS moves at least 1% from the previous close;
- an active listed wrapper or other active execution-universe instrument moves at least 3%;
- an active individual company moves at least 5%;
- an active symbol moves at least 3% from the price recorded at the last completed full CIO assessment; or
- the governed public-information record count increases after a new collection.

The thresholds are paper-phase controls. The missed-opportunity ledger and decision history should later determine whether they are too sensitive or too slow.

## Deduplication and scheduled guards

A material condition receives a deterministic fingerprint. The same condition cannot repeatedly invoke the committee. Event reviews have a 30-minute cooldown, and event triggers are suppressed for ten minutes before or after a scheduled review.

Each scheduled slot and each event review receives an independent durable cycle key. This preserves idempotency while allowing more than one legitimate decision per market date.

## Decision and execution separation

A reassessment is not a trade instruction. Every scheduled or event-driven review still requires:

- complete point-in-time evidence;
- opportunity comparison against cash and holdings;
- independent specialist review;
- CIO synthesis;
- robust sizing;
- exact funding;
- portfolio construction;
- paper-execution validation; and
- all existing cooldown, materiality, cash, turnover, and instrument limits.

The live scanner has no candidate, ranking, sizing, construction, execution, policy-promotion, or real-money authority.

## After-close learning

The 1:15 PM review resolves matured entries in the append-only opportunity-outcome ledger when later governed prices are available. It classifies missed opportunities, avoided losses, supported gains, and supported losses relative to the contemporaneous cash alternative.

This review cannot publish a construction or create a pending trade. Its output is research evidence for future governed calibration only.

## Failure behavior

- A failed scheduled review remains retryable under the existing lease and retry controls.
- A failed event review releases its trigger fingerprint so it can be retried rather than silently deduplicated.
- A failed materiality scan marks the operator degraded but does not create a trade.
- A failed after-close research review does not affect current portfolio authority.
- Real-money authorization remains false everywhere.
