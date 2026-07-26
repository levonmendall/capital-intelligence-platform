# Continuous Living-Thesis Monitoring

Every approved ownership decision becomes a `LivingThesis`. The thesis preserves the original rationale and assumptions while allowing later evidence to update its current state through append-only reviews.

## Thesis lifecycle

```text
Candidate
    -> Under Review
    -> Approved
    -> Active
    -> Strengthening / Stable / Weakening
    -> Reduced / Exited / Invalidated
    -> Evaluated
```

The first monitoring implementation operates on Active, Strengthening, Stable, Weakening, and Reduced theses. Exited, Invalidated, and Evaluated theses are terminal for active monitoring.

## Required thesis record

A living thesis contains:

- source CIO decision and candidate identifiers;
- asset;
- creation and latest-update timestamps;
- current state;
- original rationale and assumptions;
- expected return, expected downside, and horizon;
- catalysts and explicit invalidation conditions;
- monitoring indicators;
- initial and current confidence;
- current evidence identifiers;
- performance since approval;
- next review date; and
- review count.

Only Buy, Increase, or Hold decisions can create an active ownership thesis.

## Evidence update

`ThesisEvidenceUpdate` is a new point-in-time challenge to the current thesis. It contains updated expected return, downside, confidence, evidence identifiers, strengthened and weakened indicators, triggered invalidation conditions, data-current status, performance, best replacement expected return, and next review timing.

The update must occur after the current thesis snapshot and must preserve a future review date.

## Monitoring outcomes

`ThesisMonitor` produces a `ThesisReview`, not a final CIO action.

Possible proposals are:

- `continue_monitoring`;
- `review_increase`;
- `review_reduce`;
- `review_exit`;
- `review_evidence`; and
- `invalidate`.

Every proposal other than `continue_monitoring` requires CIO review.

## Classification priority

1. Explicit invalidation conditions take priority and transition the thesis to Invalidated.
2. Stale or incomplete required evidence produces an Evidence review.
3. Materially negative expected return or a decisively superior replacement produces an Exit review.
4. Negative expected return, a materially superior replacement, or material deterioration produces a Reduce review.
5. Material expected-return, confidence, or monitoring-indicator improvement produces an Increase review.
6. Otherwise the thesis becomes Stable and continues monitoring.

A replacement opportunity is evaluated through expected-return edge. This prevents positions from being monitored only against their original thesis while ignoring a stronger available use of capital.

## Append-only state

Applying a review creates a new immutable `LivingThesis` snapshot. It preserves the original rationale, original decision, and creation time while updating current state, expected return, downside, confidence, evidence identifiers, performance, next review, and review count.

The original thesis is never edited in place. Both the review and resulting snapshot are recorded in the canonical CIO journal.

## Authority boundary

Monitoring can detect deterioration, opportunity cost, stale evidence, or invalidation. It cannot issue Buy, Increase, Reduce, Exit, or any other final portfolio action.

The Chief Investment Officer remains the sole final-action authority. Portfolio construction and execution remain separate downstream boundaries.