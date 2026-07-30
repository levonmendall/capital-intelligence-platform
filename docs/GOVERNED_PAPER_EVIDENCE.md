# Governed Paper Evidence

The listed-wrapper paper pilot uses authenticated Alpaca IEX quotes and up to ten years of point-in-time daily bars together with official daily FRED macro observations to publish candidate, forecast, valuation, market, and current-holding evidence into the existing canonical CIO contracts.

Each price-history input is represented by a deterministic content fingerprint containing its symbol, first and last observation times, observation count, and complete bar-set digest. The current quote is separately fingerprinted. FRED observations are rejected when their dates are invalid, future-known, or outside the governed freshness window. Quotes are rejected when they exceed the versioned pilot age limit.

The publisher has no ranking, sizing, construction, execution, or real-money authority. Missing evidence excludes a prospective instrument. Missing evidence for a current holding blocks the complete cycle because every owned position requires an explicit holding review.

The production executor restores prior CIO decisions and active living theses from the append-only journal before each cycle so hysteresis, ownership continuity, and next-day thesis review remain auditable.

The ten-year price window supports current candidate diagnostics but does not replace the separately governed ten-year historical replay. Historical replay remains a subordinate calibration control and cannot create candidates or enlarge recommendations.
