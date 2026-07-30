# Paper Trading Readiness

## Current classification

Capital Intelligence is operationally ready for persistent, authenticated, fail-closed paper observation. It is not yet decision-complete for unattended autonomous portfolio allocation.

The runtime may collect evidence, run the scheduler, preserve state, record safe abstentions, and maintain encrypted backups. A runtime smoke-test pass must not be interpreted as proof that the system evaluated a complete comparative opportunity set.

## Required decision gates

A full paper-CIO decision is complete only when the production cycle has certified candidate evidence for every qualified candidate, compared those candidates with cash and current holdings, completed all six independent specialist analyses, issued a CIO decision, and either produced an executable construction or an evidence-supported no-superior-opportunity conclusion.

`INSUFFICIENT_EVIDENCE` and `IMPLEMENTATION_BLOCKED` are safe governed outcomes, but they are not evidence that the CIO completed a comparative investment decision.

The active free-data publisher currently excludes instruments that lack certified candidate packets. That is safe, but it means the system must report insufficient evidence rather than claim that no superior opportunity exists.

Before the first autonomous position is opened, a recurring publisher must also certify holding evidence for every resulting position. The production context already requires exact holding coverage and will fail closed when that evidence is absent.

These requirements are release gates, not optional warnings.

## Pilot policy authority

The scheduled CIO construction and paper executor use the same pilot limits:

- minimum cash weight from the versioned free-paper universe;
- maximum batch turnover from that universe;
- the lower of the canonical and pilot single-position limits;
- instrument-specific limits remain enforced by the final execution validator.

## Ten-year historical learning

The ten-year replay is appropriate only as subordinate calibration and governance evidence. It may reduce confidence or position size, but it cannot create a candidate, increase expected return, increase confidence, enlarge a position, authorize execution, or promote policy.

Live calibration requires point-in-time macro coverage, original-decision-horizon outcome alignment, and completed certification. Capability-policy-only outcomes and macro-incomplete cutoffs remain available for audit but are excluded from live forecast, confidence, and sizing calibration.

Ten years do not cover every market regime, security-master change, instrument history, or structural break. Historical learning therefore remains a conservative modifier rather than a primary signal or performance promise.

## Readiness decision

The product is ready for controlled runtime and paper-governance testing. It becomes ready for meaningful unattended paper trading only after real candidate evidence generation and recurring holding-evidence publication are deployed and the stricter production smoke test passes on that release.

Until those evidence publishers are active, the system remains fail-closed and cannot produce a decision-complete autonomous construction from the current free-data production path.

Passing these readiness gates demonstrates process and operational readiness; it does not establish future investment performance.
