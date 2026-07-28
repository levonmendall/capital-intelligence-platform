# Canonical Encrypted Recovery Drill

## Purpose

A backup is not recovery evidence merely because an archive exists. The recovery drill proves that an encrypted, policy-compliant archive can be restored into an isolated directory and used to reconstruct the exact decision lineage required by the approved baseline.

The drill never writes to production databases and cannot authorize paper testing or real-money activity.

## Expectation contract

A `canonical-recovery-drill-expectation.v1` document binds:

- expectation identity;
- controlled-test baseline identity;
- investment-process version;
- deployed code version;
- required logical authorities;
- reviewed lineage probes;
- maximum recovery time; and
- maximum data-loss interval.

A lineage probe names one logical authority, a reviewed table and column, and the exact expected identifier. Typical probes cover:

- CIO decision identity in the institutional journal;
- portfolio snapshot identity;
- paper-execution decision identity;
- thesis or evaluation identity;
- daily-operation identity;
- readiness snapshot identity; and
- campaign or approval identity.

Only safe SQLite identifiers are accepted for table and column names. Values are supplied as query parameters.

## Drill sequence

`CanonicalRecoveryDrill` performs the following steps:

1. Authenticate and decrypt the archive.
2. Verify the version-2 manifest and authority-set digest.
3. Match baseline, process, and code versions to the expectation.
4. Confirm every required logical authority is present.
5. Restore the archive into a temporary isolated directory.
6. Run SQLite integrity checks on every restored database.
7. Execute every reviewed decision-lineage probe against read-only restored databases.
8. Measure recovery time and data-loss interval.
9. Confirm production mutation count is zero.
10. Persist an append-only recovery-drill report.

A missing authority, checksum failure, manifest mismatch, integrity failure, failed lineage probe, exceeded recovery objective, or exceeded recovery-point objective makes the report fail closed.

## Command

The drill requires the same encryption key used by the archive:

```text
CAPITAL_INTELLIGENCE_BACKUP_ENCRYPTION_KEY=<secret-manager-value>
```

Run:

```bash
python run_recovery_drill.py \
  --archive backups/capital-intelligence-<timestamp>.tar.gz.fernet \
  --expectation reviewed-recovery-expectation.json \
  --executed-at 2026-07-27T16:00:00+00:00
```

The report database defaults to `database/recovery_drills.db` and may be configured with:

```text
CAPITAL_INTELLIGENCE_RECOVERY_DRILL_DATABASE=database/recovery_drills.db
```

## Report boundary

A passed report proves only that the reviewed archive restored and reconstructed the expected evidence within the approved recovery objectives. It always reports:

```text
production_mutation_count = 0
paper_test_authorized = false
real_money_authorized = false
```

The report becomes evidence for the `encrypted_backup_restore` and `evidence_lineage_reconstruction` failure scenarios in the paper-test campaign. Human governance still decides whether the complete baseline may enter controlled paper testing.

Recovery-drill reports and stage-binding approvals are themselves included in later canonical encrypted backups.
