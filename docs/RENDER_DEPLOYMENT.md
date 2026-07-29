# Render Persistent Operating Deployment

## Purpose

Streamlit Community Cloud remains useful for presentation previews, but it is not the operating host for the Capital Intelligence CIO. The application relies on durable SQLite authorities, generated reports, an always-on CIO scheduler, a resumable historical-research archive, and encrypted backups. Those responsibilities require one continuously running service with persistent storage.

The repository root contains `render.yaml`, which creates one paid Render Docker web service with:

- a 5 GB encrypted persistent disk mounted at `/app/database`;
- the authenticated Streamlit console on Render's public `PORT`;
- the read-only FastAPI service on `127.0.0.1:8000`;
- the autonomous CIO and paper operator;
- the hourly public-information collector inside the operator;
- the daily resumable ten-year historical backfill loop;
- the encrypted backup loop; and
- one-instance enforcement so SQLite authorities cannot be written by multiple service instances.

The service starts through `run_render_service.py`. Loss of Streamlit, the API, or the CIO operator terminates the supervisor and lets Render restart the complete service. Transient historical-provider or backup-process failures are retried after five minutes without making the user interface unavailable.

## Create the service

1. Sign in to Render.
2. Select **New > Blueprint**.
3. Connect `levonmendall/capital-intelligence-platform-`.
4. Select the `main` branch and the repository-root `render.yaml` file.
5. Review the proposed `capital-intelligence-platform` web service.
6. Enter the secret values requested during Blueprint creation.
7. Apply the Blueprint and wait for the health check to pass.

The Blueprint uses the paid `standard` instance. The complete supervised runtime starts Streamlit, FastAPI, the autonomous CIO/paper operator, the historical backfill worker, and encrypted backups in one service; the prior 512 MB Starter allocation produced an out-of-memory termination with exit status 137. Standard is therefore the minimum approved production-paper operating tier for this topology. The service remains fixed at one instance because a persistent disk cannot be attached to multiple instances and the canonical authorities are SQLite databases.

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

Optional provider credentials can be added later from the Render service's Environment page. Adding a credential does not grant provider certification or legal-use approval. Add `SEC_USER_AGENT` with an identifiable application name and monitored contact address so SEC historical collection can operate under the SEC's automated-access policy.

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
/app/database/backup-authority-activation.json
/app/database/cio_reports/
/app/database/historical_replay/
/app/database/backups/
```

The historical directory contains compressed append-only partitions, per-source checkpoints, backfill manifests, and shadow-replay manifests. The complete repository defaults also resolve against `CAPITAL_INTELLIGENCE_DATA_DIR=/app/database`, so newly created authorities remain on the same disk.

## Activation-aware encrypted backups

A fresh persistent disk does not contain every database that may eventually be used by the full institutional platform. Render therefore enables `CAPITAL_INTELLIGENCE_BACKUP_ACTIVATION_AWARE=true`.

Under this policy:

- every SQLite authority that currently exists is included in the encrypted backup;
- the first observation of an authority records it in `/app/database/backup-authority-activation.json`;
- an activated authority remains required permanently for that deployment;
- deletion, corruption, or disappearance of an activated authority blocks subsequent backups;
- never-created modules do not falsely block the first backup on a fresh deployment; and
- the default non-Render backup policy remains strict across the complete canonical authority registry.

The activation record does not replace a database or lower its recovery classification. It distinguishes unused modules from state that once existed and must never disappear silently. Restoring an encrypted archive recreates the included SQLite files, which causes those authorities to be activated again on the restored deployment.

## Startup sequence

Every deployment performs this sequence inside the running disk-backed instance:

1. Create persistent state, report, historical-research, and backup directories.
2. Load or generate internal runtime secrets.
3. Resolve the deployed release from `RENDER_GIT_COMMIT`.
4. Add the Render external hostname to the production allowed-host list.
5. Initialize or validate the sole `COMPOUNDING` portfolio.
6. Start the internal API.
7. Start the autonomous CIO and paper operator.
8. Start the resumable historical backfill loop.
9. Start the encrypted backup loop.
10. Start the authenticated Streamlit console on Render's public port.
11. Report healthy at `/_stcore/health` only while the supervised service remains running.

The operator collects public information immediately when no current runtime collection exists, then no more than once per hour. Collection occurs before the due CIO cycle. The historical loop runs immediately on a new disk and then once per day by default. Missing evidence can produce abstention, degraded historical coverage, or a held implementation; it cannot be converted into a transaction merely to make the interface appear active.

## Verify the first deployment

Confirm the following in Render logs:

```text
"event": "initializing"
"event": "child_starting", "child": "api"
"event": "child_starting", "child": "cio-paper-operator"
"event": "child_starting", "child": "historical-backfill"
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
- `/app/database/historical_replay/manifests/latest-backfill.json` exists after the first collection pass;
- the pending-transaction report exists; and
- the backup directory receives an encrypted archive after the first successful backup cycle.

A CIO report may correctly state no action, abstention, held execution, or pending transactions. Only a valid nonblocked construction can reach paper execution. A historical report may correctly be degraded when a free provider is unavailable; its source state and blockers must remain explicit.

## Deployment behavior

`autoDeployTrigger: checksPass` prevents Render from deploying a `main` commit until the repository checks pass. A persistent disk disables zero-downtime replacement because Render must stop the existing disk owner before starting the new version. This brief restart is required to prevent simultaneous SQLite writers.

The Render health check targets `/_stcore/health`. The supervisor treats the API, Streamlit process, and autonomous CIO operator as critical. Historical collection and encrypted backup are noncritical supervised processes: a transient exit is logged and retried after five minutes without granting data availability or execution authority.

## Community Cloud retirement

After the Render URL is operating and the canonical databases have persisted through one restart, place the Streamlit Community Cloud app into sleep or delete it. It must not remain presented as the authoritative operating instance because it does not own the persistent CIO journal, portfolio ledger, or historical archive.

## Safety boundary

This deployment remains paper-only:

```text
real_money_authorized = false
performance_claims_permitted = false
```

It does not add live brokerage endpoints, leverage, margin, synthetic evidence, or a path around eligibility, quote freshness, liquidity, portfolio integrity, idempotency, reconciliation, point-in-time evidence, or survivorship controls.
