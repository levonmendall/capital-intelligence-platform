# Capital Intelligence Platform Architecture

## Purpose

The platform is an explainable investment operating system. Deterministic
engines transform versioned evidence into assessments; committee governance
turns assessments into decisions; portfolio policy determines whether and how
an approved decision may be expressed. Generative AI may explain structured
results, but it may not invent observations, silently change scores, override
policy, or choose unconstrained position sizes.

## Bounded contexts

| Context | Owns | Must not own |
| --- | --- | --- |
| `data` and `providers` | Retrieval, normalization, timestamps, provenance, caching | Investment conclusions |
| `economic_regime` | Economic-regime inputs, rules, signals, result | Portfolio allocation |
| `intelligence` | Assessments, forecasts, themes, recommendations, compatibility facades | Collective governance |
| `committee` | Meetings, quorum, weighted votes, vetoes, consensus, final decision | Source-data retrieval |
| `evaluation` | Comparable factor and composite scores | Realized-performance measurement |
| `reporting` | Rendering immutable analytical and decision results | Recalculation of conclusions |
| `history` | Point-in-time evidence, decisions, versions, audit record | Mutation of historical records |
| `analytics` | Returns, attribution, risk, and decision-quality measurement | Ex-ante recommendations |
| `portfolio` | Mandates, constraints, sizing, risk budgets, rebalancing | Analytical score generation |
| `backtesting` | Walk-forward simulation and bias controls | Live order execution |
| `monitoring` | Consecutive-analysis comparison, materiality policy, portfolio-impact direction, alert eligibility | Data retrieval scheduling, notification transport, position sizing |
| `api` and `dashboard` | Application delivery and input validation | Domain rules |

Only contexts implemented in the repository are importable today. The
remaining names are architectural targets and should be added incrementally,
with tests and a real domain contract rather than placeholder packages.

## Dependency direction

1. Domain models and deterministic rules must not depend on the dashboard,
   database, network clients, or report renderers.
2. Providers may depend on external services and normalize their responses into
   domain inputs.
3. Intelligence engines may consume normalized inputs but may not call user
   interfaces.
4. Committee governance consumes immutable recommendations and assessments.
5. Portfolio construction consumes approved decisions plus portfolio state and
   mandate constraints.
6. Reporting consumes results from any layer but never changes them.

Cycles between bounded contexts are prohibited. Cross-context communication
uses explicit immutable models, not shared mutable dictionaries.

## Economic-regime integration

`economic_regime` is the canonical institutional classifier. Its inputs are
normalized to `[-1, 1]`, its rules are deterministic, and its result contains
the regime, confidence, data coverage, component assessments, supporting and
contradicting evidence, signals, and conclusion.

`intelligence.regime.determine_regime` remains the legacy allocation interface.
`intelligence.regime.evaluate_economic_regime` is the compatibility facade for
new consumers. The legacy interface will not be removed until its allocation
consumers have migrated and a deprecation release has been completed.

## Point-in-time data integration

`data` owns strict, immutable observation and provenance contracts. Canonical
observations distinguish provider identity, series identity, observation date,
release time, retrieval time, vintage, frequency, transformation, quality
state, staleness, and point-in-time availability.

The existing `intelligence.observation` models remain the state-engine
compatibility contract. `intelligence.observation_adapter` converts them into
canonical observations only when the caller supplies explicit provenance.
Providers will adopt the canonical contract incrementally; no live retrieval
path is silently changed by this migration.

`data.provider` defines the provider-neutral `ObservationProvider`,
`ObservationQuery`, and `SeriesSpecification` contracts. The canonical FRED
adapter implements that protocol while retaining its legacy value API. FRED
vintage dates are treated conservatively as available at the end of the
provider date; when vintage metadata is absent, retrieval time is used as an
explicit proxy rather than inventing a release timestamp.

`providers.fred_cache` owns FRED response persistence. Request keys exclude
credentials, cache writes are atomic, and records preserve the retrieval time
of the successful response. `FREDRetrievalPolicy` makes freshness, retry, and
stale-if-error limits explicit. Cache use changes the observation quality state
to `cached` or `stale`; it never silently reports fallback evidence as live.

`economic_regime.evidence` is the point-in-time bridge between canonical
observations and the regime classifier. `RegimeEvidenceBuilder` transforms
INDPRO growth, CPI inflation, the real federal-funds stance, Federal Reserve
balance-sheet liquidity, and STLFSI4 stress into bounded scores using a named,
versioned rule set. Each score carries the exact provider observations used in
its calculation. Evidence released after the decision timestamp is excluded.
Inputs are keyed by provider and series identifier, and year-over-year
baselines are chosen nearest the prior-year anniversary within a versioned
tolerance so weekly and monthly frequencies cannot be conflated.

The classifier's statistical confidence and the evidence-quality adjustment
remain separate. Missing inputs reduce coverage; cached, fixture, stale, and
fallback dependencies reduce the evidence-quality multiplier. This prevents a
complete-looking regime result from hiding degraded source quality.

`intelligence.regime_pipeline` is the canonical application service for this
path. It requests frequency-appropriate FRED histories at one decision
timestamp, records a typed load result for every required signal, and passes
only successfully retrieved canonical observations into the evidence builder.
Provider failure never triggers synthetic sample substitution: missing series
remain unavailable, reduce coverage and quality, and are visible on the final
run result. `run_regime.py` is the first explicit institutional entry point;
the older `run_intelligence.py` remains a compatibility workflow.

`data.security` separates issuers, instruments, identifiers, and venue
listings. The instrument model is multi-asset: equities, funds, fixed income,
commodities, FX, and crypto may share identity infrastructure without inheriting
equity-only assumptions. CIK identifies an SEC issuer, not every tradable
instrument. Tickers and crypto pair symbols are venue attributes and must not
be treated as permanent identities. Crypto instruments may identify their
network and contract address without an SEC issuer; spot, futures, and
perpetuals explicitly identify base, quote, and settlement assets.

Trading behavior is explicit. Exchange-session listings and continuously traded
24/7 listings cannot be conflated. A security-master snapshot records when
identities were observed and refuses ambiguous symbol resolution across venues.
Provider feeds may leave asset class and instrument type unclassified when the
source does not supply authoritative classification.

`data.market` owns the provider-neutral multi-asset market-data contract.
Queries are bounded by instrument, venue, data type, time, interval, and result
limit. Canonical records cover quotes, trades, OHLCV bars, corporate actions,
perpetual funding, and derivative open interest. Every record retains provider,
venue, observation time, retrieval time, quality state, and optional provider
identity.

Market records are never consolidated silently. A venue-specific query rejects
records from another venue, and a result batch rejects records unavailable at
the requested decision time. Corporate actions remain separate from raw prices
so adjustment policy can be versioned and audited. The existing
`providers.market_data` latest-quote interface remains a legacy compatibility
surface until its callers migrate.

`data.filing` defines provider-neutral filing queries, filing records, XBRL
facts, and the filing-provider protocol. The SEC EDGAR adapter makes a filing
available at its acceptance timestamp, not its calendar filing date. Company
facts are joined to submission metadata by accession number; facts without a
known acceptance timestamp are excluded from point-in-time results. Original
and amended forms remain distinct records so restatements are never silently
overwritten.

## Committee-governance integration

`committee` owns collective governance. New recommendation-governance callers
use `committee.recommendation_governance`; new end-to-end committee callers use
`committee.workflow.InstitutionalDecisionWorkflow`.

The mature implementation remains in `intelligence` temporarily, behind the
canonical committee facade, so existing imports remain compatible. The
briefing-oriented committee in `committee.meeting` remains a distinct narrative
meeting model and must not be confused with recommendation governance. See
[ADR-0001](docs/architecture/ADR-0001-committee-ownership.md) and the
[canonical decision pipeline](docs/DECISION_PIPELINE.md).

## Decision-discipline integration

`intelligence.decision_discipline` owns thesis lifecycle, falsification
triggers, evidence-trust dimensions, scenarios, and versioned cross-asset
transmission assumptions. Lifecycle changes are append-only transitions:
proposed, active, challenged, invalidated, and closed. Closed theses cannot be
silently reactivated.

`committee.decision_discipline` owns structured minority opinions and formal
no-action decisions. Dissent records the member, specialty, position, evidence,
materiality, and conditions that could resolve disagreement. No action is a
terminal, reviewable committee outcome with evidence, rationale, future action
triggers, and a review date; it is not an omitted decision.

`evaluation.decision_quality` owns retrospective classification. Process
verdict and realized outcome remain separate so a disciplined loss is not
treated as bad process and a lucky gain does not validate flawed process. The
evaluation layer appends reviews to decision history and never rewrites the
original evidence or conclusion.

## Versioning and auditability

Every persisted recommendation and decision should eventually include:

- observation and analysis timestamps;
- provider and series identifiers;
- input snapshot identifier;
- scoring-policy version;
- model or rule-set version;
- committee-policy version;
- code release or commit identifier;
- missing-data and confidence metadata.

Historical records are append-only. Corrections create a new version linked to
the prior record.

`journal.append_only` implements the first institutional persistence boundary
as a separate SQLite event ledger. Regime runs retain acquisition outcomes,
normalized observations, score calculations, lineage, rule versions,
classification, coverage, and quality. Retrospective decision-quality reviews
are appended against their decision identifier rather than modifying the
original record.

## Continuous-monitoring integration

`monitoring.material_change` compares consecutive canonical regime runs and
their governed decisions. It detects regime, recommendation, governance,
evidence-quality, confidence, and signal changes under a versioned materiality
policy. Every comparison produces a typed assessment; notification eligibility
is an explicit output rather than an incidental side effect.

`monitoring.service.ContinuousRegimeMonitor` runs the analytical cycle whenever
an external scheduler invokes it. The assessment sink receives every result,
including silent ones. The alert sink receives only assessments marked
`notify` or `urgent`. Scheduling cadence and delivery channels remain
application concerns and do not alter domain policy.

Portfolio impact is directional and intentionally simple: hold, review,
increase risk, reduce risk, or rebalance. It identifies affected exposures,
including a crypto risk budget where relevant, but cannot choose position
sizes. Actual holdings, mandates, concentration limits, and risk budgets belong
to the future canonical `portfolio` context.

## Decision-card reporting

`reporting.decision_card` builds a `CIODecisionCard` from one canonical regime
run, its governed decision, and an optional material-change assessment. The
card is a presentation contract: it may select and simplify existing fields,
but it cannot score evidence, change confidence, alter governance, or choose a
position size.

The same immutable card renders to schema-versioned JSON, compact Markdown, or
self-contained mobile HTML. The primary surface contains the decision, why it
matters now, and its directional portfolio implication. Supporting evidence,
risks, and review conditions are secondary detail. Because the card is
deterministically derived from journaled inputs, it does not require a separate
source-of-truth persistence model.

Database triggers reject `UPDATE` and `DELETE` operations on journal events.
Every event also includes the prior event hash in a global SHA-256 chain, so
out-of-band database changes are detectable by an integrity scan. This ledger
is intentionally separate from mutable operational tables such as holdings.

## Security and reliability

- Secrets are supplied through environment or secret stores and never committed.
- Provider payloads are untrusted input and require validation.
- Network failures use explicit stale-data or unavailable states.
- A fallback dataset must be labeled; it must never appear as live data.
- Financial actions remain paper-only until authentication, authorization,
  mandate enforcement, idempotency, and an approval boundary are implemented.
- CI must compile domain packages and run the full automated test suite.

## Acceptance rule for new contexts

A new bounded context is accepted only when it has a documented contract,
domain models, deterministic behavior, meaningful tests, compatibility impact
analysis, and no placeholder-only modules.
