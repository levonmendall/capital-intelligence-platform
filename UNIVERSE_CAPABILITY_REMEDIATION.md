# Universe, Capability, and Candidate-Reachability Remediation

## Scope

This remediation corrects the mismatch between the configured paper universe, the historical replay universe, and the capability checks used by the canonical opportunity process.

It does not lower an investment threshold, alter the canonical strategy, expand CIO authority, increase construction authority, enable broker routing, or authorize real-money execution.

## Corrections

1. **Exact bounded-pilot capability authority**
   - The versioned paper-universe configuration is converted into an exact instrument-level authority.
   - Identity, symbol, economic exposure, listing venue, country, instrument type, and unlevered structure must all match.
   - Instruments outside the configured universe remain blocked.
   - Historical replay uses an explicitly research-only current-policy overlay and does not pretend that current governance approvals existed at earlier dates.

2. **Point-in-time capability evaluation**
   - The opportunity engine evaluates universe and capability eligibility at the candidate decision timestamp.
   - Production publication injects authority derived only from the fixed 15-instrument base pilot, not the post-discovery universe.
   - The production executor independently reloads the same fixed base-pilot authority before reconciling and running the queue.

3. **Historical replay parity**
   - Default replay loads the canonical paper-universe configuration instead of relying on a stale ETF whitelist.
   - Historical candidates preserve canonical instrument identifiers, actual listing venues, execution asset classes, economic exposures, and wrapper structure.
   - Provider symbol suffixes are normalized before feature-to-instrument reconciliation.
   - Every expected pilot instrument is accounted for at every cutoff as a candidate or an explicit exclusion.
   - Missing provider records can no longer silently remove an expected instrument from the replay funnel.

4. **Historical provider truthfulness**
   - A configured Stooq collection that returns zero records is unavailable rather than available.
   - Partial symbol coverage is degraded and identifies missing symbols.
   - The configured historical listed-symbol set matches the canonical 15-instrument pilot.

5. **Cash-equivalent identity**
   - The SGOV candidate is identified as a short-duration U.S. Treasury equivalent with an explicit duration for universe-policy evaluation.

## Production-path confirmation

The regression suite publishes a decision-complete production context through the same governed publisher and production executor used by the application. A non-core listed wrapper, GOVT, must:

- pass exact bounded-pilot capability validation;
- enter the ranked opportunity queue without any threshold relaxation;
- receive exactly six independent specialist analyses;
- receive a persisted CIO decision;
- produce a committee/CIO information trace; and
- appear in the persistent-cash funnel as having reached specialist analysis and CIO consideration.

The focused remediation suite and the fixed-pilot scope regression suite passed before the final implementation commit was produced. The clean implementation commit must also pass the repository's normal browser, deterministic release-validation, historical-backfill, and security workflows before merge.

This confirms candidate reachability through the production code path. It does not claim that a completed cycle on the private Render persistent disk has already observed the same event. Live-cycle frequencies require the deployed diagnostic release and access to, or an export of, the Render institutional journal.

## Authority boundary

- Canonical investment strategy changed: **no**
- Investment thresholds changed: **no**
- CIO authority changed: **no**
- Specialist authority changed: **no**
- Construction authority changed: **no**
- Paper execution authority changed: **no**
- Real-money authority added: **no**
- Historical policy promotion authorized: **no**
