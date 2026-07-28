# User-Approved Paper Execution

## Purpose

Capital Intelligence may analyze markets, issue a CIO conclusion, and construct a proposed implementation without changing the portfolio. A simulated transaction may proceed only after an authenticated user with `MANAGE` access supports the exact displayed decision and construction.

This consent is an additional authority. It does not replace:

1. the controlled paper-test eligibility package and human release decision;
2. sustained paper-launch certification;
3. the active runtime risk switch;
4. instrument, universe, provider, quote, session, cost, and reconciliation controls.

No step authorizes real money, brokerage submission, custody, or live orders.

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

Approval events are append-only and tamper-evident. They are stored as additional tables in the canonical `paper_test_governance.db`, so the existing governance backup and recovery authority covers them.

While an approved implementation is pending, the Portfolio approval panel refreshes every five seconds. After successful execution, it changes to the completed state and displays a one-time Streamlit completion toast without requiring a manual page refresh.

## Execute the approved implementation

Use the consent-gated entrypoint instead of calling the lower-level executor directly:

```bash
python run_approved_paper_execution.py \
  --construction artifacts/portfolio-construction.json \
  --decision-identifier <CIO_DECISION_IDENTIFIER> \
  --profiles config/active-paper-instrument-profiles.json \
  --session-provider <MODULE:FACTORY> \
  --quote-provider <MODULE:FACTORY> \
  --as-of <CURRENT_TIMEZONE_AWARE_TIMESTAMP> \
  --baseline-identifier <IMMUTABLE_BASELINE> \
  --process-version <PROCESS_VERSION> \
  --code-version <TESTED_COMMIT_SHA> \
  --require-complete
```

The entrypoint first requires current user approval for the exact construction hash. It then delegates to `run_multi_asset_paper_execution.py`, which independently requires the active entry, launch, and runtime authorities and applies the existing paper-only execution controls.

A successful execution appends an `executed` event to the approval history. That prevents the same consent from being reused for a second implementation. A failed or held execution leaves the approval pending until it expires or is revoked, permitting a governed retry without changing the approved construction.

After the executed event is recorded, the worker creates a `Paper transaction completed` alert for the authenticated approver under the existing `IMPLEMENTATION` topic. The in-app alert is immediately available in the authenticated Notifications inbox. Email is queued when the user has enabled the email channel and configured an address. User alert preferences remain authoritative.

The completion alert is deduplicated by user, execution identifier, and channel. A notification-store failure cannot cause the already completed paper transaction to run again; the worker reports `completed_with_notification_error` while retaining a successful execution result.

## Fail-closed behavior

Paper execution is blocked when:

- no authenticated approval exists;
- the construction changes after approval;
- approval is declined, revoked, expired, or already executed;
- the user lacks write access;
- construction is blocked;
- controlled paper launch authority is unavailable;
- the runtime switch is halted;
- provider, quote, session, eligibility, portfolio, turnover, drawdown, or reconciliation checks fail.

Every result preserves:

```text
real_money_authorized = false
```
