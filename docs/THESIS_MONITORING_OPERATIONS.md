# Production Thesis-Monitoring Operations

## Governing rule

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

## Authority boundary

Thesis monitoring may:

- schedule a review when `next_review_at` is due;
- react to a material evidence event before the scheduled date;
- obtain a point-in-time evidence update;
- compare the owned thesis with the latest complete opportunity context;
- append a `ThesisReview` and a new immutable `LivingThesis` snapshot;
- place a material proposal into the CIO review queue; and
- publish a selective notification when a publisher is configured.

It may not change a position, resize the portfolio, create an order, submit a trade, or issue the final CIO action.

## Trigger types

- **Scheduled** — automatically generated for reviewable theses whose `next_review_at` is due.
- **Event** — supplied when new evidence, risk, catalyst, invalidation condition, or replacement opportunity appears.
- **Manual** — an explicitly identified operational review request.

Every trigger carries a stable identifier, point-in-time timestamp, reason, priority, and evidence fingerprint.

## Materiality and selective attention

The existing versioned `ThesisMonitoringPolicy` determines whether evidence means:

- continue monitoring;
- review an increase;
- review a reduction;
- review an exit;
- review evidence sufficiency; or
- invalidate the thesis.

A stable review still appends the review and revised thesis snapshot so the operational SLO is satisfied, but it produces no CIO queue item and no user interruption. Action-oriented proposals are prioritized as follows:

- invalidation and exit review — urgent;
- reduction and evidence review — high; and
- increase review — standard unless the initiating event specifies a higher priority.

## Deduplication

The append-only operational store suppresses repeated evidence fingerprints for the same thesis inside the configured window. Replaying the exact trigger repairs missing journal or notification writes without calling the evidence provider again or publishing a duplicate notification.

## Failure behavior

- A missing or integrity-invalid CIO journal blocks the entire cycle.
- A missing thesis, invalid provider result, or provider failure is recorded against that trigger and produces no thesis review or snapshot.
- Independent thesis failures do not erase successful reviews for other theses.
- `--require-all-success` returns a nonzero exit status whenever any requested thesis fails.

## Persistence

`SQLiteThesisMonitoringStore` records trigger receipt, attempts, completed reviews, failures, deduplication, CIO queue items, and notification outcomes in a contiguous SHA-256 event chain. Update and delete operations are blocked by SQLite triggers.

The canonical CIO journal remains the source of truth for `THESIS_REVIEW` and `THESIS_SNAPSHOT` events.

## Run

```bash
python run_thesis_monitoring.py \
  --evidence-provider production_thesis_provider:create_provider \
  --as-of 2026-07-27T00:00:00+00:00 \
  --require-all-success
```

Optional event triggers use a JSON list:

```json
[
  {
    "identifier": "trigger:event:example",
    "thesis_identifier": "thesis:decision:example",
    "source": "event",
    "as_of": "2026-07-27T00:00:00+00:00",
    "reason": "A material replacement opportunity emerged.",
    "evidence_fingerprint": "sha256-or-stable-provider-key",
    "priority": "high"
  }
]
```

A notification publisher is optional. Without one, material CIO-review proposals remain durably queued and the notification outcome is recorded as suppressed rather than silently discarded.

## Remaining production boundary

The orchestration substrate can operate now, but complete full-universe monitoring still depends on a certified active provider, complete point-in-time analytical evidence, and extended paper operation sufficient to measure alert usefulness and false-positive rates.
