# Production Runtime Smoke Test

## Purpose

The Render operating host includes an administrator-only production smoke-test dialog. It verifies the five live conditions required to move from a conditional deployment pass to a full paper-testing pass without exposing credentials or changing investment authority.

The dialog verifies:

1. the canonical portfolio and institutional journal survived a controlled Render restart;
2. the autonomous operator heartbeat and current CIO report are fresh;
3. Alpaca paper/IEX, FRED, and the persisted public-information collector are operating;
4. either an explicit governed no-transaction decision or a completed identified paper execution exists; and
5. the latest canonical backup is recent and healthy under the encrypted production policy.

## Authorization

Only a signed-in principal with the `administrator` role can see or open the control. The four primary screens remain unchanged.

The verifier never returns API keys, passwords, tokens, backup encryption keys, or full environment values. It does not create or change a CIO decision, portfolio construction, approval, order, or real-money authority.

## Procedure

1. Sign in to the Render-hosted application as the bootstrap administrator.
2. Select **Production smoke test** in the sidebar.
3. Select **Capture pre-restart snapshot**.
4. In Render, restart `capital-intelligence-platform` and wait until the service and `/_stcore/health` are healthy.
5. Sign in again, reopen **Production smoke test**, and select **Run post-restart verification**.
6. Review the five pass/review rows and download the sanitized JSON evidence when needed.

If the backup check is the only incomplete item, select **Create encrypted backup now**, then rerun the verification. This uses the existing activation-aware canonical backup registry and does not affect trading behavior.

## Persistent artifacts

The dialog stores these credential-free artifacts under `CAPITAL_INTELLIGENCE_DATA_DIR`:

```text
production-runtime-smoke-before-restart.json
production-runtime-smoke-latest.json
```

The pre-restart artifact contains a random persistence canary, database integrity and schema summaries, table row counts, the deployed release, and a process-start marker. The post-restart verifier requires the process marker to change, the canary file to remain present, both databases to pass SQLite integrity checks, schemas to remain stable, and no captured table row count to decrease.

## Result interpretation

`PASS` means all five runtime checks passed simultaneously.

`CONDITIONAL_OR_FAILED` means at least one check needs review. A degraded public-information source may still be represented truthfully, but missing current provider evidence, a stale heartbeat, a missing governed outcome, a missing restart, lost persistent records, or an unhealthy backup prevents a full pass.

The platform remains paper-only throughout:

```text
real_money_authorized = false
```
