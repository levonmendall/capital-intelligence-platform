# Capital Intelligence Platform

Capital Intelligence is an explainable, evidence-governed AI Chief Investment Officer designed to maximize long-term compounded portfolio returns.

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

That sentence is the operating rule for the product. A security is never evaluated in isolation, analytical confidence never becomes position size, ownership never exists without a falsifiable thesis, and retrospective evaluation never substitutes hindsight data for the original evidence package.

The binding product contract is [GOVERNING_SPECIFICATION.md](GOVERNING_SPECIFICATION.md).

## Current readiness

The product has a strong canonical architecture and a governed CIO decision process, but it is **not yet approved for controlled paper testing**. Development remains open. The software does not execute live trades.

Readiness is deliberately split into four different statuses:

| Status | What it proves | What it does not prove |
| --- | --- | --- |
| System health | The API or worker process is alive | That dependencies or the investment process work |
| Dependency readiness | Required databases, configuration, providers, and secrets are available | That a daily operation completed |
| Operational readiness | The complete daily workflow, SLOs, resilience evidence, reconciliation, and incidents are acceptable | That a baseline is approved for testing |
| Paper-test readiness | One immutable code/process baseline satisfies every governed product-test gate | Live-trading authority or proven performance |

A running API is never interpreted as proof that the complete investment process can execute. Every readiness report permanently preserves:

```text
real_money_authorized = false
performance_claims_permitted = false
```

## Governing objective and constraints

The sole investment objective is to maximize long-term compounded portfolio returns after costs.

Risk, liquidity, concentration, correlation, factor exposure, turnover, transaction costs, slippage, leverage, drawdown, evidence quality, data freshness, and implementation feasibility are constraints that protect compounding. Personal goals, retirement dates, preferred investing styles, behavioral memory, and user-selected mandates do not enter candidate ranking, specialist analysis, CIO synthesis, portfolio construction, or alerts.

The only active portfolio code is `COMPOUNDING`.

## Asset-class governance

Market data availability does not create recommendation authority. Every asset class has an explicit state.

| Product state | Initial scope |
| --- | --- |
| Core product | Liquid U.S.-listed equities, liquid U.S.-listed ETFs, cash, and short-duration U.S. Treasury equivalents |
| Controlled paper eligible | Crypto spot, unlevered spot FX, and approved international listed equities or funds, but only with active asset-class approval and complete provider, evidence, construction, execution, thesis, and evaluation coverage |
| Evidence only | Forecasts, unapproved markets, research-only instruments, and cross-market observations that may inform Environment or specialist analysis but cannot produce a direct CIO action |
| Prohibited | Live trading, leverage, margin, crypto derivatives, FX forwards or swaps, options, staking, lending, DeFi authority, synthetic notional multipliers, and any instrument without approved identity, custody, settlement, data, and execution controls |

Expanded-market approval is point-in-time, expiring, append-only, and fail closed. A symbol, provider response, forecast, or model score is never sufficient approval.

See [Governed multi-asset expansion](docs/MULTI_ASSET_EXPANSION.md).

## The only active decision path

```text
Point-in-time certified evidence
        ↓
Complete eligible-universe comparison
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
Point-in-time outcome and attribution evaluation
```

Older regime-allocation, weighted-committee, score-first, personal-goal, and Investor Memory workflows are not active decision authorities. They may exist only in isolated migration or historical research boundaries and must not appear in production entrypoints, CI release gates, or user-facing decision documentation.

### Opportunity comparison

Every candidate is compared with cash, current holdings, and every other qualified candidate available at the decision cutoff. Weak, stale, redundant, illiquid, cost-disadvantaged, or infeasible candidates are rejected before specialist review. “No superior opportunity” is a valid outcome.

### Independent specialist committee

The active committee contains:

1. Macro & Economic Strategist
2. Market Strategist
3. Fundamental & Valuation Analyst
4. Portfolio & Risk Manager
5. Evidence & Governance Officer
6. Chief Investment Officer

The first five produce independent analysis. Evidence & Governance may veto inadequate or irreproducible evidence. Portfolio & Risk may reject an infeasible expression. Only the CIO issues the final investment action.

### Portfolio implementation

The construction engine determines feasible target weights and funding sources under cash, position, liquidity, sector, factor, correlation, turnover, cost, currency, custody, settlement, and retained-weight controls. CIO confidence is not a sizing input.

Paper execution is a separate authority. It applies market sessions, identity, quote and FX freshness, liquidity participation, spread, commissions, cash, ownership, and reconciliation. It has no broker or live-order authority.

### Living thesis and evaluation

Implemented ownership requires an explicit thesis containing the original rationale, expected return, horizon, assumptions, catalysts, risks, invalidation conditions, monitoring indicators, evidence lineage, confidence, and review timing.

Later evaluation uses the frozen decision-time package. Multi-asset attribution separates local asset return, currency translation, interaction, implementation cost, and total base-currency portfolio contribution.

## Forecasting boundary

Forecasts are supporting evidence, never an independent decision authority. A governed forecast record must preserve:

- target and horizon;
- as-of timestamp and knowledge cutoff;
- model and data versions;
- scenario probabilities;
- confidence and uncertainty;
- calibration method;
- historical accuracy at the same horizon;
- source and originating-fact lineage; and
- limitations and invalidation conditions.

A forecast may influence a specialist evidence packet. It cannot create a candidate, change opportunity ranking, size a position, issue a CIO action, or bypass asset-class governance.

## Daily Capital Intelligence experience

Run the authenticated Streamlit entrypoint:

```bash
streamlit run secure_app.py
```

The product retains four deliberately simple screens:

1. **Today** — the canonical CIO briefing: what changed, why it matters, the opportunity or risk, whether the portfolio should change, confidence, and evidence that would change the conclusion.
2. **Environment** — the certified evidence snapshot used by the decision, with observations received after the cutoff shown separately as subsequent developments. Environment cannot issue a recommendation.
3. **Portfolio** — canonical holdings, construction, currency exposure, paper activity, costs, constraints, and implementation blocks.
4. **History** — CIO decisions, frozen evidence, living theses, point-in-time evaluations, attribution, and paper fills.

The Environment contract is a readiness requirement: decision-time evidence and later observations must never be blended into one hindsight view.

## Production API

Run the API:

```bash
uvicorn api.app:create_app --factory --host 0.0.0.0 --port 8000
```

Primary institutional read endpoints include:

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

The API is query-only for investment authority. It exposes no live trade or allocation mutation route.

## Canonical daily operations

The repository ships one complete twelve-stage plan:

```text
deploy/canonical-daily-operations.json
```

The stages are:

1. provider certification
2. security-master activation
3. eligible-universe publication
4. complete-universe screening
5. production-context assembly
6. canonical CIO cycle
7. paper construction and execution
8. thesis monitoring
9. outcome evaluation
10. operational evidence review
11. canonical alert delivery
12. SLO assessment

A failure or reconciliation problem blocks every downstream stage.

### Multi-worker safety

Daily orchestration uses:

- worker ownership;
- expiring operation leases;
- expiring stage locks;
- operation and stage heartbeats;
- monotonically increasing fencing tokens; and
- atomic fence verification before authoritative publication.

A replacement worker may resume after expiry with a higher token. A stale worker cannot publish results after losing ownership.

### Plan and binding validation

The repository plan invokes `run_daily_stage_adapter.py` for every stage. Deployment injects the reviewed command-binding document:

```text
CAPITAL_INTELLIGENCE_DAILY_STAGE_BINDINGS=/run/secrets/canonical-daily-stage-bindings.json
```

Validate before starting workers:

```bash
python run_daily_operations.py --validate-plan
```

Run one operation or the durable loop:

```bash
python run_daily_operations.py
python run_daily_operations.py --loop
```

The checked-in validation bindings are synthetic container fixtures only. They cannot be used as production authority.

See [Canonical daily operations](docs/CANONICAL_DAILY_OPERATIONS.md).

## Deployment

Prepare environment and the reviewed stage-binding secret:

```bash
cp deploy/staging.env.example deploy/staging.env
export CAPITAL_INTELLIGENCE_ENV_FILE=deploy/staging.env
export CAPITAL_INTELLIGENCE_DAILY_STAGE_BINDINGS_FILE=/secure/reviewed-bindings.json
docker compose up --build -d
```

The scheduler validates its complete plan before entering the loop. Docker fails early when the reviewed binding file is absent.

Operational endpoints include:

```text
GET /health
GET /ready
GET /live
GET /worker/health
GET /operations/slo
GET /metrics
```

These endpoints report system or dependency state. They do not declare paper-test readiness.

## Deterministic validation

The supported local test environment is Python 3.11.

```bash
python -m compileall -q .
python initialize.py
python run_daily_operations.py --validate-plan
pytest -q --maxfail=1
```

Container acceptance uses a separate validation image:

```bash
docker build --target validation -t capital-intelligence:validation .
docker run --rm capital-intelligence:validation
```

That command runs the fenced twelve-stage workflow through isolated subprocesses and the persisted-authority-to-real-CIO integration under explicit time limits. The production `runtime` image does not include test tooling.

## Backup and recovery

Canonical backup and restore commands are:

```bash
python run_backup.py
python run_backup.py --healthcheck
python run_restore.py backups/<archive>.tar.gz.fernet --verify-only
```

Paper-test readiness requires backups to cover every active authority needed to reproduce a decision: provider and security-master certification, universe eligibility, screening, production context, CIO journal, portfolio state, theses, execution, approvals, asset-specific evidence, evaluations, operations, incidents, SLOs, resilience, and readiness reports. Retired legacy authorities must not remain in the active backup manifest.

## Burn-in and failure testing

Before a controlled paper cohort starts, one immutable code and process baseline must complete a multi-day operation burn-in and pass scenarios covering:

- provider outage and recovery;
- stale or future-known data;
- incomplete screening;
- worker termination and fenced takeover;
- database lock, corruption, and unavailability;
- encrypted backup restoration;
- execution hold and retry;
- duplicate alert suppression;
- valid no-action days; and
- complete decision evidence-lineage reconstruction.

A clean single-day run is insufficient.

## Remaining readiness work

The highest-priority architecture upgrades are now represented in the canonical design, including fenced multi-worker operations, a complete twelve-stage plan, startup validation, isolated stage timeouts, and container acceptance. Controlled paper testing still requires evidence that the following are complete for one immutable baseline:

- reviewed production stage bindings and licensed provider credentials;
- complete provider and point-in-time market coverage for every approved asset class;
- full active-authority backup and restore verification;
- Environment decision-snapshot and subsequent-observation separation;
- deterministic full release validation and duration budgets;
- required resilience campaigns and multi-day burn-in;
- zero unresolved critical incidents, integrity failures, or reconciliation failures; and
- formal human governance approval.

The repository does not claim proven alpha, authorize real money, permit production-performance claims, or treat development activity after the baseline as part of the test sample.

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
