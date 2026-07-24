# Capital Intelligence Platform

An explainable, AI-assisted investment operating system for disciplined research, portfolio management, and paper trading.

## Current Release

Foundation Version 1.x

The active milestone productionizes a deterministic, point-in-time
`economic_regime` path while preserving the legacy allocation interface.
The canonical institutional command is:

```bash
python run_regime.py
```

It retrieves the required FRED series when `FRED_API_KEY` is configured. If a
series or credential is unavailable, the command reports the missing evidence
and reduced coverage; it never silently substitutes sample data. The legacy
compatibility workflow remains available through `python run_intelligence.py`.

To append the complete run to the tamper-evident institutional journal:

```bash
python run_regime.py \
  --journal database/institutional_journal.db \
  --code-version YOUR_COMMIT_SHA
```

The journal is separate from mutable portfolio tables. It rejects update and
delete operations and verifies a hash chain across recorded events.

See:

- [Architecture](ARCHITECTURE.md)
- [Product vision](PRODUCT_VISION.md)
- [Roadmap](ROADMAP.md)
- [Data sources and governance](DATA_SOURCES.md)
- [Institutional decision engine](DECISION_ENGINE.md)

## Core Objectives

- Analyze changing market conditions
- Identify probable economic and market regimes
- Produce transparent CIO recommendations
- Manage multiple virtual investment mandates
- Record decisions and supporting rationale
- Measure portfolio performance over time

## Planned Architecture
intelligence = analysis and individual committee judgment
committee = meeting orchestration and collective governance

## Governance Architecture

The governance system is divided into two layers.

### `intelligence`

The `intelligence` package owns analytical judgment produced by individual
committee members. It includes:

- committee assessments
- score adjustments
- adjustment policies
- decision thresholds
- committee roles and votes
- individual committee opinions
- specialized members such as the Macro Committee

### `committee`

The `committee` package owns collective institutional governance. It includes:

- committee meetings
- opinion collection
- quorum
- voting weights
- veto handling
- consensus
- final committee decisions

The intended flow is:

Recommendation
→ Individual committee assessments
→ Individual committee opinions
→ Committee meeting
→ Consensus decision
→ Portfolio action

```text
app.py
initialize.py
run_intelligence.py

core/
intelligence/
dashboard/
config/
database/
economic_regime/
tests/
docs/
.github/workflows/
