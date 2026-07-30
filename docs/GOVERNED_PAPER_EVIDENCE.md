# Governed Paper Evidence

The paper pilot retains strategic U.S.-listed cross-asset wrappers and adds a daily broad U.S.-company discovery lane. It uses authenticated Alpaca IEX snapshots, quotes, and point-in-time daily bars together with the SEC company master, public SEC company facts, and official daily FRED macro observations to publish candidate, forecast, valuation, market, and current-holding evidence into the existing canonical CIO contracts.

Each price-history input is represented by a deterministic content fingerprint containing its symbol, first and last observation times, observation count, and complete bar-set digest. The current quote is separately fingerprinted. FRED observations are rejected when their dates are invalid, future-known, or outside the governed freshness window. A strategic one-year analysis may fall back to the latest official close when the premarket top of book is older than the analysis limit. Execution still requires a current positive, non-crossed quote inside the versioned pilot age limit.

The publisher has no ranking, sizing, construction, execution, or real-money authority. Missing evidence excludes a prospective instrument. Missing evidence for a current holding blocks the complete cycle because every owned position requires an explicit holding review.

The production executor restores prior CIO decisions and active living theses from the append-only journal before each cycle so hysteresis, ownership continuity, and next-day thesis review remain auditable.

The ten-year price window supports current candidate diagnostics but does not replace the separately governed ten-year historical replay. Historical replay remains a subordinate calibration control and cannot create candidates or enlarge recommendations.


## Company discovery and exploratory authority

The discovery lane evaluates the active Alpaca U.S.-equity list, requires SEC company identity, applies price and liquidity floors, ranks current market strength, and requests deeper price history for the strongest names and every current company holding. Company candidates then require normalized public SEC annual facts, company-factor analysis, relative-strength evidence, macro translation, and complete governed lineage.

A newly discovered company has a maximum 1% paper target and one-cycle entry persistence. Existing positions may be evaluated up to the governed 5% company ceiling, but any increase must pass the normal CIO, robustness, funding, construction, and execution controls. Discovery itself cannot rank the final opportunity set, issue a CIO action, size a portfolio, or authorize a fill.

The free-data lane does not currently include sell-side estimate revisions, proprietary fund flows, full consolidated market depth, or continuously updated company news. Those missing inputs are disclosed limitations rather than neutral evidence.

## Missed-opportunity measurement

Every screened candidate is recorded in a hash-chained append-only ledger with its contemporaneous price, cash alternative, qualification disposition, and rejection reasons. Once at least 21 days have elapsed and a later governed price is available, the system classifies rejected outperformers as missed opportunities and rejected underperformers as avoided losses. These observations are research and calibration evidence only; they cannot affect the original decision or authorize current trading.
