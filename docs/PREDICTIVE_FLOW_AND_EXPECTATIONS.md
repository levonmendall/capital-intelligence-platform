# Predictive capital-flow and market-expectations intelligence

## Investment questions

The predictive layer supplies the existing committee with two additional answers:

1. Where is marginal capital moving, and does the movement resemble durable
   accumulation, distribution, rotation, crowding, or short covering?
2. How different is the evidence-backed outlook from the outcome currently implied
   by price, volatility, recent distribution, and observed flow?

The layer does not create an instrument, approve a trade, size a position, construct a
portfolio, or execute an order. It enriches the existing Market, Cross-Asset Forecast,
and Fundamental & Valuation specialists through `ForwardIntelligenceBundle`.

## Capital-flow model

`CapitalFlowEngine` derives a point-in-time market-flow proxy from raw daily price and
volume evidence before the candidate record is finalized. It evaluates:

- recent dollar-volume acceleration;
- signed dollar flow;
- accumulation and distribution;
- price-volume confirmation;
- persistence;
- short- and medium-horizon trend;
- volatility;
- crowding and reversal risk; and
- the likelihood that a positive move is short covering rather than durable buying.

The state catalog is:

- accumulation;
- distribution;
- short covering;
- crowded advance;
- crowded decline;
- rotation; and
- neutral.

The current free-data version is explicitly a price-and-volume proxy. It does not
claim complete knowledge of ETF creations, mutual-fund subscriptions, dealer
inventory, futures positioning, options dealer exposure, credit issuance, or
cross-border ownership. Those sources can replace or supplement the proxy after their
point-in-time and licensing boundaries are certified.

## Market-expectations model

`MarketExpectationsEngine` separates:

- the evidence-backed central outlook;
- a disclosed market-implied proxy based on recent price, volatility, return
  distribution, and flow;
- expected surprise;
- estimated priced-in share;
- forecast uncertainty;
- price sensitivity;
- catalyst strength; and
- crowding.

Strong fundamentals are not automatically bullish. A candidate with a strong outlook
but a more optimistic market-implied proxy can receive a weak or negative expectations
signal. A modest outlook can receive a positive signal when market pricing appears
excessively pessimistic and the evidence supports a positive surprise.

## Active production integration

The production paper-evidence facade now:

1. derives the flow observation from the exact bar rows used by the candidate;
2. builds the standard candidate and specialist evidence;
3. creates flow and expectations signals;
4. enriches the existing Market context and canonical forward-intelligence bundle;
5. adds derived evidence identifiers and model versions to governed lineage;
6. persists the bundle through the existing append-only production-context store; and
7. supplies the same six specialists and CIO process already used in production.

No parallel committee or decision engine is introduced.

## Fail-closed behavior

A governed candidate cannot silently omit the predictive layer. Missing bar evidence,
missing point-in-time boundaries, malformed prices or volume, non-finite values, or
missing derived flow evidence fail candidate construction. Every forward-intelligence
evidence identifier must be present in the candidate lineage before persistence.

## Future institutional source expansion

The model contract is designed to incorporate certified sources for:

- ETF and mutual-fund flows;
- CFTC positioning and futures open interest;
- options volume, skew, volatility surfaces, and dealer positioning;
- Treasury issuance, reserves, reverse repo, and Treasury cash balances;
- credit creation, issuance, spreads, and dealer inventories;
- foreign demand and cross-border capital;
- corporate buybacks, issuance, and insider activity; and
- crypto funding, open interest, liquidations, stablecoin supply, and exchange flows.

Until those sources are active, the system reports the narrower market-flow proxy
truthfully rather than representing it as complete institutional flow.

## Authority boundaries

- One governed $250,000 paper portfolio remains.
- Exactly six specialists remain.
- The CIO remains the sole investment authority.
- Evidence and capability gates remain fail closed.
- Portfolio construction remains independently authoritative.
- Persistence remains append only and point in time.
- Execution remains paper only.
- No live-money capability is introduced.
