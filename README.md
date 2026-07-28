# Capital Intelligence Platform

**A dark-first, evidence-governed AI Chief Investment Officer for one $250,000 USD paper portfolio.**

Capital Intelligence continuously analyzes supported liquid public markets, compares every qualified opportunity with cash and current holdings, and determines whether the portfolio has a better evidence-supported use of capital.

The software does not execute live trades.

[Open the current Streamlit experience](https://dgmb3pd9uzhv2jmruwqeub.streamlit.app)

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

That rule governs the product. A security is never evaluated in isolation, analytical confidence never becomes position size, ownership never exists without a falsifiable thesis, and retrospective evaluation never substitutes hindsight data for the original decision package.

The binding product and engineering contract is [GOVERNING_SPECIFICATION.md](GOVERNING_SPECIFICATION.md).

---

## Project at a glance

| Area | Current project contract |
| --- | --- |
| Objective | Maximize long-term compounded portfolio returns after implementation costs |
| Active portfolio | One portfolio: `COMPOUNDING` |
| Initial paper capital | **$250,000 USD** |
| Market scope | Required analysis across all supported liquid public-market families |
| Allocation scope | Direct paper allocation only after instrument-level capability approval |
| Decision authority | Five independent specialists plus one Chief Investment Officer |
| Portfolio sizing | Construction and funding logic; CIO confidence is not a sizing input |
| Product surfaces | Today, Environment, Portfolio, and History |
| Interface | Signature command-system design with dark mode as the preset and light mode as an alternate |
| Execution | Research and paper only; no broker submission or live-money authority |
| Readiness | Core architecture is implemented; controlled paper testing still requires production data, burn-in, resilience evidence, and formal governance approval |

## What the platform is

Capital Intelligence is designed to behave like a disciplined institutional investment office working continuously on behalf of one portfolio.

It:

- observes the global financial system;
- converts raw information into point-in-time evidence;
- identifies and ranks possible uses of capital;
- evaluates qualified opportunities through independent investment disciplines;
- produces a final CIO decision, including abstention;
- constructs a feasible portfolio-level implementation;
- monitors every active ownership thesis; and
- evaluates decisions using the information that was actually available at the time.

It is **not** a financial planner, personal-goal robo-advisor, financial-news feed, isolated stock-scoring tool, social trading product, or live brokerage system.

## One objective, one portfolio

The sole governing objective is:

> **Maximize long-term compounded portfolio returns.**

Risk, liquidity, concentration, correlation, factor exposure, turnover, costs, leverage, drawdown, data freshness, evidence quality, and implementation feasibility are protective constraints. They do not create competing portfolios or user-selected investment philosophies.

The only active portfolio code is `COMPOUNDING`. Initialization creates exactly one USD paper portfolio with **$250,000**. Valid but incompatible legacy portfolio databases are archived before the active state is reset.

Global equities, rates, credit, cash, commodities, foreign exchange, crypto, real-estate securities, options, volatility, futures, and other approved alternatives are analyzed as possible evidence or exposures inside this one portfolio. They never become separate growth, income, crypto, tactical, global, or defensive portfolios.

## All-market analysis and governed allocation

Market availability does not create recommendation authority.

| State | Meaning |
| --- | --- |
| Required analysis | All supported liquid public-market families must remain visible to the opportunity process |
| Governed paper allocation | A classified instrument may be allocated only after its complete point-in-time capability stack is approved |
| Core policy eligible | Plain, liquid U.S.-listed equities and ETFs, cash, and short-duration U.S. Treasury equivalents |
| Capability governed | International equities, broad fixed income, commodities, FX, crypto, real estate, derivatives, volatility, alternatives, and complex wrappers |
| Fail closed | Missing identity, data, valuation, liquidity, execution, custody, settlement, lifecycle, thesis, evaluation, or governance capability |
| Never authorized here | Live trading, broker submission, or real-money authority |

The active universe is provider-driven and point-in-time. A static symbol list, exchange listing, provider response, model score, or domestic wrapper is never sufficient approval by itself.

See [Governed multi-asset expansion](docs/MULTI_ASSET_EXPANSION.md).

---

## Signature product experience

The Streamlit product is intentionally limited to four primary screens. The presentation is dark-first and uses a custom command-system layer rather than a generic dashboard layout.

### Today — Decision command console

The daily CIO surface answers:

1. What changed?
2. Why does it matter?
3. What opportunity or risk emerged?
4. Should the portfolio change?
5. How confident is the governed conclusion?

When no qualified opportunity or complete CIO record exists, Today displays an honest standby or no-action state rather than manufacturing a recommendation.

### Environment — Market telemetry field

Environment presents certified macroeconomic and market evidence. It is diagnostic and cannot issue an investment action. Decision-time evidence and observations received after the cutoff must remain separate so the interface never creates a hindsight view.

### Portfolio — Construction engine

Portfolio shows the sole canonical portfolio, capital deployment, holdings, cash, construction status, costs, constraints, paper trades, and value history. Construction determines feasible sizing and funding but cannot change the CIO decision or submit an order.

### History — Institutional decision memory

History exposes canonical CIO briefings, living theses, evaluations, attribution, calibration, and paper activity. The underlying journal is append-only and hash-chained.

Run the authenticated interface:

```bash
streamlit run secure_app.py
```

The presentation system lives in `premium_ui.py`. Dark mode is the configured default; users may switch to the alternate light appearance without changing any investment or data behavior.

---

## Canonical decision process

```text
Certified point-in-time evidence
        ↓
Provider-driven eligible universe
        ↓
Complete capital-alternative comparison
        ↓
Qualification and opportunity ranking
        ↓
Five independent specialist analyses
        ↓
CIO synthesis, dissent, veto, or abstention
        ↓
Portfolio construction and funding
        ↓
Reconciled paper implementation
        ↓
Living-thesis monitoring
        ↓
Point-in-time evaluation and attribution
```

A failure, incomplete universe, stale evidence, unresolved disagreement, implementation block, or weak opportunity edge can stop the process. “No superior opportunity” and “No material change” are valid governed outcomes.

Older regime-allocation, weighted-committee, score-first, personal-goal, Investor Memory, conviction-trend, and multiple-mandate workflows are not active decision authorities.

## Independent specialist committee

The active investment organization contains:

1. Macro & Economic Strategist
2. Market Strategist
3. Fundamental & Valuation Analyst
4. Portfolio & Risk Manager
5. Evidence & Governance Officer
6. Chief Investment Officer

The first five complete independent first-pass analysis against the same evidence boundary. They do not see or average one another’s conclusions before submission.

- Evidence & Governance may veto inadequate, stale, or irreproducible evidence.
- Portfolio & Risk may block an infeasible implementation.
- Dissent remains visible.
- Only the CIO issues the final user-facing investment action.

## Portfolio construction

The construction engine receives approved CIO intent and the actual canonical portfolio state. It:

- applies exits and reductions before additions;
- allocates positive intents in opportunity-rank order;
- uses cash above the required reserve first;
- reduces only explicitly funding-eligible holdings when replacement edge is sufficient;
- tests funding transactionally and restores unnecessary sales;
- enforces position, sector, factor, correlation, liquidity, cash, turnover, cost, and currency constraints; and
- emits non-executing paper trade proposals.

CIO confidence measures evidence reliability. It is intentionally absent from the sizing algorithm.

`SQLiteCanonicalPortfolioStore` is the sole active authority for cash, holdings, valuation history, and implementation lineage.

## Living theses and evaluation

Implemented ownership requires a living thesis containing:

- original rationale and expected return;
- investment horizon;
- assumptions and catalysts;
- risks and invalidation conditions;
- monitoring indicators;
- supporting and contradictory evidence;
- evidence lineage and confidence; and
- review timing.

The original thesis is immutable. New evidence creates new snapshots and may strengthen, stabilize, weaken, invalidate, or identify a superior replacement. Monitoring may request CIO review but cannot trade autonomously.

Evaluation uses the frozen decision-time package and the original alternative set. Multi-asset attribution separates local return, currency translation, interaction, implementation cost, and total base-currency contribution. Hindsight alternatives and future-known information are rejected.

## Forecasting boundary

Forecasts are supporting evidence, not an independent decision authority.

A governed forecast preserves its target, horizon, knowledge cutoff, model and data versions, scenario probabilities, uncertainty, calibration method, historical accuracy, source lineage, limitations, and invalidation conditions.

A forecast cannot create a candidate, alter ranking, size a position, issue a CIO action, or bypass market-governance requirements.

---

## Current readiness

The core institutional CIO architecture is implemented as software. The repository includes:

- point-in-time evidence and provenance contracts;
- provider and security-master certification controls;
- complete-universe publication and screening requirements;
- candidate qualification and capital-alternative comparison;
- five independent specialists and CIO-only action authority;
- portfolio-level construction and funding;
- one append-only canonical portfolio-state source;
- append-only CIO, thesis, construction, execution, and evaluation history;
- continuous thesis-review orchestration;
- point-in-time attribution and confidence calibration;
- a read-only institutional API;
- a fail-closed twelve-stage daily operation;
- authentication, authorization, backups, restore verification, SLOs, incident evidence, and resilience controls; and
- deterministic CI, CodeQL, dependency audit, and container security gates.

The project is **not yet approved as a production investment manager or for live-money execution**. Controlled paper testing still requires one immutable baseline with:

- reviewed production stage bindings and licensed provider credentials;
- complete production-grade point-in-time market coverage for every approved asset class;
- verified backup and recovery coverage for every active authority;
- successful multi-day operating burn-in;
- production-scale outage, corruption, takeover, recovery, and reconciliation exercises;
- sufficient out-of-sample decisions across market regimes;
- zero unresolved critical integrity or reconciliation failures; and
- formal human governance approval.

Every readiness report preserves:

```text
real_money_authorized = false
performance_claims_permitted = false
```

A running application, API, worker, or successful single-day cycle does not prove paper-test readiness.

---

## Local setup

The supported local environment is Python 3.11.

```bash
git clone https://github.com/levonmendall/capital-intelligence-platform-.git
cd capital-intelligence-platform-

python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python initialize.py
streamlit run secure_app.py
```

For Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

Provider credentials, database paths, stage bindings, and deployment settings are environment-controlled. See [Data sources and governance](DATA_SOURCES.md) and [Operations](docs/OPERATIONS.md).

## Production API

Start the read-only API:

```bash
uvicorn api.app:create_app --factory --host 0.0.0.0 --port 8000
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

The API is query-only for investment authority and exposes no live-trade or allocation-mutation route.

## Canonical daily operation

The repository ships one complete twelve-stage operation plan at:

```text
deploy/canonical-daily-operations.json
```

The stages are:

1. provider certification;
2. security-master activation;
3. eligible-universe publication;
4. complete-universe screening;
5. production-context assembly;
6. canonical CIO cycle;
7. paper construction and execution;
8. thesis monitoring;
9. outcome evaluation;
10. operational evidence review;
11. canonical alert delivery; and
12. SLO assessment.

A failure or reconciliation problem blocks downstream authority.

Validate and run the plan:

```bash
python run_daily_operations.py --validate-plan
python run_daily_operations.py
python run_daily_operations.py --loop
```

Daily orchestration uses expiring worker leases, stage locks, heartbeats, monotonically increasing fencing tokens, and atomic fence verification. A stale worker cannot publish after losing ownership.

See [Canonical daily operations](docs/CANONICAL_DAILY_OPERATIONS.md).

## Deterministic validation

```bash
python -m compileall -q .
python initialize.py
python run_daily_operations.py --validate-plan
pytest -q --maxfail=1
```

Container acceptance uses the validation image:

```bash
docker build --target validation -t capital-intelligence:validation .
docker run --rm capital-intelligence:validation
```

The production runtime image does not include test tooling.

## Deployment

Prepare the environment and reviewed stage-binding secret:

```bash
cp deploy/staging.env.example deploy/staging.env
export CAPITAL_INTELLIGENCE_ENV_FILE=deploy/staging.env
export CAPITAL_INTELLIGENCE_DAILY_STAGE_BINDINGS_FILE=/secure/reviewed-bindings.json
docker compose up --build -d
```

The scheduler validates its full plan before entering the loop. Docker fails early when the reviewed binding file is absent.

## Backup and recovery

```bash
python run_backup.py
python run_backup.py --healthcheck
python run_restore.py backups/<archive>.tar.gz.fernet --verify-only
```

Readiness requires backup coverage for every active authority needed to reproduce a decision, including provider and security-master certification, universe eligibility, screening, production context, CIO journal, canonical portfolio state, theses, paper execution, approvals, evaluations, operations, incidents, resilience, SLOs, and readiness reports.

---

## Repository structure

```text
app.py                         Signature four-screen Streamlit experience
premium_ui.py                  Dark-first command-system presentation layer
secure_app.py                  Authenticated Streamlit entrypoint
initialize.py                  Canonical initialization and readiness checks

cio/                           Decision contracts, synthesis, persistence, cycle
opportunity/                   Eligibility, qualification, comparison, ranking
committee/                     Independent specialist analysis
portfolio/                     Construction, canonical state, paper execution
thesis/                        Living-thesis records and monitoring
evaluation/                    Point-in-time outcomes, attribution, calibration
providers/                     Data retrieval, certification, and provenance
api/                           Query-only institutional API
reporting/                     Daily CIO briefing assembly
deploy/                        Operations plans and deployment configuration
docs/                          Architecture, governance, evidence, and operations
tests/                         Decision, architecture, readiness, and security tests
```

## Documentation

- [Governing specification](GOVERNING_SPECIFICATION.md)
- [Architecture](ARCHITECTURE.md)
- [Roadmap](ROADMAP.md)
- [Canonical daily operations](docs/CANONICAL_DAILY_OPERATIONS.md)
- [Post-operation readiness](docs/POST_OPERATION_READINESS.md)
- [Automatic product-test readiness](docs/AUTOMATIC_TEST_READINESS.md)
- [Operational readiness assembly](docs/OPERATIONAL_READINESS_ASSEMBLY.md)
- [Governed multi-asset expansion](docs/MULTI_ASSET_EXPANSION.md)
- [Multi-asset evidence](docs/MULTI_ASSET_EVIDENCE.md)
- [Multi-asset paper execution](docs/MULTI_ASSET_PAPER_EXECUTION.md)
- [Multi-asset outcome attribution](docs/MULTI_ASSET_OUTCOME_ATTRIBUTION.md)
- [Point-in-time evaluation](docs/POINT_IN_TIME_EVALUATION.md)
- [Point-in-time security master](docs/POINT_IN_TIME_SECURITY_MASTER.md)
- [Provider certification](docs/PROVIDER_CERTIFICATION.md)
- [Complete-universe screening](docs/FULL_UNIVERSE_SCREENING.md)
- [Portfolio construction](docs/PORTFOLIO_CONSTRUCTION.md)
- [Canonical portfolio state](docs/CANONICAL_PORTFOLIO_STATE.md)
- [Thesis monitoring](docs/THESIS_MONITORING_OPERATIONS.md)
- [Paper-operation evidence](docs/PAPER_OPERATION_EVIDENCE.md)
- [Resilience exercises](docs/RESILIENCE_EXERCISES.md)
- [Operational SLOs](docs/OPERATIONAL_SLOS.md)
- [Production API](docs/PRODUCTION_API.md)
- [Legacy authority isolation](docs/LEGACY_AUTHORITY_ISOLATION.md)
- [Data sources and governance](DATA_SOURCES.md)
- [Operations](docs/OPERATIONS.md)

---

## Safety statement

Capital Intelligence is currently a research and paper-investment system. It does not authorize live trading, provide broker connectivity, claim proven alpha, or permit production-performance claims. A future execution layer would require separate technical controls, independent governance approval, and a new authorization boundary; it may not bypass the CIO, construction, canonical portfolio state, thesis, or evaluation process.
