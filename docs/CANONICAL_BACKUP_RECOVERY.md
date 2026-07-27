# Canonical Backup and Recovery

## Governing purpose

A Capital Intelligence decision is reproducible only when every active authority needed to reconstruct its evidence, decision, implementation, monitoring, evaluation, and operational state can be restored together.

The production backup path uses `CanonicalBackupRegistry`. It is an allow-list, not a directory scan. A new SQLite file is not protected until it is explicitly added to the registry and validated.

## Active authority set

The registry covers:

### Evidence

- security master and provider certification;
- certified eligible universe;
- complete-universe screening;
- production context;
- asset-specific evidence.

### Decision and portfolio

- institutional CIO journal, including decisions and thesis lineage;
- canonical cross-currency portfolio state;
- multi-asset paper execution.

### Governance and evaluation

- asset-class approvals;
- multi-asset outcome attribution and evaluation.

### Operations

- canonical daily-operation history and lease state;
- canonical alerts;
- operational SLOs;
- incidents;
- resilience exercises.

### Readiness and platform state

- product-readiness evidence;
- product-test readiness reports;
- daily intelligence read snapshots;
- authentication and identity state.

Every configured path is explicit in the staging and production environment examples.

## Retired authorities

The active registry prohibits:

```text
analytical_engines
investor_memory
investment_policy
regime_allocation
weighted_committee
```

Those names cannot enter a strict backup manager or a version-2 canonical manifest. Historical migration files may be retained outside the active recovery process, but they are not production decision authority.

## Version-2 manifest

A canonical archive uses:

```text
capital-intelligence-backup.v2
```

The manifest preserves:

- creation timestamp;
- immutable test baseline when configured;
- investment-process version;
- code version;
- backup-registry schema version;
- exact required logical authority names;
- prohibited logical authority names;
- omitted optional authorities;
- authority category and environment variable;
- configured source path;
- decision-reproduction and platform-recovery requirements;
- byte length and SHA-256 checksum for every SQLite copy; and
- a SHA-256 digest of the complete authority set.

The archive is rejected when a required authority is missing, a logical identity is duplicated, a prohibited legacy name is present, a checksum or authority-set digest fails, or the archive's required set does not match the active registry.

## Commands

Validate all required sources without producing an archive:

```bash
python run_backup.py --validate-sources
```

Create an encrypted, integrity-checked archive:

```bash
python run_backup.py
```

Check recency, encryption, manifest completeness, checksums, and SQLite integrity:

```bash
python run_backup.py --healthcheck
```

Verify an archive against the current canonical registry:

```bash
python run_restore.py backups/<archive>.tar.gz.fernet --verify-only
```

Restore every manifest authority to an isolated directory:

```bash
python run_restore.py backups/<archive>.tar.gz.fernet \
  --target restored-database
```

Restore never writes directly over the active deployment unless `--overwrite` is explicitly supplied. Each database is copied to a temporary target, integrity checked, and atomically renamed.

## Recovery acceptance

A paper-test baseline requires recorded evidence that:

1. every required source was available;
2. the archive was encrypted and verified;
3. every manifest database was restored;
4. each restored SQLite database passed `PRAGMA integrity_check`;
5. the restored authority count matched the manifest exactly;
6. the baseline, process, and code identifiers matched the tested operation; and
7. decision evidence lineage could be reconstructed from the restored stores.

Creating an archive is not sufficient disaster-recovery evidence. Restore and reconstruction must be exercised during the resilience campaign.

## Boundary

Backup completeness does not approve a provider, asset class, CIO action, or test baseline. It is one required operational gate. Archives contain sensitive institutional and identity state and must remain encrypted, access controlled, retained according to policy, and excluded from source control.
