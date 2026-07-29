# Render Persistent Operating Deployment

## Purpose

Streamlit Community Cloud remains useful for presentation previews, but it is not the operating host for the Capital Intelligence CIO. The application relies on durable SQLite authorities, generated reports, an always-on CIO scheduler, and an encrypted backup loop. Those responsibilities require one continuously running service with persistent storage.

The repository root now contains `render.yaml`, which creates one paid Render Docker web service with:

- a 5 GB encrypted persistent disk mounted at `/app/database`;
- the authenticated Streamlit console on Render's public `PORT`;
- the read-only FastAPI service on `127.0.0.1:8000`;
- the autonomous CIO and paper operator;
- the hourly public-information collector inside the operator;
- the encrypted backup loop; and
- one-instance enforcement so SQLite authorities cannot be written by multiple service instances.

The service starts through `run_render_service.py`. Loss of Streamlit, the API, or the CIO operator terminates the supervisor and lets Render restart the complete service. A transient backup-process failure is retried after five minutes without making the user interface unavailable.

## Create the service

1. Sign in to Render.
2. Select **New > Blueprint**.
3. Connect `levonmendall/capital-intelligence-platform-`.
4. Select the `main` branch and the repository-root `render.yaml` file.
5. Review the proposed `capital-intelligence-platform` web service.
6. Enter the secret values requested during Blueprint creation.
7. Apply the Blueprint and wait for the health check to pass.

The Blueprint uses the paid `starter` instance because Render persistent disks are not available on a free web service. The service is intentionally fixed at one instance because a persistent disk cannot be attached to multiple instances and the canonical authorities are SQLite databases.

## Required secret values

Render prompts for these values during the initial Blueprint creation:

```text
CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_EMAIL
CAPITAL_INTELLIGENCE_BOOTSTRAP_ADMIN_PASSWORD
APCA_API_KEY_ID
APCA_API_SECRET_KEY
FRED_API_KEY
```

Use the Alpaca **paper** account credentials. Do not enter live-account credentials.

The supervisor generates the internal metrics token and Fernet backup-encryption key on first startup and stores them as mode-`0600` files on the encrypted persistent disk. Explicit environment values override the generated values.

Optional provider credentials can be added later from the Render service's Environment page. Adding a credential does not grant provider certification or legal-use approval.

## Persistent authorities

Only paths under `/app/database` survive restarts and deployments. The Render service therefore places all active state there, including:

```text
/app/database/canonical_portfolio.db
/app/database/institutional_journal.db
/app/database/identity.db
/app/database/alerts.db
/app/database/multi_asset_paper_execution.db
/app/database/public-live-information-report.json
/app/database/public-live-information-records.json
/app/database/public-live-information-runtime-state.json
/app/database/cio_reports/
/app/database/backups/
```

The complete repository defaults also resolve against `CAPITAL_INTELLIGENCE_DATA_DIR=/app/database`, so newly created authorities remain on the same disk.

## Startup sequence

Every deployment performs this sequence inside the running disk-backed instance:

1. Create persistent state, report, and backup directories.
2. Load or generate internal runtime secrets.
3. Resolve the deployed release from `RENDER_GIT_COMMIT`.
4. Add the Render external hostname to the production allowed-host list.
5. Initialize or validate the sole `COMPOUNDING` portfolio.
6. Start the internal API.
7. Start the autonomous CIO and paper operator.
8. Start the encrypted backup loop.
9. Start the authenticated Streamlit console on Render's public port.
10. Report healthy at `/_stcore/health` only while the supervised service remains running.

The operator collects public information immediately when no current runtime collection exists, then no more than once per hour. Collection occurs before the due CIO cycle. Missing evidence can produce abstention or a held implementation; it cannot be converted into a transaction merely to make the interface appear active.

## Verify the first deployment

Confirm the following in Render logs:

```text
"event": "initializing"
"event": "child_starting", "child": "api"
"event": "child_starting", "child": "cio-paper-operator"
"event": "child_starting", "child": "encrypted-backup"
"event": "child_starting", "child": "streamlit"
```

Then open the Render service URL and sign in with the bootstrap administrator credentials. Verify:

- Today shows provider/session state and the current CIO report;
- Environment shows provider-backed market and macro evidence;
- Portfolio shows the canonical $250,000 paper portfolio and any pending implementation;
- History shows CIO reports, decisions, theses, and paper activity;
- the operator heartbeat is refreshed at least once every 180 seconds;
- the public-information runtime state exists;
- the pending-transaction report exists; and
- the backup directory receives an encrypted archive after the first successful backup cycle.

A CIO report may correctly state no action, abstention, held execution, or pending transactions. Only a valid nonblocked construction can reach paper execution.

## Deployment behavior

`autoDeployTrigger: checksPass` prevents Render from deploying a `main` commit until the repository checks pass. A persistent disk disables zero-downtime replacement because Render must stop the existing disk owner before starting the new version. This brief restart is required to prevent simultaneous SQLite writers.

The Render health check targets `/_stcore/health`. The supervisor additionally treats the API, Streamlit process, and autonomous CIO operator as critical. If any critical child exits, the complete service exits so Render can restart it.

## Community Cloud retirement

After the Render URL is operating and the canonical databases have persisted through one restart, place the Streamlit Community Cloud app into sleep or delete it. It must not remain presented as the authoritative operating instance because it does not own the persistent CIO journal or portfolio ledger.

## Safety boundary

This deployment remains paper-only:

```text
real_money_authorized = false
performance_claims_permitted = false
```

It does not add live brokerage endpoints, leverage, margin, synthetic evidence, or a path around eligibility, quote freshness, liquidity, portfolio integrity, idempotency, or reconciliation controls.
