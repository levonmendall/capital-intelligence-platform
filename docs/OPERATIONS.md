# Deployment and Operations

## Runtime topology

The Version 1 production topology contains four independently restartable services built from the same immutable image:

- `api` — authenticated FastAPI boundary;
- `web` — authenticated Streamlit experience;
- `scheduler` — canonical daily cycle and selective-alert worker; and
- `backup` — encrypted SQLite backup loop.

All services run as an unprivileged user with dropped Linux capabilities, a read-only root filesystem, and explicit writable data, backup, and temporary mounts. TLS terminates at a trusted reverse proxy or managed ingress. The application rejects non-HTTPS requests in production using the forwarded protocol header.

## Start a staging stack

```bash
cp deploy/staging.env.example deploy/staging.env
# Replace every placeholder secret.
docker compose up --build -d
```

Expose ports only through a TLS reverse proxy in shared environments. The compose defaults bind API and Streamlit to loopback.

## Health contracts

- `GET /health` — process liveness and release identity;
- `GET /ready` — required stores, authentication, alert persistence, backup target, and operational-policy readiness;
- `GET /live` — minimal process liveness;
- `GET /worker/health` — scheduler heartbeat freshness and last cycle status;
- `GET /metrics` — Prometheus text format, protected by the metrics bearer token when configured.

A stale or failed scheduler heartbeat returns HTTP 503 without marking the API process itself dead.

## Security-master readiness

The security master has a separate operational authority from ordinary store readiness. Catalog ingestion, activation, and source freshness can be inspected without contacting a provider:

```bash
python run_security_master.py --status
```

Monitor `screening_ready`, both integrity flags, the active catalog identifier, active source age, and blocking reasons. A catalog can remain stored while `screening_ready` is false. This is expected for the public SEC current feed and for any stale or incomplete provider delivery.

Production full-universe screening must call the activated-catalog boundary. It must not read the latest catalog row directly. Alert on catalog-chain failure, operation-chain failure, source age above policy, activation rejection, reconciliation conflict, and an absent active catalog after the licensed provider's delivery window.

See [Security-master ingestion and activation](SECURITY_MASTER_OPERATIONS.md).

## Logs and correlation

Every API request receives an `X-Request-ID`. A valid inbound ID is preserved; otherwise a new UUID is generated. JSON logs include timestamp, severity, service, environment, release, request ID, path, status, duration, and client address. Passwords, tokens, authorization headers, and secrets are never added as structured fields.

## Metrics

The API exports request counts, duration sums, rate-limit rejections, and unhandled exceptions. Scrape `/metrics` using:

```http
Authorization: Bearer <CAPITAL_INTELLIGENCE_METRICS_TOKEN>
```

Create alerts for sustained 5xx responses, stale worker heartbeat, failed scheduled cycles, repeated delivery failures, backup failure, and missing daily snapshots after the configured cycle window.

## Request hardening

The API enforces:

- trusted host allowlists;
- optional production HTTPS enforcement;
- request body size limits;
- per-process sliding-window rate limits;
- no-store, frame-denial, referrer, content-type, permissions, and CSP headers;
- HSTS when HTTPS enforcement is enabled.

Rate limiting is intentionally local to one API process. A future horizontally scaled deployment should replace it with an ingress or shared-store limiter.

## Secrets

Use a secret manager or orchestrator secret facility. Do not commit populated `.env` files. Remove the bootstrap administrator password after the initial account is created. Rotate metrics, backup-encryption, SMTP, provider, and administrator credentials independently.

## Release procedure

1. Merge only after tests, image build, and security workflows pass.
2. Tag the image with the immutable commit SHA.
3. Back up production stores and verify the archive.
4. Deploy to staging and check `/ready`, `/worker/health`, login, daily snapshot, and alert inbox.
5. Promote the identical image to production.
6. Monitor errors, cycle completion, worker freshness, and backup completion.
7. Roll back to the prior image if readiness or user-critical checks fail.
