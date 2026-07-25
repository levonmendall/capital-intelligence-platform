# Backup and Restore

## Backup guarantees

`run_backup.py` uses SQLite's online backup API rather than copying live database files. Each copied database must pass `PRAGMA integrity_check`. The archive contains a versioned manifest with logical database names, byte sizes, and SHA-256 checksums.

Production requires a Fernet encryption key. The encrypted archive is authenticated, so modification or an incorrect key causes verification to fail. Store the encryption key separately from the archive and rotate it through a documented key lifecycle.

## Create and verify

```bash
python run_backup.py
python run_restore.py backups/<archive>.tar.gz.fernet --verify-only
```

The persistent backup service runs the same operation every configured interval and prunes archives older than the retention period.

## Restore drill

Never restore directly over a running production volume.

```bash
python run_restore.py backups/<archive>.tar.gz.fernet \
  --target restored-database
```

Then:

1. verify every restored database with the restore command;
2. start an isolated API and worker against the restored directory;
3. confirm authentication, latest daily snapshot, Investor Memory, alerts, and scheduled-cycle history;
4. record the restore duration and result;
5. delete the drill environment securely.

Run a restore drill at least quarterly and after any storage or schema migration.

## Recovery objectives

The default daily backup interval implies an RPO of up to 24 hours. The target RTO is operator-dependent and must be measured through restore drills. Reduce the interval for stricter requirements.
