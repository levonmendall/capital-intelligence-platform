# Capital Intelligence Platform

**An evidence-governed AI Chief Investment Officer for one $250,000 USD paper portfolio.**

Capital Intelligence continuously converts market, economic, corporate, and event information into point-in-time investment evidence; compares qualified opportunities with cash and existing holdings; and determines whether the portfolio has a better use of capital.

[Open the current Render application](https://capital-intelligence-platform.onrender.com/)

> Every recommendation must be compared with the portfolio’s other available uses of capital, implemented at the portfolio level, monitored against an explicit thesis, and evaluated afterward using the evidence that was available when the decision was made.

The binding product and engineering contract is [GOVERNING_SPECIFICATION.md](GOVERNING_SPECIFICATION.md).

---

## Project contract

| Area | Current project definition |
| --- | --- |
| Objective | Maximize long-term compounded portfolio returns after implementation costs |
| Active portfolio | One canonical portfolio: `COMPOUNDING` |
| Initial paper capital | **$250,000 USD** |
| Decision authority | Six independent specialists advise; only the CIO may authorize an investment action |
| Market scope | Analyze all supported liquid public-market families without treating a static symbol list as the investment universe |
| Allocation scope | Capability-based and fail-closed; an instrument is paper-eligible only when its complete data, evidence, valuation, liquidity, execution, custody, settlement, lifecycle, thesis, and evaluation stack is approved |
| Portfolio sizing | Risk-adjusted initial target followed by portfolio construction; construction may reduce but never increase CIO-approved exposure |
| Product surfaces | Portfolio, Today, Environment, and History |
| Interface | Dark-only, Portfolio-first command system with a collapsible CIO report |
| Execution | Autonomous reconciled paper execution when all controls pass |
| Live money | **Not authorized** |
| Performance claims | No claim of proven alpha or production investment performance |

## What the platform is

Capital Intelligence is designed to operate like a disciplined institutional investment office working continuously on behalf of one governed portfolio.

It:

- observes the financial and economic environment;
- distinguishes useful evidence from general information;
- builds a provider-driven, point-in-time opportunity universe;
- rejects incomplete, stale, unsupported, or economically unqualified candidates;
- obtains six independent specialist analyses;
- gives the CIO sole authority to act, abstain, or reject;
- sizes approved intent at the portfolio level;
- implements only reconciled paper transactions;
- monitors every active investment thesis; and
- evaluates decisions without introducing hindsight data.

It is **not** a personal financial planner, goal-based robo-advisor, financial-news feed, isolated stock-scoring system, social-trading product, or live brokerage platform.

## One objective and one portfolio

The system has one governing objective:

> **Maximize long-term compounded portfolio returns after costs.**

Risk, liquidity, concentration, correlation, factor exposure, turnover, transaction costs, drawdown, data freshness, evidence quality, and execution feasibility are constraints that protect the compounding process. They do not create separate investor goals, strategies, or portfolios.

The only active portfolio code is `COMPOUNDING`. The canonical initial state contains one USD paper portfolio with **$250,000**.

Global equities, rates, credit, cash equivalents, commodities, foreign exchange, crypto, real-estate securities, derivatives, volatility, and other liquid alternatives may be analyzed as possible capital alternatives. They do not become separate growth, income, crypto, tactical, global, or defensive portfolios.

---

## All-market analysis versus paper eligibility

The platform is intentionally broader than its currently executable paper universe.

All supported market families should remain visible to research and opportunity detection. Direct paper ownership is allowed only when the affected instrument has a complete and currently approved capability stack.

| State | Meaning |
| --- | --- |
| Analysis required | The market remains visible to the opportunity process when supported evidence is available |
| Decision eligible | Identity, point-in-time evidence, expected return, liquidity, risk, costs, and governance are complete |
| Paper eligible | Decision eligibility plus approved execution, custody, settlement, lifecycle, reconciliation, thesis, and evaluation capabilities |
| Evidence only | Information may affect environment or cross-asset analysis but cannot directly authorize ownership |
| Fail closed | Missing, stale, degraded, unlicensed, uncertified, or contradictory capability prevents action |
| Prohibited | Live trading and real-money authority |

A provider response, exchange listing, model score, domestic wrapper, or static symbol list is never sufficient approval by itself.

Broad-market ambitions must not be described as completed production coverage. Markets remain research-only, evidence-only, or ineligible until their real provider credentials, licensing, historical coverage, point-in-time behavior, technical binding, and operational certification are present.

See [Data sources and governance](DATA_SOURCES.md), [All-Markets Data Readiness](docs/ALL_MARKETS_DATA_READINESS.md), and [Governed multi-asset expansion](docs/MULTI_ASSET_EXPANSION.md).

---

## Product experience

The application uses four primary surfaces in this order:

### Portfolio — default opening surface

Portfolio is the first screen. It presents the canonical portfolio, capital structure, cash, holdings, live governed marks, P&L, constraints, construction status, and paper implementation lineage.

A collapsed CIO report appears directly beneath the capital structure. Selecting the report row or icon expands the current report without moving the user into a separate workflow.

### Today — what changed and why it matters

Today explains material daily developments through an investment lens:

1. What changed?
2. Why does it matter?
3. Which opportunity or risk emerged?
4. How does it affect the portfolio?
5. Did the CIO decide the portfolio should change?

The surface is not a general news feed. Information is included because it affects economic conditions, expected returns, risk, an active thesis, or the portfolio’s opportunity set.

### Environment — economic and market context

Environment presents certified macroeconomic, cross-asset, market, valuation, liquidity, technical, and event evidence in simplified language.

It may explain implications for the portfolio, but it cannot authorize an investment action. Decision-time evidence and information received after the decision cutoff remain separate.

### History — institutional memory

History contains CIO reports, decisions, dissent, evidence lineage, construction, paper implementation, living-thesis changes, evaluations, attribution, and persistent-cash diagnostics.

The governing records are append-only and point-in-time.

---

## Canonical decision process

```text
Public information and market/economic data
        ↓
Event relevance and portfolio interpretation
        ↓
Provider-driven eligible universe
        ↓
Decision-eligible instruments
        ↓
Complete and current evidence
        ↓
Screening and economic qualification
        ↓
Six independent specialist analyses
        ↓
Committee synthesis with visible dissent
        ↓
CIO consideration and qualification
        ↓
Risk-adjusted initial target
        ↓
Portfolio construction and funding
        ↓
Nonzero final target
        ↓
Reconciled paper implementation
        ↓
Canonical portfolio state
        ↓
Thesis monitoring, history, and evaluation
```

Every stage can stop the process. Valid no-action outcomes include no attractive opportunity, failure to exceed the cash hurdle, insufficient expected return, incomplete evidence, provider degradation, downside risk, liquidity or cost rejection, specialist concern, CIO rejection, construction constraints, or a final position below the minimum-position rule.

Thresholds are not lowered merely to produce activity. Remaining in cash can be the correct governed decision.

## Independent specialist committee

The active investment organization contains six independent specialists and one CIO:

1. Macro & Economic Strategist
2. Market Strategist
3. Cross-Asset Forecast & Scenario Specialist
4. Fundamental & Valuation Analyst
5. Portfolio & Risk Manager
6. Evidence & Governance Officer
7. Chief Investment Officer

The first six specialists analyze the same point-in-time evidence boundary independently. Their conclusions are not averaged into automatic authority.

- Evidence & Governance may reject stale, incomplete, unsupported, or irreproducible evidence.
- Portfolio & Risk may block infeasible or unsafe implementation.
- Dissent and material specialist concerns remain visible.
- Forecasts, model scores, the user interface, construction, execution, and historical learning cannot independently authorize a portfolio change.
- Only the CIO may issue the final action, abstention, or rejection.

## CIO reports

A completed scheduled CIO cycle should persist a same-cycle report containing the relevant environment, evidence, specialist conclusions, dissent, CIO decision, portfolio implications, and construction or implementation outcome.

Expected outcomes are:

- **Completed cycle, no action:** a CIO report explaining why cash or the existing portfolio remains preferable.
- **Completed cycle, action approved:** a CIO report plus the approved target, construction result, and paper-implementation status.
- **Blocked cycle:** a fail-closed status identifying the missing evidence, provider problem, portfolio-state issue, or operational failure; a complete CIO decision report is not manufactured.

A lack of trades is not evidence that the CIO cycle failed.

## Portfolio sizing and construction

Sizing is separated from analytical confidence.

The CIO qualifies an opportunity and produces a risk-adjusted initial target based on expected return, downside, uncertainty, liquidity, costs, and portfolio relevance. The construction engine then evaluates the actual portfolio and may reduce that target when constraints bind.

Construction may:

- process exits and reductions before additions;
- compare a new position with cash and current holdings;
- preserve the required cash reserve;
- reduce only explicitly funding-eligible holdings when replacement edge is sufficient;
- enforce position, sector, factor, correlation, liquidity, turnover, cost, currency, and lifecycle constraints;
- restore unnecessary proposed sales; and
- reduce an approved target to zero when the feasible result is below the minimum-position rule.

Construction cannot increase CIO-approved exposure, change the CIO decision, or create an independent trade.

`SQLiteCanonicalPortfolioStore` is the active authority for cash, holdings, valuation history, P&L, implementation lineage, corporate actions, and reconciled portfolio state.

## Living theses and point-in-time evaluation

Every implemented holding requires a living thesis with:

- the original rationale and expected return;
- investment horizon;
- assumptions and catalysts;
- risks and invalidation conditions;
- monitoring indicators;
- supporting and contradictory evidence;
- evidence lineage; and
- review timing.

The original thesis remains immutable. New evidence creates a new snapshot and may strengthen, weaken, invalidate, or identify a superior replacement. Monitoring may request CIO review but cannot trade.

Evaluation uses the frozen decision package and alternatives known at the original decision time. Later revisions, future-known data, and hindsight alternatives cannot rewrite the original record.

---

## Current data and provider boundary

The repository contains governed paths for official macroeconomic data, corporate filings, market data, reference data, historical research, and paper-broker execution.

Current production configuration includes:

- FRED credentials for macroeconomic and rate evidence;
- SEC EDGAR access with a required descriptive user agent;
- Alpaca paper-trading and IEX market-data endpoints;
- governed secret slots for EODHD and Databento; and
- additional capability and certification workflows for broader institutional and crypto coverage.

Provider availability is not assumed. Each cycle checks freshness, credentials, evidence completeness, quote coverage, portfolio marks, and required certifications. Transient provider resilience may use disclosed bounded retries or approved recent cache behavior, but stale or fallback evidence never masquerades as newly retrieved data.

A weekday production cycle fails closed when required Alpaca readiness, quote coverage, FRED cash evidence, universe discovery, candidate evidence, or holding marks are unavailable.

See [DATA_SOURCES.md](DATA_SOURCES.md) for the authoritative source registry and point-in-time requirements.

---

## Autonomous paper operation

The canonical worker is:

```bash
python capital_intelligence_cli.py run operator
```

Each pass:

1. collects public information and market evidence;
2. checks whether a canonical scheduled slot is due;
3. assembles a fresh production context;
4. executes the CIO cycle only when that context is ready;
5. persists same-cycle reporting and construction records; and
6. attempts exact, authorized, reconciled paper implementation when all controls pass.

Automatic paper execution requires current Alpaca paper credentials, a complete same-cycle CIO report and construction, exact authorization, current universe membership, valid portfolio state, liquidity and quote controls, worker leases, and reconciliation.

The worker does not substitute an old report, stale construction, fixture recommendation, or synthetic opportunity when current evidence is missing.

## Current production schedule

The Render production environment is configured for `America/Los_Angeles` with canonical CIO schedule slots at:

```text
07:00
10:00
12:45
```

The scheduler polls continuously, uses idempotent cycle keys, leases work, and prevents duplicate completed cycles. The first daily cycle key follows this form:

```text
canonical-cio:America/Los_Angeles:YYYY-MM-DD
```

Additional event scanning and an after-close checkpoint are also configured. A scheduled time represents an attempt to assemble current evidence and run the governed cycle; it is not a guarantee that incomplete providers or evidence will be ignored.

---

## Deployment architecture

The canonical Render entrypoint is:

```bash
python run_render_service.py
```

The current Render service is configured as one Standard instance in Oregon with a persistent 5 GB disk mounted at `/app/database`. It deploys from `main` after required checks pass.

The Render supervisor starts:

- the read-only API;
- the critical autonomous CIO and paper operator;
- historical backfill;
- encrypted backup;
- the Streamlit application; and
- the composite-readiness watchdog.

The paper operator is critical. If it exits unexpectedly, the supervisor stops so the hosting platform can restart the service.

Canonical commands and supported topologies are declared in `config/runtime_topologies.json`.

```bash
python capital_intelligence_cli.py topology render
python capital_intelligence_cli.py validate
```

The public hosting health path confirms the Streamlit service is responding. Composite operational readiness additionally depends on the API, operator heartbeat, provider state, portfolio integrity, reconciliation, backups, data freshness, and deployed code identity.

## Production API

Start the read-only API locally:

```bash
python capital_intelligence_cli.py run api
```

Primary institutional endpoints include:

```text
GET /v1/cio/latest
GET /v1/cio/history
GET /v1/cio/decisions/latest
GET /v1/cio/construction/latest
GET /v1/cio/evidence/latest
GET /v1/cio/evaluations/latest
GET /v1/cio/theses
GET /v1/cio/process
```

Operational endpoints include:

```text
GET /health
GET /ready
GET /live
GET /worker/health
GET /operations/slo
GET /metrics
```

The API exposes no live-trade or independent portfolio-allocation route.

---

## Readiness status

The core governed paper architecture is implemented, including:

- one canonical $250,000 portfolio;
- point-in-time evidence and provenance;
- provider and security-master governance;
- opportunity qualification and cash-hurdle comparison;
- six independent specialists and CIO-only authority;
- risk-adjusted initial sizing and portfolio construction;
- append-only CIO, portfolio, thesis, execution, and evaluation records;
- autonomous scheduled paper operation;
- exact authorization and reconciliation controls;
- persistent-cash diagnostics;
- authenticated production surfaces;
- encrypted backup and recovery workflows; and
- deterministic validation, security, and container gates.

This means the repository contains a controlled unattended paper-trading path. It does **not** mean every market is currently certified for direct allocation, every scheduled run will complete despite unavailable providers, or the strategy has demonstrated superior investment performance.

End-to-end production operation remains conditional on:

- the intended commit being deployed;
- valid production credentials and provider entitlements;
- current provider and security-master certifications;
- complete point-in-time candidate and holding evidence;
- healthy canonical portfolio state and reconciliation;
- current backup and operational-readiness evidence; and
- successful out-of-sample paper operation across enough market conditions.

The permanent boundaries are:

```text
real_money_authorized = false
performance_claims_permitted = false
```

---

## Local setup

Python 3.11 is the supported environment.

```bash
git clone https://github.com/levonmendall/capital-intelligence-platform-.git
cd capital-intelligence-platform-

python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python initialize.py
python capital_intelligence_cli.py run ui
```

Windows PowerShell activation:

```powershell
.venv\Scripts\Activate.ps1
```

Provider credentials, database paths, deployment settings, authentication, and paper-execution behavior are environment controlled.

## Validation

Validate the canonical command inventory and run the release suite:

```bash
python capital_intelligence_cli.py validate
python capital_intelligence_cli.py run validate
```

Common development checks:

```bash
python -m compileall -q .
python initialize.py
python run_daily_operations.py --validate-plan
pytest -q --maxfail=1
```

Persistent-cash reporting:

```bash
python capital_intelligence_cli.py persistent-cash-report
```

Container acceptance:

```bash
docker build --target validation -t capital-intelligence:validation .
docker run --rm capital-intelligence:validation
```

## Backup and recovery

```bash
python capital_intelligence_cli.py run backup
python run_backup.py --healthcheck
python run_restore.py backups/<archive>.tar.gz.fernet --verify-only
```

Backup coverage must preserve every active authority needed to reproduce a decision, including evidence, universe eligibility, screening, CIO records, canonical portfolio state, theses, construction, paper execution, evaluations, incidents, SLOs, and readiness reports.

---

## Repository map

```text
app.py                         Portfolio-first Streamlit experience
premium_ui.py                  Dark command-system presentation layer
secure_app.py                  Authenticated application entrypoint
initialize.py                  Canonical initialization and readiness checks
capital_intelligence_cli.py    Supported command gateway
run_render_service.py          Render process supervisor
run_autonomous_paper_operator.py
                               Canonical scheduled CIO and paper operator

cio/                           CIO contracts, synthesis, cycles, persistence
committee/                     Independent specialist analysis
opportunity/                   Eligibility, qualification, comparison, ranking
portfolio/                     Construction, canonical state, paper execution
thesis/                        Living-thesis records and monitoring
evaluation/                    Outcomes, attribution, calibration, cash diagnostics
intelligence/                  Market, economic, event, and educational interpretation
providers/                     Provider adapters and resilience controls
data/                          Point-in-time evidence and security-master contracts
governance/                    Authority, readiness, certification, and safety
operations/                    Scheduling, leases, SLOs, recovery, and incidents
api/                           Read-only institutional and operational API
config/                        Runtime, provider, experiment, and policy manifests
docs/                          Detailed architecture and operating documentation
tests/                         Deterministic behavioral and governance validation
```

## Governing principles

1. One objective: compound the portfolio over the long term.
2. One canonical $250,000 paper portfolio.
3. CIO-only investment authority.
4. Every decision compared with cash and all qualified capital alternatives.
5. Independent specialist analysis with visible dissent.
6. Fail closed on incomplete, stale, degraded, or unsupported evidence.
7. Risk-adjusted initial sizing followed by constraint-aware construction.
8. Construction may reduce but never increase approved exposure.
9. No ownership without a falsifiable living thesis.
10. Append-only lineage and point-in-time evaluation.
11. No thresholds lowered merely to produce trades.
12. No live-money authority and no unearned performance claims.

## Safety statement

Capital Intelligence is a research and governed paper-investment system. It can connect to paper-broker and market-data services, but it cannot authorize or submit live-money trades. Information, forecasts, specialist analysis, the user interface, construction, execution services, and historical learning remain subordinate to the CIO authority boundary and the complete fail-closed control path.
