# Incident Response

## Severity

- **SEV-1:** unauthorized data access, credential compromise, corrupted production stores, or materially incorrect portfolio guidance presented as current;
- **SEV-2:** API unavailable, scheduler stale, alerts broadly failing, or backup verification failing;
- **SEV-3:** partial provider degradation, isolated delivery failure, or non-critical UI failure.

## Immediate actions

1. Assign an incident lead and record an incident start time.
2. Preserve logs, request IDs, release SHA, health responses, and relevant database copies.
3. Contain the issue: revoke sessions, disable affected users, stop the scheduler, disable email, or remove the release from service as appropriate.
4. Never overwrite suspected corrupted data before a forensic copy and verified backup exist.
5. Communicate observed facts, user impact, and the next decision point without speculating.

## Common runbooks

### Worker stale

Check `/worker/health`, container status, provider credentials, scheduled-cycle records, and alert database locks. Restart only after confirming no active lease is still valid.

### Authentication concern

Disable affected accounts, revoke sessions, rotate bootstrap and infrastructure secrets, review append-only authentication audit events, and inspect request IDs for suspicious access.

### Backup failure

Preserve the last verified archive, inspect disk capacity and key availability, run `run_backup.py` manually, and perform a verification-only restore. Escalate if the last verified backup exceeds the RPO.

### Incorrect intelligence output

Stop outbound delivery while preserving the canonical snapshot and journal. Mark the output unavailable or stale rather than silently replacing it. Review evidence provenance, governance decision, material-change result, and code release.

## Closure

An incident closes only after service is stable, user impact is understood, evidence is preserved, corrective work is tracked, and a blameless review documents detection, response, root cause, and prevention.
