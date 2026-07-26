# Capital Intelligence Platform

Capital Intelligence is an explainable, evidence-governed AI Chief Investment Officer designed to maximize long-term compounded portfolio returns.

The platform continuously converts point-in-time global financial intelligence into qualified opportunities, independent specialist analyses, a final CIO decision, portfolio implementation, thesis monitoring, and outcome evaluation.

> **Governing objective: maximize long-term compounded portfolio returns.**

Risk, liquidity, concentration, transaction costs, slippage, turnover, leverage, drawdown, evidence quality, data freshness, model confidence, and execution feasibility are operating constraints. Individual financial goals are not investment objectives and do not belong in the recommendation or portfolio-construction process.

The binding product contract is [GOVERNING_SPECIFICATION.md](GOVERNING_SPECIFICATION.md).

## Version 1 scope

Direct recommendation and allocation eligibility is limited to:

- liquid U.S.-listed equities;
- liquid U.S.-listed ETFs; and
- cash or short-duration Treasury equivalents.

Government bonds, credit, commodities, currencies, options, international indexes, global ETFs, crypto, volatility, and other markets may be analyzed as evidence. They are not direct recommendation targets until dedicated asset-specific frameworks have been validated.

## Current foundation

Foundation 1.x currently includes:

- point-in-time economic-regime intelligence;
- normalized provenance-aware economic, market, security, and filing contracts;
- seven reusable analytical engines;
- append-only institutional history and Decision Replay foundations;
- committee-governance and portfolio-fit foundations;
- a daily environment and decision-card experience;
- continuous analysis with selective material-change alerts;
- authenticated FastAPI and four-surface Streamlit delivery;
- encrypted backup and restore verification;
- reproducible dependency locks and blocking security controls; and
- research and paper-trading boundaries.

The platform is not yet a complete production investment system. Opportunity ranking, the specified specialist committee, CIO synthesis, quantitative candidate schema, portfolio optimization, thesis monitoring, walk-forward validation, attribution, and confidence calibration remain active roadmap work.

## Canonical decision loop

```text
Global Financial Intelligence
        -> Data Normalization, Provenance, and Point-in-Time Storage
        -> Signal and Evidence Generation
        -> Opportunity Detection and Ranking
        -> Independent Specialist Analysis
        -> Chief Investment Officer Decision
        -> Portfolio Construction and Implementation
        -> Continuous Thesis Monitoring
        -> Daily Capital Intelligence
        -> Evaluation, Attribution, and Confidence Calibration
```

The system is a continuous decision loop rather than a reporting pipeline.

## Committee contract

The governing committee contains:

1. Macro & Economic Strategist
2. Market Strategist
3. Fundamental & Valuation Analyst
4. Portfolio & Risk Manager
5. Evidence & Governance Officer
6. Chief Investment Officer

The first five analyze independently. The Evidence & Governance Officer may veto inadequate or irreproducible evidence. The Portfolio & Risk Manager may reject infeasible implementations. Only the CIO issues the final user-facing investment decision.

Weighted specialist consensus is not the final authority. Material dissent is preserved and provided to the CIO.

## Permitted CIO decisions

- Buy
- Increase
- Hold
- Reduce
- Exit
- Watch
- Insufficient evidence
- No superior opportunity
- No material change

No action is a valid and often preferable result.

## Canonical intelligence workflow

Run the current economic-regime pipeline:

```bash
python run_regime.py
```

When `FRED_API_KEY` is configured, the command retrieves required FRED series. Missing credentials or observations reduce disclosed coverage; the pipeline never silently substitutes sample data.

Journal a complete run:

```bash
python run_regime.py \
  --journal database/institutional_journal.db \
  --code-version YOUR_COMMIT_SHA
```

Run governance and journal the assessment and decision:

```bash
python run_regime.py \
  --govern \
  --journal database/institutional_journal.db \
  --code-version YOUR_COMMIT_SHA
```

The append-only institutional journal is separate from mutable paper-portfolio tables and verifies a hash chain across recorded events.

## Daily Capital Intelligence

Run the authenticated Streamlit entrypoint:

```bash
streamlit run secure_app.py
```

The primary navigation remains deliberately limited to:

1. **Today** — the material CIO briefing: what changed, why it matters, portfolio implication, action or disciplined no-action, confidence, and review conditions;
2. **Environment** — concise market and economic context with supporting evidence;
3. **Portfolio** — authorized holdings, paper activity, constraints, and non-executing implementation analysis; and
4. **History** — decision history, score context, Decision Replay, thesis history, and paper activity.

The Capital Intelligence Score is a supporting environment/evidence indicator. It is not the governing product identity, an expected-return estimate, or a trading signal.

The default experience is not a news feed and does not expose internal committee mechanics unless the user drills into analytical or audit detail.

## Scheduled intelligence and selective alerts

Run the persistent worker:

```bash
python run_scheduler.py
```

Run one due cycle and delivery pass:

```bash
python run_scheduler.py --once
```

The worker records every analytical cycle and applies versioned material-change policy before delivery. Unchanged conditions remain quiet and produce an auditable suppression record. Alerts must be based on material opportunity, risk, thesis, evidence, or CIO-decision changes—not individual financial goals.

## Authentication and authorization

Authentication is required by default. Configure the initial administrator before the first API, Streamlit, scheduler, or backup start:

```bash
export CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_EMAIL="admin@example.com"
export CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_PASSWORD="replace-with-a-long-random-password"
export CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_NAME="Platform Administrator"
```

Remove the bootstrap password after the first account is created.

Users receive explicit roles and portfolio or mandate grants. Authorization controls access to portfolios, holdings, paper trades, value history, alerts, and audit records. Access controls do not create personalized investment objectives.

See [Authentication and mandate authorization](docs/AUTHENTICATION_AND_AUTHORIZATION.md).

## Deployment and operational hardening

```bash
cp deploy/staging.env.example deploy/staging.env
docker compose up --build -d
```

The same immutable image runs the API, web app, scheduler, and backup service. Containers run as a non-root user with a read-only root filesystem, dropped capabilities, explicit writable volumes, and loopback-only host ports by default.

Operational endpoints:

```text
GET /health
GET /ready
GET /live
GET /worker/health
GET /metrics
```

Create or verify backups with:

```bash
python run_backup.py
python run_backup.py --healthcheck
python run_restore.py backups/<archive>.tar.gz.fernet --verify-only
python run_restore.py backups/<archive>.tar.gz.fernet --target restored-database
```

See [Deployment and operations](docs/OPERATIONS.md), [Backup and restore](docs/BACKUP_RESTORE.md), and [Incident response](docs/INCIDENT_RESPONSE.md).

## Production API

```bash
uvicorn api.app:create_app --factory --host 0.0.0.0 --port 8000
```

Session endpoints:

```text
POST /v1/auth/login
POST /v1/auth/refresh
POST /v1/auth/logout
GET  /v1/auth/me
```

Authenticated intelligence endpoints include daily snapshots, history, environment, decisions, replay artifacts, conviction context, authorized portfolios, and alerts. Goal-based investment-policy endpoints are compatibility surfaces scheduled for removal from the active decision path.

Use `/docs` for interactive documentation and `/openapi.json` for the deterministic contract.

## Engineering rules

Every core change must:

- improve long-term capital compounding;
- use traceable point-in-time evidence;
- preserve source independence and contradictory evidence;
- integrate with the common decision schema;
- respect Version 1 recommendation eligibility;
- preserve specialist independence and CIO-only action authority;
- support no-action and insufficient-evidence outcomes;
- keep sizing and execution separate from analytical conviction;
- produce a falsifiable thesis and monitoring plan; and
- support later attribution and confidence calibration.

## Documentation

- [Governing specification](GOVERNING_SPECIFICATION.md)
- [Product vision](PRODUCT_VISION.md)
- [Roadmap](ROADMAP.md)
- [Architecture](ARCHITECTURE.md)
- [Data sources and governance](DATA_SOURCES.md)
- [Institutional decision engine](DECISION_ENGINE.md)
- [Canonical daily experience](docs/DAILY_INTELLIGENCE_EXPERIENCE.md)
- [Portfolio-fit gate](docs/PORTFOLIO_FIT.md)
- [Dependency management](docs/DEPENDENCIES.md)
- [Production API](docs/PRODUCTION_API.md)
- [Operations](docs/OPERATIONS.md)

## Status boundary

The software remains research and paper-trading software. It does not execute live trades. Real-money reliance requires completion and validation of the remaining opportunity, portfolio, backtesting, attribution, and confidence-calibration layers.