# Protected FRED Live-Provider Verification

## Purpose

The normal pull-request and deterministic release workflows remain credential-free. Live FRED access is verified separately so a repository secret is not exposed to ordinary validation jobs or workflows triggered by forks.

## GitHub configuration

The workflow expects the repository or environment secret:

```text
FRED_API_KEY
```

The job is bound to the GitHub environment:

```text
live-provider-smoke
```

Configure that environment in **Settings → Environments → live-provider-smoke**. Recommended protection:

- allow deployment only from `main`;
- require an authorized reviewer for manual runs when practical;
- prevent administrators from bypassing the rule when strict evidence is required; and
- keep the FRED credential in GitHub Secrets rather than variables or committed files.

The existing repository-level `FRED_API_KEY` secret is sufficient for the workflow. Moving it to the `live-provider-smoke` environment later can narrow its scope further.

## Triggers

`.github/workflows/fred-live-smoke.yml` runs:

- manually through `workflow_dispatch`;
- weekly on Monday at 13:17 UTC; and
- after changes reach `main` that affect the FRED adapter, cache, series registry, smoke command, workflow, or runtime dependency lock.

It does not run for pull requests.

## Verification behavior

The command performs one bounded live request for the `DGS10` series:

```bash
python run_fred_live_smoke.py \
  --series DGS10 \
  --report reports/fred-live-smoke.json
```

The report contains provider identity, series identity, check time, latest observation date, observation count, and readiness state. It does not serialize the API key, exception text, request URL, or observation value.

A successful check produces `state=ready`. Missing credentials, provider errors, invalid payloads, or unavailable observations produce a nonzero exit and `state=blocked`.

## Boundary

A successful smoke check proves that the configured credential can reach and parse one live FRED series. It does not certify every FRED series, prove complete macro coverage, authorize real money, or replace the all-markets data-readiness gate.
