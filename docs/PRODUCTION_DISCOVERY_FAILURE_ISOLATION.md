# Production discovery failure isolation

## Incident

The August 3, 2026 07:00 Pacific CIO cycle completed public-information collection
but failed before publishing an opportunity universe. EODHD returned HTTP 402 for
the LSE active symbol directory. The production publisher placed broad Alpaca/SEC
U.S.-security discovery and optional comprehensive global discovery in one exception
boundary, so the unentitled global provider discarded the otherwise valid U.S. scan.

## Correction

The production publisher now separates the two scopes:

1. Broad Alpaca/SEC U.S.-security discovery remains mandatory. Failure blocks the
   cycle and prohibits a no-superior-opportunity conclusion.
2. Comprehensive global discovery is mandatory only when an explicit probe, a
   configured complete certified investable catalog, or
   `CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY=true` makes it authoritative.
3. A known comprehensive-provider or catalog failure in optional mode produces an
   immutable degraded-scope record and does not discard the completed U.S. search.
4. The cycle and state file explicitly state that complete all-market coverage was
   not achieved. No missing global instrument or evidence is fabricated.

## Governance boundary

This correction does not treat unentitled EODHD data as available, lower a threshold,
create a candidate, authorize a trade, or certify global coverage. It aligns the
production cycle with the existing capability-based paper scope: strategic listed
wrappers and broad U.S. company discovery can operate while uncertified global lanes
remain unavailable. Once comprehensive discovery is explicitly certified or required,
its failure remains fully fail-closed.
