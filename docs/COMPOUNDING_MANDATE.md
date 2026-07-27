# Compounding Mandate

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

The platform has one investment mandate. The sole active investment mandate is `COMPOUNDING`.

Its objective is to maximize long-term compounded portfolio returns after implementation costs and within approved operational constraints. Every candidate, current holding, cash position, and qualified alternative is evaluated under that same objective.

## Retired mandates

Preservation, income, balanced, growth, tactical, value, global, and innovation are not active mandates. They may describe historical records, evidence, exposures, or isolated research, but they cannot:

- create a separate decision authority;
- alter opportunity qualification or ranking;
- change the CIO objective;
- determine position size or funding;
- own active portfolio state;
- trigger an alert; or
- appear as an active user-facing portfolio objective.

## Operational constraint profiles

Constraint profiles may specify:

- minimum cash;
- maximum position, sector, factor, or correlated exposure;
- liquidity participation and market-session controls;
- turnover and transaction-cost limits;
- leverage prohibitions;
- drawdown and permanent-capital-loss controls;
- evidence-quality and data-freshness thresholds; and
- restricted instruments or exposures.

These controls govern feasibility, durability, and implementation. They do not create competing portfolio objectives, change opportunity ranking, manufacture a CIO action, or use confidence as a risk budget.

## Canonical portfolio authority

`SQLiteCanonicalPortfolioStore` is the sole active authority for cash, holdings, valuations, and implementation lineage. Construction, rebalancing, paper execution, the authenticated application, the production API, backups, and reporting use that append-only state.

## Compatibility boundary

The retired mandate/trading database may retain historical labels and records for migration audit. It is a query-only migration source and cannot be seeded or mutated by active product paths. Its compatibility configuration contains only the compounding portfolio record.

Authentication routes or database fields that retain the word `mandate` are access-control compatibility surfaces only. They do not select an investment objective or reactivate a retired mandate.

## Production-readiness boundary

The compounding mandate defines how the software makes and evaluates decisions; it does not prove that the process reliably creates value. Production reliance still requires licensed point-in-time provider coverage, complete-universe operation, extended multi-regime paper evidence, resilience evidence at production scale, and formal governance approval. Missing external data or elapsed evidence must remain explicitly blocked or insufficient rather than being fabricated.
