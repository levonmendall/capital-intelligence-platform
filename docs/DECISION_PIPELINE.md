# Canonical Institutional Decision Pipeline

## Scope

This document defines the target sequence from evidence to portfolio action.
The point-in-time regime path is now orchestrated from canonical evidence
through recommendation governance and append-only recording. Other
unimplemented segments are contracts for future milestones, not claims of
production readiness.

## Sequence

1. Providers retrieve source data and attach provenance.
2. Normalization creates point-in-time observations.
3. Deterministic engines publish typed assessments.
4. Forecasting produces scenarios without changing historical observations.
5. Themes and theses connect evidence to investable implications.
6. Recommendation rules create immutable recommendations.
7. Specialist committee members form independent assessments and opinions.
8. Committee governance applies quorum, weights, vetoes, and policy.
9. Reporting and statistics describe the same final decision.
10. Portfolio construction applies mandate and risk constraints separately.
11. History records inputs, versions, votes, decisions, and outcomes.

## Implemented orchestration boundary

`committee.workflow.InstitutionalDecisionWorkflow` owns steps 7–9 for a single
`InvestmentRecommendation`:

```text
InvestmentRecommendation
    -> RecommendationInvestmentCommittee
    -> RecommendationCommitteeDecision
    -> InvestmentCommitteeReport
    -> CommitteeStatistics
    -> InvestmentCommitteeResult
```

The result enforces that the report references the same decision and that the
workflow timestamp is timezone-aware.

## Regime governance boundary

`committee.regime_governance.RegimeGovernanceWorkflow` connects the canonical
`InstitutionalRegimeRun` to that implemented committee boundary:

```text
InstitutionalRegimeRun
    -> evidence coverage / quality / confidence gates
    -> InvestmentRecommendation
    -> InstitutionalDecisionWorkflow
    -> approve / modify / reject / escalate / no action
    -> append-only journal
```

The adapter produces a macro recommendation; it does not produce portfolio
weights or orders. A failed evidence gate creates a typed `NoActionDecision`
with a review date and action triggers. Material open dissent is retained and
escalates an otherwise valid committee result instead of being averaged away.

## User-facing decision card

`reporting.decision_card` consumes the completed regime run, governed decision,
and optional material-change assessment. It produces one immutable
`CIODecisionCard` and deterministic JSON, Markdown, and HTML representations.

The card intentionally separates the primary answer from supporting detail:

1. What should I do?
2. Why does it matter now?
3. How could it affect the portfolio?
4. What evidence, risks, and conditions sit behind the answer?

Reporting cannot change a score or decision. Mandate-aware sizing remains a
separate portfolio responsibility.

## Portfolio-fit boundary

`portfolio.PortfolioFitGate` implements the first portion of step 10:

```text
Approved committee decision
    + proposed portfolio expression
    + point-in-time portfolio snapshot
    + versioned mandate
    -> fit / smaller / replace / blocked / no budget / no action
```

The proposed expression is separate from the analytical recommendation. The
gate can cap a requested weight under explicit constraints, but it cannot
create an order or mutate holdings. Every result can be appended to the
institutional journal and passed to the CIO decision card.

## Non-negotiable boundaries

- Recommendations never execute trades.
- Reports never recalculate or alter decisions.
- Committee approval never bypasses portfolio constraints.
- Portfolio sizing is not a direct transform of an analytical score.
- AI-generated prose never changes deterministic scores or policy.
- Missing or stale data remains visible through confidence and coverage.
- Historical records are append-only and retain the versions used at decision
  time.

## Compatibility

The legacy `intelligence.pipeline` remains the current market-snapshot and
allocation path. It is not silently redirected to the institutional workflow.
Migration requires explicit input adapters, allocation-policy tests, and a
release note because the two flows currently use different regime labels and
decision contracts.
