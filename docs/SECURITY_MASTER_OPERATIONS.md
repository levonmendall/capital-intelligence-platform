# Security-Master Ingestion and Activation

## Governing boundary

A security-master catalog can be useful evidence without being safe to power a full-universe investment cycle. Storage and activation are therefore separate authorities.

The platform may store current-only, incomplete, stale, or non-authoritative catalogs for discovery and audit. Only a catalog that passes the explicit activation policy may be used to construct the Version 1 screening universe.

## Provider delivery contract

A provider implements `SecurityMasterProvider` and returns a `SecurityMasterCatalogDelivery` containing:

- the immutable `SecurityMasterCatalog`;
- the source observation timestamp;
- the retrieval timestamp; and
- the ingestion-request identifier.

Observation and retrieval timestamps are distinct from record-effective timestamps. A security whose identifiers have not changed recently may still arrive in a fresh catalog. Conversely, a cached delivery can be stale even when one contained record changed recently.

## Ingestion flow

`SecurityMasterIngestionService` performs the following sequence:

1. fetch a provider delivery against one `SecurityMasterIngestionQuery`;
2. verify provider identity and request correlation;
3. append the catalog to `SQLiteSecurityMasterStore`;
4. verify the catalog hash chain;
5. construct the requested point-in-time snapshot;
6. load the latest append-only provider certification report;
7. evaluate certification, coverage, classification, identifiers, listings, future-known records, and source freshness;
8. append the ingestion result to `SQLiteSecurityMasterOperationalStore`; and
9. append a separate activation event only when every policy check passes.

The three activation modes are:

- `store_only` — preserve the catalog but never activate it;
- `activate_if_eligible` — activate only when eligible and otherwise return a stored-not-activated result; and
- `require_activation` — record the rejected result and raise `SecurityMasterActivationError` when policy blocks activation.

Provider failure, reconciliation conflict, catalog rejection, and activation rejection remain separate typed outcomes.

## Activation policy

`SecurityMasterActivationPolicy` can require:

- authoritative `SecurityMasterCoverage`;
- a latest provider certification that is approved, unexpired, source-matched, and integrity-valid;
- verified catalog-store integrity;
- a maximum source-observation age;
- a minimum active instrument count;
- minimum active-listing coverage;
- minimum instrument-classification coverage;
- minimum stable FIGI, CUSIP, or ISIN coverage;
- no duplicate active venue-symbol listing; and
- no records unavailable at the knowledge cutoff.

The quality report exposes every measurement and issue. Passing the policy does not prove investment alpha; it establishes only that the identity universe is sufficiently complete, current, and reproducible for screening.

## Expiring activation

Activation is append-only but not permanent. `active_catalog()` rechecks:

- the catalog hash chain;
- the operational-event hash chain;
- the provider-certification hash chain;
- the latest certification decision and expiration;
- authoritative coverage; and
- current source age.

A newly approved renewal does not silently inherit an old activation. The catalog must be ingested and activated again under the new certification identifier, preserving the exact authority used at activation time.

A stale catalog automatically becomes unavailable for screening without deleting or rewriting its activation history. `status()` reports the latest ingestion, latest activation, source age, integrity state, readiness, and blocking reasons.

## Reconciliation

`SecurityMasterReconciler` requires an explicit source-priority policy. Independent records with the same temporal natural key may be de-duplicated only when their economic content agrees. Provider labels and source record identifiers may differ; issuer identity, instrument classification, identifier values, listing details, temporal boundaries, and corporate-action terms may not.

Conflicting overlapping facts raise `SecurityMasterReconciliationError`. There is no silent majority vote or last-write-wins merge. Composite coverage is conservative: a reconciled catalog claims a capability only when every contributing source claims it.

## SEC current-feed operation

Run current SEC identity ingestion:

```bash
SEC_USER_AGENT="Capital Intelligence operations@example.com" \
python run_security_master.py
```

The SEC ticker-exchange feed is intentionally stored but not activated. It lacks licensed complete-universe coverage, historical identifiers, listing history, delistings, corporate actions, full classification, stable instrument identifiers, and a defined service level.

Require activation to exercise the hard gate:

```bash
SEC_USER_AGENT="Capital Intelligence operations@example.com" \
python run_security_master.py --require-activation
```

This command exits nonzero after recording the exact rejection reasons.

Inspect readiness without contacting a provider:

```bash
python run_security_master.py --status
```

The default database is `database/security_master.db`. Override it with `CAPITAL_INTELLIGENCE_SECURITY_MASTER_DATABASE` or `--database`.

## Provider certification boundary

Before activation, run the machine-readable capability manifest and historical scenario suite through `run_provider_certification.py`. The manifest and suite schemas, append-only registry, exit codes, renewal rules, and revocation semantics are documented in [Provider Certification](PROVIDER_CERTIFICATION.md).

Conditional approval is not sufficient for activation. A later rejected report is a revocation event, and an expired report blocks the active catalog immediately.

## Production activation boundary

A licensed provider can be integrated through the same protocol, but it must not be marked authoritative merely because an adapter exists. Production activation requires verified contractual rights, point-in-time historical delivery, complete eligible-universe coverage, delisted securities, corporate actions, identifier and venue history, classification quality, provenance, an operational SLA, and an approved current certification report.

Continuous full-universe screening must consume only `active_catalog()`. Reading the latest stored catalog directly would bypass the activation authority and is prohibited for investment decisions.
