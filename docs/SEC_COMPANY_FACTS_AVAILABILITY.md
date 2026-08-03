# SEC Company Facts availability

## Production incident

The August 3, 2026 canonical CIO retry progressed beyond the optional global-catalog,
SEC filing-row, and Alpaca historical-pagination repairs. It then reached Invesco QQQ
Trust, Series 1 (CIK `0001067839`) inside the dynamically discovered U.S.-security lane.
The SEC submissions record exists, but the SEC Company Facts endpoint returns HTTP 404
for that issuer.

A missing Company Facts resource is an instrument-level evidence limitation. It does
not prove that SEC is unavailable for every other issuer and therefore must not abort
cross-market evidence collection for the entire universe.

## Correction

Production SEC evidence now distinguishes a Company Facts HTTP 404 from provider-wide
or structural failures:

1. A Company Facts 404 returns an empty company-facts result for that issuer.
2. The normal candidate-evidence builder then excludes a prospective company because
   its required fundamental evidence cannot be normalized.
3. If the affected symbol is already held, mandatory holding-evidence rules still block
   the cycle.
4. SEC submissions 404s remain blocking because issuer and filing identity cannot be
   established.
5. Company Facts 5xx responses, request failures, malformed JSON, malformed fact
   payloads, and point-in-time filing failures remain blocking.
6. The event is logged with the CIK, HTTP status, availability-policy version, and
   paper-only authority flags without response content or credentials.

## Governance boundary

This change does not invent company fundamentals, reclassify a fund as an operating
company, lower evidence standards, shorten history, reduce the universe, change an
investment threshold, create a candidate, authorize the CIO, alter construction,
execute an order, or enable real money. It isolates one issuer's absent XBRL resource
while preserving fail-closed treatment for that issuer and for genuine provider or
structural failures.
