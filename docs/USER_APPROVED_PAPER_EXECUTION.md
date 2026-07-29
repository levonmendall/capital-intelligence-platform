# Autonomous and Manual Paper Execution

## Default operating mode

Capital Intelligence now starts in **automatic paper mode** whenever valid Alpaca
paper credentials are present. A separate click is not required for every CIO
construction.

Automatic mode does not weaken the investment or execution process. For each exact
construction it writes an append-only, SHA-256-bound system authorization and then
delegates to the existing canonical paper executor. The executor still independently
requires:

- one current canonical CIO decision and matching construction;
- a certified eligible-universe publication;
- an active and unblocked Alpaca paper account;
- an open trading session and current, non-crossed IEX quotes;
- instrument eligibility and exact identity lineage;
- portfolio, cash, turnover, drawdown, liquidity, leverage and cost compliance;
- append-only fills; and
- exact portfolio and accounting reconciliation.

Every result preserves `real_money_authorized=false`. Alpaca live brokerage endpoints
remain rejected.

## Configuration

```text
APCA_API_KEY_ID=<paper-key>
APCA_API_SECRET_KEY=<paper-secret>
APCA_API_BASE_URL=https://paper-api.alpaca.markets
APCA_DATA_BASE_URL=https://data.alpaca.markets
APCA_DATA_FEED=iex

CAPITAL_INTELLIGENCE_PAPER_EXECUTION_MODE=automatic
CAPITAL_INTELLIGENCE_DATA_DIR=database
```

Available modes are:

- `automatic` — default when paper credentials are available;
- `manual` — retain exact authenticated approval before execution; and
- `disabled` — monitor and construct without implementing paper trades.

The compatibility variable
`CAPITAL_INTELLIGENCE_STREAMLIT_PAPER_EXECUTION_ENABLED=false` still disables paper
execution when no explicit mode is supplied.

## Human pause

Automatic mode preserves a human stop without making that stop a launch prerequisite.
A portfolio manager can pause the exact construction from the Portfolio surface. The
latest decline or revocation prevents the autonomous policy from reauthorizing that
same construction. The manager may explicitly resume it later.

## Headless operation

Paper execution no longer depends on an open Streamlit browser session:

```bash
python run_autonomous_paper_operator.py --loop
```

The operator runs the canonical scheduled CIO worker, reads the latest matching
briefing and construction from the institutional journal, and checks paper execution
continuously. No recommendation or construction is fabricated when upstream evidence
is unavailable. Missing evidence produces a monitoring or idle state.

The Docker scheduler service runs this operator by default. The externally bound
12-stage institutional orchestrator remains available for deployments that need it,
but it is not a prerequisite for beginning paper operation.

## Manual compatibility mode

Set:

```text
CAPITAL_INTELLIGENCE_PAPER_EXECUTION_MODE=manual
```

The authenticated Portfolio surface then presents approve, decline and revoke controls
for the exact construction. The lower-level `run_approved_paper_execution.py` command
continues to support this workflow.
