# User-Approved Paper Execution

## Purpose

Capital Intelligence may analyze markets, issue a CIO conclusion, and construct a proposed implementation without changing the portfolio. A simulated transaction may proceed only after an authenticated user with `MANAGE` access supports the exact displayed decision and construction.

This consent is an additional authority. It does not replace:

1. the controlled paper-test eligibility package and human release decision in staging or production;
2. sustained paper-launch certification in staging or production;
3. the active runtime risk switch in staging or production;
4. instrument, universe, provider, quote, session, cost, liquidity, and reconciliation controls.

No step authorizes real money, custody, or a live brokerage order. Alpaca supplies paper-account, market-clock, asset, and IEX quote evidence; the canonical portfolio records internal simulated fills.

## Streamlit workflow

Run the authenticated application:

```bash
streamlit run secure_app.py
```

When the Portfolio surface contains a valid construction with proposed paper trades, a user with write access can:

- approve the exact implementation;
- decline it; or
- revoke an unexpired approval before execution.

The approval is bound to:

- the CIO decision identifier;
- the construction request identifier;
- the canonical SHA-256 of the complete construction payload;
- the authenticated user and session;
- an approval timestamp and 24-hour expiry; and
- the sole `COMPOUNDING` portfolio.

Approval events are append-only and tamper-evident. They are stored in `paper_test_governance.db`.

The Streamlit runtime now co-locates the execution worker with the approval database and canonical portfolio databases. Approval triggers an immediate attempt. A background fragment checks every 30 seconds while the application is active, and the Portfolio approval panel checks every five seconds while it is open. A construction-level lease and the canonical execution store prevent duplicate execution.

After successful execution, the approval changes to `executed`, the Portfolio surface displays the execution identifier, and a one-time completion toast appears without a manual refresh.

## Streamlit deployment configuration

Root-level Streamlit secrets must include one matching Alpaca paper pair:

```toml
APCA_API_KEY_ID = "replace-with-paper-key-id"
APCA_API_SECRET_KEY = "replace-with-paper-secret"
APCA_API_BASE_URL = "https://paper-api.alpaca.markets"
APCA_DATA_BASE_URL = "https://data.alpaca.markets"
APCA_DATA_FEED = "iex"

CAPITAL_INTELLIGENCE_ENVIRONMENT = "paper"
CAPITAL_INTELLIGENCE_STREAMLIT_PAPER_EXECUTION_ENABLED = "true"
CAPITAL_INTELLIGENCE_DATA_DIR = "database"
```

`paper`, `development`, and `test` environments use the repository's explicit development launch-gate bypass unless `CAPITAL_INTELLIGENCE_STREAMLIT_PAPER_EXECUTION_DEVELOPMENT_BYPASS=false` is configured. The lower-level executor refuses that bypass in `staging` or `production`.

For staging or production, also configure exact authority versions and populate the three append-only operational authority databases:

```text
CAPITAL_INTELLIGENCE_TEST_BASELINE_IDENTIFIER
CAPITAL_INTELLIGENCE_INVESTMENT_PROCESS_VERSION
CAPITAL_INTELLIGENCE_RELEASE
CAPITAL_INTELLIGENCE_PAPER_TEST_GOVERNANCE_DATABASE
CAPITAL_INTELLIGENCE_PAPER_LAUNCH_DATABASE
CAPITAL_INTELLIGENCE_PAPER_CONTROL_DATABASE
```

The application and worker must use the same `CAPITAL_INTELLIGENCE_DATA_DIR` or explicit database paths. The co-located Streamlit worker satisfies this requirement within one runtime. A deployment that uses multiple replicas requires shared persistent storage or a managed database.

## Manual execution entrypoint

Operators may still use the consent-gated command directly:

```bash
python run_approved_paper_execution.py \
  --construction artifacts/portfolio-construction.json \
  --decision-identifier <CIO_DECISION_IDENTIFIER> \
  --profiles artifacts/exact-trade-profiles.json \
  --session-provider providers.alpaca_paper:create_alpaca_paper_session_provider \
  --quote-provider providers.alpaca_paper:create_alpaca_paper_quote_provider \
  --as-of <CURRENT_TIMEZONE_AWARE_TIMESTAMP> \
  --baseline-identifier <IMMUTABLE_BASELINE> \
  --process-version <PROCESS_VERSION> \
  --code-version <TESTED_COMMIT_SHA> \
  --require-complete
```

The Streamlit worker materializes the exact approved construction and only the profiles corresponding to proposed trades before invoking this entrypoint.

A successful execution appends an `executed` event to the approval history. That prevents the same consent from being reused. A failed or held execution leaves approval pending until it expires or is revoked, permitting a governed retry without changing the approved construction.

After the executed event is recorded, the worker creates a `Paper transaction completed` alert for the authenticated approver under the existing `IMPLEMENTATION` topic. The in-app alert is immediately available. Email is queued when the user has enabled email and configured an address.

## Fail-closed behavior

Paper execution is blocked or held when:

- no authenticated approval exists;
- the construction changes after approval;
- approval is declined, revoked, expired, or already executed;
- the user lacks write access;
- automatic execution is disabled or Alpaca credentials are missing from the runtime;
- construction is blocked or outside the free listed-wrapper pilot;
- the market is closed;
- an asset is inactive, non-tradable, or non-fractionable;
- quotes are unavailable, stale, crossed, materially future-dated, or lack sufficient notional;
- eligible-universe or portfolio lineage is unavailable;
- staging or production paper authorities are unavailable;
- the runtime switch is halted;
- turnover, cash, drawdown, cost, or reconciliation checks fail.

Every result preserves:

```text
real_money_authorized = false
```
