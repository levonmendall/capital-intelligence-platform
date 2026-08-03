# Today news coverage resilience

The Today surface now treats an empty event record set as a coverage defect, not as
proof that the investment news cycle was quiet.

## Collection continuity

- Broad GDELT discovery requests a rolling 24-hour window instead of one hour.
- Render collects public information every 15 minutes.
- Each pass merges current normalized records with a bounded 30-hour source-timed
  history, preventing one thin or degraded pass from erasing the day’s valid stories.
- Event identity is deduplicated and original publication time remains authoritative.
- Collection output includes source-health and record-count diagnostics.

## Display admission

The Today educational surface still rejects stale, future-dated, fixture, raw OFAC
listing, and routine administrative noise. It admits a current source-qualified headline
when a provider omitted impact-channel metadata or when the exact investment
transmission is still unresolved. In the latter case it reports the development,
identifies what remains unknown, and avoids inventing a directional market conclusion.
The Environment surface remains restricted to economic impact channels.

## Empty-state truthfulness

When no usable current records exist, the UI reports incomplete coverage and keeps the
collection/filtering condition visible. It no longer says that no story deserved
attention. Historical retention is capped at 36 hours and never renews publication age.
If all upstream sources are unavailable, the application reports the outage rather than
fabricating a headline or relabeling stale information as current.

These controls affect educational presentation only. They do not lower evidence,
specialist, CIO, cash-hurdle, construction, sizing, paper-execution, or real-money
boundaries.
