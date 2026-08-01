# Persistent Cash Diagnostic

## Decision status

Phase 1 does **not** authorize a strategy change. The repository artifact contains no production SQLite journals or Render persistent-disk export, so the number of empirically available live cycles in this checkout is **0**. It is therefore not yet defensible to attribute the portfolio's routine cash posture to thresholds, data failure, committee behavior, construction, or execution frequency.

The production path now emits one idempotent `persistent_cash_diagnostic.v1` event after each completed canonical CIO cycle. The event is appended to the existing hash-chained CIO journal and can later be joined to canonical `paper_trade_fill` events. It is diagnostic-only and is deliberately unable to change candidates, specialist output, CIO actions, construction, or execution.

## Protected invariant

The canonical investment strategy, every threshold, CIO-only authority, append-only lineage, fail-closed readiness, point-in-time boundaries, portfolio construction, and paper-only execution remain unchanged. A diagnostic-storage failure is logged after the CIO cycle and cannot change or suppress the immutable cycle result.

## Measured funnel

| Stage | Structured evidence | Phase 1 count source |
|---|---|---|
| Eligible universe | Complete-universe screening publication | `eligible_instrument_count` and instrument observations |
| Decision-eligible instruments | Candidate payloads produced by the screening provider | `candidate_count` |
| Complete evidence | Candidate aggregate score and weakest evidence dimension against the active qualification policy | Per-candidate evidence gate |
| Screening | Persisted opportunity queue | Ranked versus rejected qualifications and reasons |
| Six-specialist analysis | Point-in-time decision snapshot | Exactly six recorded specialist roles |
| Committee synthesis | Complete six-role packet reaching the CIO boundary | Candidate has a six-role snapshot and a CIO decision |
| CIO consideration | Canonical CIO decision | Decision identifier and action |
| CIO qualification | Material CIO action with a governed target | Buy, increase, reduce, or exit |
| Risk-adjusted initial target | CIO recommendation | Positive `recommended_position_weight` |
| Portfolio construction | Construction result | Request identifier, status, constraints, and blocks |
| Nonzero final target | Construction target | Positive symbol target |
| Paper implementation | Canonical internal simulated fill | Joined later by decision identifier; pending at the decision boundary |

## Cash/no-action taxonomy

Every instrument receives a primary reason and zero or more contributing reasons drawn from the requested closed taxonomy:

- no attractive opportunity;
- incomplete or stale evidence;
- provider degradation;
- screening rejection;
- insufficient expected return;
- failure to exceed the cash hurdle;
- downside or tail-risk rejection;
- liquidity or cost rejection;
- specialist concern;
- hidden specialist veto;
- committee aggregation issue;
- CIO rejection;
- construction constraint;
- approved target reduced to zero;
- minimum-position rule; or
- operational or execution failure.

The classifier prioritizes explicit structured vetoes, blocks, actions, and targets. Narrative text is retained as reason evidence and is only mapped into the closed taxonomy; it is never allowed to authorize a decision. An explicit evidence veto is reported as an evidence problem plus specialist concern, not mislabeled as a hidden veto. Hidden veto and committee aggregation findings require the Phase 2 evidence trace.

## How to obtain the first production measurement

After deployment, run:

```bash
python capital_intelligence_cli.py persistent-cash-report \
  --journal-database database/cio_journal.db \
  --report reports/persistent-cash-summary.json
```

Acceptance requires the report's `available_cycle_count` to reconcile the number of new diagnostic events, the CIO journal hash chain to verify, and every all-cash cycle to have a primary reason. A decision-cycle event does not call the absence of a fill an execution failure because execution has not yet occurred at that boundary.

## Deployment, migration, and rollback

- Migration: none. The existing append-only journal accepts a new event-type value; no table or row is rewritten.
- Deployment: restart the canonical scheduler after the code deploy. Existing cycles remain unchanged and are explicitly outside the measured denominator until a governed backfill is designed.
- Rollback: redeploy the prior code. Already-appended diagnostic events remain valid non-authoritative history and must not be deleted.
- Authority: CIO, construction, governance, execution, and real-money authority changed: **no**.

