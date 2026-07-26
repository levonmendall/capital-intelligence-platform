# Capital Intelligence Platform

Capital Intelligence is an explainable, evidence-governed AI Chief Investment Officer designed to maximize long-term compounded portfolio returns.

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

That sentence is the operating rule for the product. A security is never evaluated in isolation, analytical confidence never becomes position size, ownership never exists without a falsifiable thesis, and retrospective evaluation never substitutes hindsight data for the original evidence package.

The binding product contract is [GOVERNING_SPECIFICATION.md](GOVERNING_SPECIFICATION.md).

## Governing objective and constraints

The objective is to maximize long-term compounded portfolio returns.

Risk, liquidity, concentration, correlation, factor exposure, turnover, transaction costs, slippage, leverage, drawdown, evidence quality, data freshness, and implementation feasibility are constraints that protect compounding. Individual financial goals, retirement dates, preferred investment philosophies, behavioral memory, and personal risk preferences are not investment objectives and do not enter candidate ranking, specialist analysis, CIO synthesis, portfolio construction, or alerts.

## Version 1 recommendation universe

Direct recommendation and allocation eligibility is limited to:

- liquid U.S.-listed equities;
- liquid U.S.-listed ETFs; and
- cash or short-duration Treasury equivalents.

Other markets may be analyzed as evidence or regime inputs. They cannot become direct CIO recommendations until dedicated asset-specific frameworks are validated and added to the versioned recommendation-universe policy.

## Implemented canonical loop

```text
Point-in-time financial evidence
        -> normalized provenance and availability boundaries
        -> quantitative candidate records
        -> comparison with cash, current holdings, and every supplied alternative
        -> qualification and opportunity ranking
        -> five independent specialist analyses
        -> CIO synthesis, dissent preservation, vetoes, or abstention
        -> portfolio-level sizing, funding, costs, and constraint checks
        -> explicit living thesis and falsification conditions
        -> Daily Capital Intelligence briefing
        -> point-in-time outcome evaluation, attribution, and calibration
```

The core loop is implemented and enforced through typed contracts, a tamper-evident append-only journal, integration tests, and architecture tests.

### Opportunity comparison

Every candidate is evaluated against the complete point-in-time capital-alternative set supplied to the cycle, including cash, current holdings, and other qualified candidates. Weak, stale, redundant, illiquid, cost-disadvantaged, or infeasible candidates are rejected before specialist review. No superior opportunity is a valid result.

### Independent specialist committee

The committee contains:

1. Macro & Economic Strategist
2. Market Strategist
3. Fundamental & Valuation Analyst
4. Portfolio & Risk Manager
5. Evidence & Governance Officer
6. Chief Investment Officer

The first five complete independent first-pass analyses. The Evidence & Governance Officer may veto inadequate or irreproducible evidence. The Portfolio & Risk Manager may reject an infeasible expression. Only the CIO issues the final user-facing investment decision. Weighted consensus is retained only in isolated legacy research modules and is not decision authority.

### Portfolio implementation

An approved CIO action is translated into a separate construction request. The construction engine determines feasible target weights and funding sources under cash, position, liquidity, sector, factor, correlation, turnover, cost, and minimum-retained-weight controls. CIO confidence is not used as a sizing input. The result remains a paper proposal and does not submit broker orders.

### Living thesis

Implemented ownership requires an explicit thesis containing the original rationale, expected return, horizon, assumptions, catalysts, risks, invalidation conditions, monitoring indicators, evidence lineage, confidence, and review timing. Monitoring may classify the thesis as strengthening, stable, weakening, stale, replacement-opportunity, exit-review, or invalidated. It may propose CIO review but cannot trade or silently rewrite the original thesis.

### Point-in-time evaluation

Every CIO decision receives an immutable decision-evidence snapshot. The snapshot freezes the original alternatives, evidence cutoff, prices, expected returns, risks, probability, specialist packet, models, policies, portfolio implementation, and thesis. Later evaluation compares realized results with the best alternative that was actually available at decision time, separates process quality from outcome, reconciles selection, sizing, timing, and costs, and supports confidence calibration without automatically changing governance.

## Daily Capital Intelligence

Run the authenticated Streamlit entrypoint:

```bash
streamlit run secure_app.py
```

The product retains four deliberately simple screens:

1. **Today** — the canonical CIO briefing: what changed, why it matters, the opportunity or risk, whether the portfolio should change, confidence, and evidence that would change the conclusion.
2. **Environment** — diagnostic economic and market evidence that informs analysis but cannot issue a recommendation.
3. **Portfolio** — canonical construction, authorized holdings, paper activity, costs, constraints, and implementation blocks.
4. **History** — CIO briefings, point-in-time evaluations, living theses, and paper-trade records.

There is no score-first opening screen, legacy recommendation fallback, conviction-trend authority, or Investor Memory decision control. If the canonical journal has no governed decision, the interface shows an honest no-decision state.

## Production API

Run the API:

```bash
uvicorn api.app:create_app --factory --host 0.0.0.0 --port 8000
```

The primary institutional read endpoints are:

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

The API reads from the append-only CIO journal in query-only mode and returns journal sequence and content-hash metadata. It exposes no trade or allocation mutation route. `/v1/daily` and legacy replay/decision surfaces remain deprecated diagnostics. Personal CIO, conviction, goal, investment-policy, and Investor Memory route families are not registered.

See [Production API](docs/PRODUCTION_API.md).

## Canonical intelligence and operations

Run or inspect security-master ingestion:

```bash
SEC_USER_AGENT="Capital Intelligence operations@example.com" python run_security_master.py
python run_security_master.py --status
```

The public SEC current feed is stored for discovery but cannot pass the full-universe activation gate. Licensed historical coverage remains a separate production requirement.

Certify a commercial provider before activation:

```bash
python run_provider_certification.py \
  --provider-factory vendor_adapter:create_provider \
  --manifest provider-manifest.json \
  --suite provider-certification-suite.json
```

A catalog cannot activate unless the latest provider certification is approved, unexpired, source-matched, and integrity-valid. Conditional approval is not investment authority, and a later rejected report immediately revokes screening readiness.

Run one governed complete-universe screening cycle:

```bash
python run_full_universe_screening.py \
  --cycle-id full-universe:2026-07-27 \
  --scheduled-for 2026-07-27T11:00:00+00:00 \
  --as-of 2026-07-27T12:00:00+00:00 \
  --knowledge-cutoff 2026-07-27T12:00:00+00:00 \
  --context deploy/opportunity-context.json \
  --metrics-provider licensed_market_adapter:build_metrics_provider \
  --candidate-provider production_candidate_adapter:build_candidate_provider
```

The cycle requires a currently certified and activated catalog, exact point-in-time metrics for the security master, and terminal screening results for every eligible constituent. Failed or incomplete partitions are retained for audit but cannot create an opportunity queue or CIO evidence.

Run the economic-regime research pipeline:

```bash
python run_regime.py
```

Assess or record the production operational objectives:

```bash
python run_slos.py
python run_slos.py --record-assessment --require-ready
```

The SLO authority measures authoritative provider freshness, complete eligible-universe cycle completion, living-thesis review latency, and point-in-time decision-evaluation latency. It does not create recommendations or relax data and governance requirements. Production readiness fails closed when a required objective is blocked or breached.

Run the persistent scheduler:

```bash
python run_scheduler.py
```

Run one due cycle and delivery pass:

```bash
python run_scheduler.py --once
```

Material-change delivery may reflect evidence, opportunity, risk, thesis, implementation, confidence, or CIO-decision changes. Score movement alone and individual financial goals cannot trigger investment alerts.

Deployment:

```bash
cp deploy/staging.env.example deploy/staging.env
docker compose up --build -d
```

Operational endpoints:

```text
GET /health
GET /ready
GET /live
GET /worker/health
GET /operations/slo
GET /metrics
```

Backup verification:

```bash
python run_backup.py
python run_backup.py --healthcheck
python run_restore.py backups/<archive>.tar.gz.fernet --verify-only
```

## Engineering invariants

Every active recommendation path must:

- optimize the governing objective subject to versioned constraints;
- use traceable point-in-time evidence;
- compare the candidate with every available use of capital;
- preserve contradictory evidence and source independence;
- enforce Version 1 recommendation eligibility;
- preserve specialist independence, vetoes, implementation blocks, and dissent;
- attribute the user-facing action only to the CIO;
- support disciplined no-action and insufficient-evidence outcomes;
- keep confidence, sizing, and execution as separate authorities;
- implement approved actions at portfolio level;
- create and continuously challenge an explicit thesis; and
- evaluate process and outcomes from the frozen decision-time evidence package.

Architecture tests prevent active application and API entrypoints from importing personal-goal, Investor Memory, legacy weighted-committee, or score-first recommendation authority.

## Status boundary

The canonical institutional decision architecture is implemented. The software remains research and paper-trading software and does not execute live trades.

Production investment reliance still requires broader live and licensed data coverage, comprehensive point-in-time Version 1 universe screening, extended walk-forward evidence across regimes, operational monitoring at production scale, paper-trading performance sufficient for governance approval, and a separately controlled execution system. The repository does not claim proven alpha or production brokerage readiness.

## Documentation

- [Governing specification](GOVERNING_SPECIFICATION.md)
- [Architecture](ARCHITECTURE.md)
- [Roadmap](ROADMAP.md)
- [Point-in-time evaluation](docs/POINT_IN_TIME_EVALUATION.md)
- [Point-in-time security master](docs/POINT_IN_TIME_SECURITY_MASTER.md)
- [Security-master ingestion and activation](docs/SECURITY_MASTER_OPERATIONS.md)
- [Security-master provider certification](docs/PROVIDER_CERTIFICATION.md)
- [Complete-universe screening](docs/FULL_UNIVERSE_SCREENING.md)
- [Portfolio construction](docs/PORTFOLIO_CONSTRUCTION.md)
- [Daily experience](docs/DAILY_INTELLIGENCE_EXPERIENCE.md)
- [Production API](docs/PRODUCTION_API.md)
- [Legacy authority isolation](docs/LEGACY_AUTHORITY_ISOLATION.md)
- [Data sources and governance](DATA_SOURCES.md)
- [Operational service levels](docs/OPERATIONAL_SLOS.md)
- [Operations](docs/OPERATIONS.md)
