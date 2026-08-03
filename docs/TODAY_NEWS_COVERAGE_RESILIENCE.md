# Today news coverage resilience

The Today surface treats an empty event record set as a coverage defect, not as proof
that the investment news cycle was quiet.

## Collection continuity

- Broad GDELT discovery requests a rolling 24-hour window instead of one hour.
- Render collects public information every 15 minutes.
- Each pass merges current normalized records with a bounded 30-hour source-timed
  history, preventing one thin or degraded pass from erasing the day’s valid stories.
- Event identity is deduplicated and original publication time remains authoritative.
- Collection output includes source-health and record-count diagnostics.

## Display admission

The Today educational surface rejects stale, future-dated, fixture, raw OFAC listing,
and routine administrative noise. It admits a current source-qualified headline when a
provider omitted impact-channel metadata or when the exact investment transmission is
still unresolved. In the latter case it reports the development, identifies what remains
unknown, and avoids inventing a directional market conclusion.

Raw IMF, World Bank, Treasury, CFTC, and EIA table observations are economic evidence,
not news headlines. They remain available to the Environment and research layers, but
they cannot fill Today merely because the application retrieved them recently. Today
uses source publication time first, event time second, and collection time only when a
source provides neither. A corrected current record also evicts an older cached version
that had been mislabeled as fresh.

The regression suite explicitly reproduces the false-fresh GDP examples from 1984,
2007, and 2024 while proving that a genuine current source-qualified market headline
continues to appear even when its impact-channel metadata is incomplete.

## Empty-state truthfulness

When no usable current records exist, the UI reports incomplete coverage and keeps the
collection/filtering condition visible. It does not claim that no story deserved
attention. Historical retention is capped at 36 hours and never renews publication age.
If all upstream sources are unavailable, the application reports the outage rather than
fabricating a headline or relabeling stale information as current.

These controls affect educational presentation only. They do not lower evidence,
specialist, CIO, cash-hurdle, construction, sizing, paper-execution, or real-money
boundaries.
