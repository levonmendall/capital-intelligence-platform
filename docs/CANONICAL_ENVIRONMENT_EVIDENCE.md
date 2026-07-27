# Canonical Environment Evidence

## Product contract

The Environment screen is a decision-evidence view, not a news feed and not a recommendation authority.

It must show the exact certified evidence snapshot available to the CIO at the decision cutoff. Observations that became available later appear in a separate collection labeled as subsequent developments. They are never merged into the original snapshot or presented as evidence the CIO could have known.

## Decision snapshot

`CertifiedDecisionEnvironmentSnapshot` preserves:

- decision, production-context, and screening-publication identifiers;
- decision timestamp and knowledge cutoff;
- publication timestamp;
- the concise Environment payload shown to the user;
- exact evidence identifiers;
- source and model versions;
- code version; and
- investment-process version.

The record is append-only and permanently states `decision_time_certified=true`.

## Subsequent developments

`SubsequentEnvironmentObservation` preserves:

- the decision snapshot it follows;
- observation and availability timestamps;
- category and concise summary;
- source and evidence identifiers;
- materiality; and
- structured supporting payload.

A later observation is rejected when it was already available at or before the decision cutoff. It is also rejected when it reuses a decision-time evidence identifier. Every response states `decision_time_certified=false` for these observations.

## API

```text
GET /v1/environment/latest
```

The canonical response contains:

```text
decision-time environment
knowledge cutoff
evidence and version lineage
subsequent_observations[]
subsequent_developments_are_decision_evidence = false
```

Production defaults to `CAPITAL_INTELLIGENCE_REQUIRE_CANONICAL_ENVIRONMENT=true`. When the certified snapshot is unavailable, the route fails with HTTP 503 rather than falling back to a legacy, hindsight-blended presentation snapshot.

Development fixtures may explicitly set the requirement to false. In that compatibility mode, a legacy snapshot is labeled `decision_time_certified=false` and contains no subsequent observations.

## Commands

Publish the exact decision snapshot:

```bash
python run_environment_evidence.py \
  --snapshot artifacts/certified-environment.json
```

Append a later observation:

```bash
python run_environment_evidence.py \
  --observation artifacts/subsequent-environment-observation.json
```

Inspect the current view:

```bash
python run_environment_evidence.py --latest
```

## Workflow responsibility

The reviewed production stage binding must publish the snapshot from the same production-context and CIO evidence package used for the decision. It must not regenerate the summary from newer provider data. Later observations enter only through the subsequent-observation command.

## Recovery and readiness

The Environment database is an active decision-reproduction backup authority. Controlled paper testing requires proof that the exact snapshot and all later observations can be restored with their hash chain and evidence identities intact.

Environment cannot issue or alter an investment action, approve a market, change portfolio construction, or authorize real money.
