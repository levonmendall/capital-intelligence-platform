# V2.1 historical data schema

## market_history

One row per date and ticker, including price, returns, momentum, breadth proxy,
flow proxy, risk score, volatility, source, and recording timestamp.

## regime_history

One row per archived date, including regime, posture, confidence, composite
score, component scores, source payload, and timestamp.

## rotation_history

One row per date and ticker, including rank, risk-adjusted score, trend score,
CIO view, and trend state.

## committee_history

One row per date and specialist.

## decision_history

One immutable CIO decision per archived date.

## decision_outcomes

Reserved for forward 5-, 21-, and 63-business-day result measurement.

Never store brokerage credentials, passwords, Social Security numbers, or
account numbers in these files.
