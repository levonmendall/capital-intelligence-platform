# Deprecated Personal CIO Compatibility Surface

The Personal CIO product contract is deprecated by [GOVERNING_SPECIFICATION.md](../GOVERNING_SPECIFICATION.md).

Capital Intelligence now applies one institutional investment objective:

> **Maximize long-term compounded portfolio returns.**

Individual goals, target dates, target amounts, retirement plans, income requirements, preferred risk levels, behavioral profiles, and personalized investment philosophies must not influence:

- opportunity detection or ranking;
- expected-return estimates;
- specialist analysis;
- Evidence & Governance review;
- CIO synthesis or action;
- position sizing or portfolio optimization;
- material-change alerts; or
- user-facing investment explanations.

## Compatibility status

Legacy Personal CIO, investor-goal, investment-policy-profile, objective-onboarding, and Investor Memory code may remain temporarily only to support safe data migration and backward-compatible reads.

Compatibility surfaces must:

1. remain isolated from the active investment decision graph;
2. be clearly marked deprecated;
3. avoid creating new decision dependencies;
4. preserve historical records without rewriting them;
5. provide an explicit removal or archival path; and
6. be covered by tests proving they cannot alter a candidate, specialist analysis, CIO decision, portfolio response, alert, or daily briefing.

New development must not add features to these surfaces.

## Retained concepts

The following concepts remain valid after removing Personal CIO behavior:

- authenticated users and roles;
- portfolio and mandate access control;
- append-only institutional decision history;
- conviction or confidence diagnostics derived from evidence and committee analysis;
- opportunity-cost analysis;
- decision-review lessons tied to the institutional process; and
- selective material-change alerts.

A portfolio mandate represents implementation constraints such as liquidity, concentration, leverage, prohibited exposures, turnover, drawdown, and execution feasibility. It does not represent an investor-specific competing objective.

## Replacement terminology

- Personal CIO → Capital Intelligence CIO or Chief Investment Officer
- Investor objective → governing return objective, when referring to the investment process
- Portfolio Alignment → Portfolio Contribution or Portfolio Improvement
- Personal CIO Brief → Daily Capital Intelligence Briefing
- Investor Memory → Decision Review Journal, only when records concern the investment process rather than personal behavior

## Removal plan

The active implementation must be migrated in this order:

1. stop passing goals and investment-policy profiles into briefing, ranking, committee, alerts, and portfolio services;
2. remove goal onboarding and goal-based API writes from primary clients;
3. rename user-facing routes and models around the institutional CIO contract;
4. archive or migrate historical goal records outside the active decision database graph;
5. delete unused Personal CIO domain and route code after compatibility tests and deprecation windows are complete.

Until this work is complete, the legacy code is technical debt and must not be described as a product capability.