# Multi-Asset Decision Evidence

## Purpose

The comparable `CandidateDecisionRecord` remains the common decision schema. Crypto, foreign exchange, and international listed markets additionally require a complete asset-specific evidence packet before a qualified candidate can enter the scheduled CIO context.

The packet is an evidence boundary, not another recommendation engine. It cannot add candidates, change rankings, size positions, issue a CIO action, or infer missing inputs.

## Required evidence

Every expanded-market packet preserves:

- screening cycle, candidate, instrument, and asset-class identities;
- asset-class governance approval identity;
- decision timestamp and knowledge cutoff;
- freshness boundary;
- required asset-specific metrics;
- valuation basis;
- expected-return drivers;
- risks and invalidation conditions;
- provider certifications;
- source and model versions;
- operating limitations; and
- downstream observations linked to originating economic facts.

Required metric categories are:

| Market | Required categories |
| --- | --- |
| Crypto | valuation, supply/demand, liquidity, implementation cost |
| FX | rate differential, valuation, liquidity, implementation cost |
| International equity | fundamental quality, valuation, currency exposure, liquidity, implementation cost |

These categories define minimum coverage. A later model version may add metrics but may not silently remove a required category.

## Originating-fact lineage

One economic fact repeated by several vendors remains one originating fact. Each downstream observation records:

- observation identifier;
- originating-fact identifier;
- source family;
- source identifier;
- observation timestamp; and
- availability timestamp.

The evidence authority exposes both observation count and independent-origin count. Repetition can improve delivery resilience but cannot manufacture independent confirmation.

## Point-in-time controls

An observation available after the knowledge cutoff is rejected. A packet stale at the cutoff is rejected. Packet timestamp, cutoff, screening cycle, candidate, instrument, and asset class must exactly match the production context.

## Production context

The configured production adapter uses `SQLiteAssetSpecificEvidenceStore`. For each qualified expanded-market candidate it requires exactly one matching packet. Missing and extra candidate packets both block the cycle.

The canonical context manifest adds:

- packet identifiers;
- asset-class approval identifiers;
- provider-certification identifiers;
- observation identifiers;
- originating-fact identifiers;
- source versions; and
- model versions.

A U.S. equity, U.S. ETF, or Treasury-equivalent cycle remains compatible and requires no synthetic expanded-market packet.

## Persistence

`SQLiteAssetSpecificEvidenceStore` is append-only and SHA-256 chained. Updates and deletes are prohibited. Exact replay is idempotent; conflicting content under an existing identifier fails.

## Remaining data boundary

The contract does not certify a real provider or create production evidence. Each selected market still requires licensed providers, historical coverage, certified model outputs, and complete screening before its first real packet can be persisted.
