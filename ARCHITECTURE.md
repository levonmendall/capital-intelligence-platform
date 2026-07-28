# Capital Intelligence Platform Architecture

## Governing invariant

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

The architecture is organized around authority boundaries. Analytical components may produce evidence and conclusions, but only the Chief Investment Officer may issue a user-facing investment action. Portfolio construction controls sizing and funding. Thesis monitoring may propose review. Evaluation may score process and outcome. None of those layers may silently assume another layer’s authority.

## Investment mandate and constraints

The platform has one active investment mandate: `COMPOUNDING`, meaning maximize long-term compounded portfolio returns after implementation costs. Liquidity, concentration, sector, factor, correlation, leverage, turnover, cash-reserve, drawdown, transaction-cost, evidence-quality, data-freshness, and restricted-instrument rules are operational constraints. They protect implementation feasibility but cannot create competing objectives, change opportunity ranking, or issue CIO decisions.

The mandate owns exactly one USD paper portfolio initialized with $250,000. Global equities, rates, credit, cash, commodities, FX, crypto, real estate, options, volatility, and approved alternatives are possible evidence or exposures inside that portfolio, never separate portfolio authorities.

Preservation, income, balanced, growth, tactical, value, global, and innovation are retired mandate labels. They may remain only in historical migration records or isolated offline research and are not active portfolio authorities.

## Canonical flow

```text
Providers and point-in-time stores
        -> normalized evidence and provenance
        -> analytical engines and company factors
        -> quantitative CandidateDecisionRecord
        -> OpportunityEngine compares every capital alternative
        -> six independent SpecialistAnalysis records
        -> ChiefInvestmentOfficer synthesis
        -> PortfolioConstructionEngine
        -> canonical append-only portfolio state
        -> LivingThesis snapshots and monitoring
        -> DailyCIOBriefing
        -> DecisionEvidenceSnapshot
        -> point-in-time evaluation, attribution, and calibration
```

## Module ownership

| Module | Owns | Must not own |
| --- | --- | --- |
| `data`, `providers` | retrieval, normalization, provenance, point-in-time availability | investment actions |
| `intelligence`, `company`, regime packages | analytical evidence and versioned factor results | candidate eligibility or portfolio size |
| `cio.models` | common candidate, specialist, dissent, and CIO-decision contracts | data retrieval or execution |
| `opportunity` | point-in-time eligibility, qualification, all-market alternative comparison, ranking, rejection | final action or sizing |
| `committee.specialists` | six independent first-pass analyses | user-facing action |
| `cio.synthesis` | final action, disclosed confidence, abstention, thesis approval | broker execution |
| `portfolio.construction_engine` | target weights, funding, costs, liquidity, constraints | changing the CIO action or using confidence as size |
| `portfolio.state` | sole `COMPOUNDING` portfolio, $250,000 starting basis, append-only cash, positions, valuations, and implementation lineage | investment analysis or multiple active portfolios |
| `thesis` | immutable ownership thesis and review proposals | automatic trades or historical rewrites |
| `evaluation` | frozen evidence snapshots, realized comparison, attribution, calibration, walk-forward controls | hindsight inputs or autonomous governance changes |
| `cio.persistence` | append-only hash-chained journal | mutable decision history |
| `reporting.daily_cio` | concise explanation of canonical results | rescoring, reranking, or manufacturing actions |
| `api.routes.cio`, `app.py` | read-only delivery of journal-backed CIO records | legacy fallbacks or decision recomputation |

## Point-in-time evidence boundary

Every material input carries an availability timestamp and source identity. Candidate and cycle timestamps must be mutually consistent. A `DecisionEvidenceSnapshot` freezes:

- the original candidate and scenario assumptions;
- the complete capital-alternative set;
- evidence identifiers and cutoff;
- specialist conclusions, vetoes, blocks, and dissent;
- CIO action and confidence;
- construction and implemented weight;
- thesis and falsification conditions; and
- model, policy, schema, and code versions.

Evaluation rejects evidence or alternatives unavailable at the original decision timestamp. Walk-forward audits require non-overlapping training, decision, and evaluation windows and point-in-time universe eligibility.

## Opportunity authority

The opportunity layer is mandatory before specialist review. It compares candidates with cash, current holdings, and all other supplied alternatives. It applies eligibility, freshness, coverage, liquidity, downside, cost, opportunity-edge, redundancy, and feasibility rules. A candidate may reach the committee only if it represents a plausible superior use of capital.

An empty qualified queue is not an error. It becomes a governed “No superior opportunity” result.

## Specialist and CIO authority

The six specialists complete independent first-pass analyses against the same candidate boundary. They cannot see or average one another’s conclusions before submission. The Evidence & Governance Officer may veto inadequate or irreproducible evidence. The Portfolio & Risk Manager may block infeasible implementation. Dissent remains visible to the CIO.

The CIO alone selects Buy, Increase, Hold, Reduce, Exit, Watch, Insufficient evidence, No superior opportunity, or No material change. Weighted-voter modules remain isolated historical research and cannot be imported by active API, application, or canonical-cycle entrypoints.

## Portfolio construction and state authority

Construction receives approved CIO intents and the actual canonical portfolio state. It:

- applies exits and reductions before additions;
- allocates positive intents in opportunity-rank order;
- uses cash above the reserve first;
- reduces only explicitly funding-eligible holdings when replacement edge is sufficient;
- tests funding transactionally and restores unnecessary sales;
- enforces position, sector, factor, correlation, liquidity, cash, turnover, and cost constraints; and
- emits non-executing paper trade proposals.

Confidence is evidence reliability, not risk budget. It is intentionally absent from the sizing algorithm.

`SQLiteCanonicalPortfolioStore` is the only active authority for cash, holdings, valuation history, and implementation lineage. The retired mandate/trading database is a query-only migration source. Active application, API, construction, rebalancing, paper execution, backup, and reporting paths must not seed, mutate, or treat it as current portfolio state.

## Living-thesis authority

Implemented ownership creates a `LivingThesis`. The original rationale is immutable. New evidence creates a new snapshot and may strengthen, stabilize, weaken, invalidate, or identify a superior replacement. Monitoring may issue a review proposal but cannot change the portfolio without a new CIO decision and construction pass.

## Evaluation authority

Evaluation uses the frozen decision snapshot and later realized outcomes. It requires results for exactly the original alternative set and rejects hindsight alternatives. It separates disciplined process from favorable outcome and reconciles selection, sizing, timing, and implementation costs. Confidence calibration is retrospective evidence for governance review; it cannot automatically rewrite weights, policies, or authority rules.

## Persistence and read models

`SQLiteCIOJournal` is append-only and hash-chained. Updates and deletes are blocked. Events include candidates, opportunity queues, specialist packets, CIO decisions, construction, thesis snapshots and reviews, Daily Capital Intelligence briefings, evidence snapshots, evaluations, calibration, walk-forward audits, and paper fills.

The active API and Streamlit application use a query-only `JournalRepository`. User-facing records include journal sequence and content hash. Missing canonical data produces an honest 404 or no-decision state; delivery code does not synthesize substitutes.

## Product surfaces

The active product has four screens:

1. Today — canonical CIO briefing.
2. Environment — diagnostic evidence only.
3. Portfolio — construction, holdings, constraints, and paper activity.
4. History — briefings, evaluations, theses, and paper records.

The Capital Intelligence Score, conviction trend, Personal CIO, Investor Memory, and retired goal-oriented mandates are not active decision authorities. See [Legacy authority isolation](docs/LEGACY_AUTHORITY_ISOLATION.md).

## Security and execution boundary

Authentication and authorization control data access, not investment objectives. The API opens intelligence and portfolio stores read-only or query-only and exposes no trade mutation endpoint. Containers, dependencies, source scanning, image scanning, backups, restore verification, and operational health checks are enforced in CI and deployment.

The current system is research and paper-only. A future broker layer requires separate approval, idempotency, order policy, pre-trade controls, market-hours checks, realized-cost measurement, incident procedures, and governance authorization. It may not bypass the CIO, construction, canonical portfolio state, thesis, or evaluation boundaries.
