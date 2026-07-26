# Point-in-Time Security Master

## Governing purpose

Every recommendation must be compared with every other use of capital that was actually available at the decision timestamp. That comparison is only reproducible when issuer identity, instrument identity, symbols, venues, listing status, delistings, and corporate actions are known point in time rather than reconstructed from today’s survivors.

The security-master domain provides that identity and membership substrate. It does not create investment candidates, expected returns, CIO actions, position sizes, or trades.

## Two time boundaries

Every security-master snapshot has:

- `as_of` — the economic timestamp being reconstructed; and
- `knowledge_cutoff` — the latest timestamp at which a source record may have been available to the system.

This distinction allows a later correction to improve a later replay without rewriting what the platform knew at the earlier decision cutoff. Records learned after the cutoff are excluded even when their effective interval includes the economic timestamp.

## Temporal records

`data.security_master` separates stable identity from attributes that change through time:

- `IssuerRecord` — stable issuer identity;
- `InstrumentRecord` — stable security or fund identity and classification;
- `IdentifierAssignment` — CIK, FIGI, CUSIP, ISIN, provider, or other identifiers with effective and availability intervals;
- `ListingRecord` — symbol, venue, country, currency, calendar, listing status, and eligibility interval;
- `SecurityMasterAction` — symbol changes, venue changes, relistings, delistings, mergers, spinoffs, and other identity events; and
- `SecurityMasterCoverage` — explicit provider capabilities and deficiencies.

The catalog chooses the latest available revision for each stable record key at the requested knowledge cutoff. Historical records remain immutable.

## Coverage authority

A source may claim authoritative recommendation-universe coverage only when it discloses all of the following capabilities:

- licensed use;
- complete eligible-universe coverage;
- point-in-time availability;
- historical identifiers;
- complete listing history;
- delisted securities;
- corporate actions;
- complete provenance; and
- a defined service level.

`SecurityMasterCoverage.require_authoritative()` rejects incomplete sources. This prevents a current ticker list from masquerading as a survivorship-safe historical universe.

The SEC ticker-exchange reference feed is deliberately marked current-only and non-authoritative. It is useful for current identifier discovery but does not provide historical symbols, delistings, corporate actions, complete instrument classification, or a licensed full-universe service level.

## Version 1 universe construction

`Version1UniverseBuilder` combines:

1. a point-in-time security-master snapshot;
2. market metrics available by the same decision timestamp;
3. analytical-coverage metrics available by that timestamp; and
4. the versioned `RecommendationUniversePolicy`.

The output contains:

- eligible constituents with canonical instrument and listing identity;
- exact security-master record identifiers;
- structural membership intervals for walk-forward evaluation;
- the resulting `CandidateInstrument` lineage boundary; and
- every excluded instrument with explicit reasons.

The builder rejects future metrics and does not manufacture missing liquidity, duration, Treasury classification, or analytical coverage. Unsupported instruments remain evidence-only or ineligible under the existing Version 1 policy.

## Candidate lineage

Every active `CandidateInstrument` now requires:

- `security_master_snapshot_identifier`; and
- one or more `security_master_record_identifiers`.

The company-candidate builder and CIO journal serialization preserve those fields. A candidate therefore cannot enter opportunity ranking without disclosing the exact point-in-time identity records used to classify it.

## Persistence and integrity

`SQLiteSecurityMasterStore` stores complete catalogs as append-only, canonical JSON events. It provides:

- idempotent writes;
- conflicting-content rejection;
- a contiguous SHA-256 event chain;
- database triggers blocking update and delete operations;
- integrity verification; and
- point-in-time catalog and universe replay.

This store preserves the source catalog received by the platform. It does not make an incomplete source authoritative.

## Survivorship and walk-forward controls

Delisted securities remain present in historical snapshots when they were active at the reconstructed timestamp. They disappear only after the effective delisting boundary. Structural membership converts to the evaluation layer’s `PointInTimeUniverseMembership`, allowing walk-forward audits to reject securities that were absent from the original universe.

A credible backtest must still obtain authoritative historical catalogs and market/fundamental data from licensed providers. The domain prevents look-ahead and survivorship errors in software; it cannot supply missing commercial history.

## Current boundary and next step

The repository now has the complete temporal model, authoritative-coverage gate, append-only store, Version 1 universe builder, candidate lineage enforcement, and deterministic tests. It does **not** yet operate a complete licensed full-universe master.

The next data step is provider integration for historical identifiers, venue history, delistings, corporate actions, instrument classification, and service-level monitoring. Only after that coverage is validated should continuous full-universe screening be enabled.
