# Data Coverage Matrix

Status vocabulary:

- **Monitored**: information can be observed or discussed.
- **Decision-certified**: point-in-time, provenance, freshness, rights, and required-domain gates are certified for CIO use.
- **Allocatable**: an instrument also passes identity, liquidity, cost, construction, paper execution, and reconciliation gates.

| Market/domain | Monitored now | Decision-certified now | Allocatable now | Evidence/gap |
|---|---|---|---|---|
| U.S. macro/rates | Yes | Partial/current; FRED enabled | Indirectly through certified pilot instruments only | Revised-vintage backtests require ALFRED certification |
| U.S. equities/ETFs | Yes | Bounded pilot only | 15-instrument pilot subject to live readiness | Alpaca IEX is not consolidated market evidence |
| International equities | Yes | Wrapper/pilot exposure; broad direct markets not certified | `VXUS` wrapper only in bounded pilot | Global reference/fundamental/market providers blocked |
| Government bonds/credit | Yes | Wrapper/pilot exposure | `GOVT`, `LQD`, `HYG`, `SGOV` in pilot | Direct fixed-income terms, pricing, calendars, liquidity not certified |
| Commodities/gold | Yes | Wrapper analysis/pilot | `DBC`, `GLD` in pilot | Direct curves/futures data and margin certification incomplete |
| FX | Yes | Monitored; direct decision certification incomplete | `UUP` wrapper in pilot; direct spot remains blocked unless separately certified | Global FX provider/availability boundaries missing |
| Crypto | Yes, including venue/public signals | Direct market certification incomplete | `IBIT` wrapper in pilot; direct spot crypto not currently certified allocatable | Coinbase/Kraken validation providers disabled; historical market structure/reference gaps |
| Real estate/alternatives | Yes | Wrapper-level pilot | `VNQ`, `DBMF`, `WTPI`, `VIXY`, `BTAL` subject to caps | Direct-market/derivative certification incomplete |
| Options/volatility | Yes | Not broadly certified | Only bounded listed wrappers; direct options prohibited until contract/margin/surface gates pass | OCC/CME/ICE/derived surfaces disabled |
| Fundamentals/filings | SEC current coverage | Partial | Supports only instruments/candidates whose complete gate passes | Older SEC archive, revisions, global accounting coverage incomplete |
| Security master/reference | Current SEC + configured sources | Partial | Pilot identities are bounded/configured | Delistings, historical listings, actions, membership, calendars incomplete |
| Public events/news | Multiple official/public sources | Educational only; five-case quality benchmark human-approved | Never directly allocatable | Benchmarking improves relevance and portfolio mapping but cannot authorize a decision or allocation |

The all-market manifest contains 20 declared provider capabilities; only official FRED and SEC EDGAR are enabled at this baseline. A provider being configured or monitored does not make a market decision-certified or allocatable.
