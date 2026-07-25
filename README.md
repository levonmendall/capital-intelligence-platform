# Capital Intelligence Platform

An explainable, AI-assisted investment operating system for disciplined market
research, governed portfolio decisions, personal investor memory, and paper
trading.

## Current release

Foundation Version 1.x now includes:

- point-in-time economic-regime intelligence;
- six-specialist committee governance;
- a daily Capital Intelligence Score and conviction trend;
- a concise Environment Brief and CIO Decision Card;
- append-only daily history, Decision Replay, and Investor Memory;
- mandate-aware opportunity-cost analysis;
- an authenticated FastAPI boundary; and
- an authenticated four-screen Streamlit experience.

The software remains research and paper-trading software. It does not execute
live trades or bypass mandate constraints.

## Canonical intelligence workflow

```bash
python run_regime.py
```

When `FRED_API_KEY` is configured, the command retrieves the required FRED
series. Missing credentials or observations reduce disclosed coverage; the
canonical pipeline never silently substitutes sample data.

To journal a complete run:

```bash
python run_regime.py \
  --journal database/institutional_journal.db \
  --code-version YOUR_COMMIT_SHA
```

To run governance and journal the regime assessment plus committee decision:

```bash
python run_regime.py \
  --govern \
  --journal database/institutional_journal.db \
  --code-version YOUR_COMMIT_SHA
```

The append-only institutional journal is separate from mutable paper-portfolio
tables and verifies a hash chain across recorded events.

## Authentication and authorization

Runtime settings loaded from the environment require authentication by default.
Before the first API or Streamlit start, configure the initial administrator:

```bash
export CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_EMAIL="admin@example.com"
export CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_PASSWORD="replace-with-a-long-random-password"
export CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_NAME="Platform Administrator"
```

Remove the bootstrap password from the environment after the first account is
created.

Passwords use scrypt with unique salts. Access and refresh credentials are
opaque and stored only as hashes. Refresh rotates both credentials; logout and
account disabling revoke sessions.

Users receive explicit roles, mandate grants, and—when needed—investor-profile
grants. Portfolio lists, holdings, trades, values, and Investor Memory are
filtered at the service boundary rather than merely hidden in the interface.

See [Authentication and mandate authorization](docs/AUTHENTICATION_AND_AUTHORIZATION.md).

## Daily Capital Intelligence experience

Run the authenticated Streamlit entrypoint:

```bash
streamlit run secure_app.py
```

The primary navigation remains deliberately limited to:

1. **Today** — Capital Intelligence Score, conviction, environment, risk,
   committee stance, portfolio impact, and what changed;
2. **Environment** — the concise brief plus supporting economic evidence;
3. **Portfolio** — authorized mandates, holdings, paper trades, value history,
   and non-executing opportunity-cost analysis; and
4. **History** — score and conviction trends, Decision Replay, Investor Memory,
   and the authorized paper-trade journal.

Daily score records are stored in the append-only
`database/daily_intelligence_snapshots.db` history. Current, incomplete, stale,
and unavailable evidence states remain explicit. Score movement alone does not
trigger an alert; notification remains governed by material-change policy.

See [Canonical daily experience](docs/DAILY_INTELLIGENCE_EXPERIENCE.md).

## Production API

```bash
uvicorn api.app:create_app --factory --host 0.0.0.0 --port 8000
```

Public operational endpoints:

```text
GET /health
GET /ready
```

Session endpoints:

```text
POST /v1/auth/login
POST /v1/auth/refresh
POST /v1/auth/logout
GET  /v1/auth/me
```

Authenticated intelligence endpoints include daily snapshots, history,
environment, decisions, replays, conviction, Investor Memory, and authorized
portfolios. Administrator-only routes provision users, assign mandate and
investor grants, and disable accounts.

Use `/docs` for interactive documentation and `/openapi.json` for the
deterministic contract. Missing, stale, incomplete, and unavailable data remain
explicit.

See [Production API](docs/PRODUCTION_API.md).

## Personal CIO intelligence

The product pairs the daily Capital Intelligence Score with:

- a conviction trend derived from evidence confidence, committee support, and
  committee agreement;
- append-only Investor Memory built only from deliberately recorded preferences,
  actions, mistakes, and lessons; and
- explicit opportunity-cost analysis that uses excess cash and user-selected
  funding candidates without silently choosing a sale.

See [Personal CIO intelligence](docs/PERSONAL_CIO.md).

## Continuous intelligence, selective alerts

`monitoring.ContinuousRegimeMonitor` is the application boundary for scheduled
analysis. Every cycle can retrieve new point-in-time evidence, evaluate the
regime, run governance, compare the result with the prior decision, and record
the comparison. Notification remains a separate policy decision.

The default material-change policy stays quiet when the working view is
unchanged or only one moderate signal moves. It surfaces portfolio review only
when the evidence crosses governed materiality thresholds.

## CIO decision card

```bash
python run_regime.py \
  --decision-card html \
  --card-output reports/latest-decision.html
```

`--decision-card` supports Markdown, JSON, and responsive HTML. The primary view
shows the decision, why it matters now, and the directional portfolio effect;
evidence, risks, and review conditions remain available as progressive detail.

## Portfolio-fit and opportunity-cost gates

Committee approval does not flow directly into a portfolio weight. The
`portfolio.PortfolioFitGate` evaluates a proposal against a point-in-time
portfolio snapshot and versioned mandate.

The gate checks direction, prohibited exposure, liquidity, concentration,
minimum cash, risk budget, and overlap. Opportunity-cost analysis then explains
whether the proposal can use excess cash, which explicitly approved reduction
could fund it, and what trade-offs would result. Neither component executes a
trade.

## Documentation

- [Architecture](ARCHITECTURE.md)
- [Product vision](PRODUCT_VISION.md)
- [Roadmap](ROADMAP.md)
- [Data sources and governance](DATA_SOURCES.md)
- [Institutional decision engine](DECISION_ENGINE.md)
- [Authentication and authorization](docs/AUTHENTICATION_AND_AUTHORIZATION.md)
- [Canonical daily experience](docs/DAILY_INTELLIGENCE_EXPERIENCE.md)
- [Production API](docs/PRODUCTION_API.md)
- [Personal CIO intelligence](docs/PERSONAL_CIO.md)
- [Portfolio-fit gate](docs/PORTFOLIO_FIT.md)
