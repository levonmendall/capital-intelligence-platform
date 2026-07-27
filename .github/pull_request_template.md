## Governing rule

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

- [ ] This change preserves that rule across every active path it touches.

## Summary

Describe what changed and why it improves long-term capital compounding.

## Governing specification

- [ ] This change is consistent with `GOVERNING_SPECIFICATION.md`.
- [ ] `COMPOUNDING` remains the sole active investment mandate.
- [ ] Operational constraints remain separate from opportunity ranking and the investment objective.
- [ ] It does not introduce an individual financial goal, retirement target, behavioral preference, or personalized investment philosophy into the investment process.
- [ ] Direct recommendation targets comply with the Version 1 universe policy.
- [ ] Evidence remains point-in-time, traceable, independent, reproducible, certified where required, and explicit about missing or contradictory inputs.
- [ ] Every candidate is compared with cash, current holdings, and all other available qualified alternatives without comparing the candidate with itself.
- [ ] Candidate or decision changes integrate with the common decision schema.
- [ ] Specialist analysis remains independent and specialists do not issue the final user-facing action.
- [ ] Only the CIO issues Buy, Increase, Hold, Reduce, Exit, Watch, or disciplined abstention decisions.
- [ ] No-action, no-superior-opportunity, and insufficient-evidence outcomes remain supported.
- [ ] Position sizing and implementation remain separate from analytical confidence.
- [ ] Canonical portfolio state remains the sole active cash, holdings, valuation, and implementation authority.
- [ ] Approved decisions remain monitorable through explicit assumptions and invalidation conditions.
- [ ] Evaluation uses only the evidence and alternatives available at the original decision timestamp.
- [ ] No legacy score, conviction, goal, mandate, weighted-consensus, or parallel portfolio authority is reactivated.

## Validation

List the complete tests, integration workflows, fixtures, replay checks, point-in-time checks, architecture checks, and security gates used. Explain any failure and the repair rather than omitting it.

## Decision impact

Explain how this change affects opportunity detection, specialist analysis, CIO synthesis, portfolio construction, canonical portfolio state, thesis monitoring, daily briefing, alerts, or evaluation.

## Evidence and version impact

List the source, model, schema, policy, and process versions added or changed. State whether the change creates a new validation sample boundary.

## Compatibility and migration

Document deprecated behavior, data migration, API compatibility, and removal timing. Compatibility code must remain isolated from the active decision graph.

## Production-readiness boundary

State what remains blocked by licensed data, elapsed paper evidence, operational scale, governance review, or separately approved execution. Do not claim production readiness from software tests alone.
