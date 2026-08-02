# Currency and Global-Liquidity Transmission Layer

## Purpose

Add a non-authoritative currency layer to the Committee and CIO Decision-System V2 so the existing specialists can reason about how exchange rates, dollar liquidity, policy divergence and hedging costs affect currencies, assets, companies and the governed portfolio.

This layer cannot decide, size, construct, authorize or execute an investment. It produces point-in-time evidence for the existing six specialists and CIO.

## Core questions

1. Which currency is strengthening or weakening, against what benchmark, and over what horizon?
2. Why is the move occurring?
3. Is the move nominal, real, policy-driven, growth-driven, risk-driven or funding-driven?
4. Which markets, companies and balance sheets are exposed?
5. Is the transmission already priced into forwards, options, yield curves, credit and relative asset performance?
6. What evidence would confirm or invalidate the conclusion?

## Required regime distinctions

Dollar strength must not be treated as one universal signal. The layer must distinguish at least:

- stronger U.S. growth and productivity;
- wider U.S. real-rate or nominal-rate differentials;
- Federal Reserve tightening or slower easing;
- foreign central-bank easing or foreign growth weakness;
- safe-haven demand during market stress;
- dollar funding shortage or collateral scarcity;
- terms-of-trade and commodity shocks;
- fiscal, political or intervention risk.

The same observed dollar appreciation can have materially different asset implications under each cause.

## Required evidence

- trade-weighted and bilateral spot returns;
- real effective exchange-rate valuation;
- nominal and real yield differentials;
- forward points and carry;
- implied volatility, skew and risk reversals;
- cross-currency basis and dollar-funding conditions;
- central-bank balance sheets and policy divergence;
- reserves, intervention and external-balance evidence;
- capital flows where point-in-time evidence is available;
- commodity, credit, equity, rates and volatility confirmation;
- hedging cost for USD and non-USD investors.

## Transmission map

The layer must translate currency conditions into explicit scenario effects on:

- other developed- and emerging-market currencies;
- local- and hard-currency emerging-market debt;
- emerging-market equities and refinancing risk;
- commodities priced in U.S. dollars;
- gold, crypto and global-liquidity-sensitive assets;
- U.S. import prices and inflation;
- multinational revenue translation and margins;
- exporters' and importers' competitiveness;
- hedged and unhedged international equity returns;
- hedged and unhedged international bond returns;
- global credit spreads, external debt service and capital flows.

## Company and asset exposure

For each affected candidate, the layer should estimate where applicable:

- revenue and cost currency mix;
- transaction and translation exposure;
- natural and financial hedges;
- foreign debt and refinancing exposure;
- pricing power and pass-through;
- sensitivity of margins, earnings, cash flow and valuation;
- sensitivity of local-currency and USD investor returns.

## Scenario discipline

Every currency conclusion must be probabilistic and conditional. It must include:

- base, supportive and adverse paths;
- causal driver;
- affected assets and direction of impact;
- magnitude range and confidence;
- independent confirmation;
- contradictory evidence;
- market-implied expectation comparison;
- invalidation conditions.

The system must never hard-code `dollar strength = risk-off`, `dollar weakness = risk-on`, or any equivalent rule.

## Specialist use

- Macro/Economic: policy divergence, global liquidity, inflation and external balances.
- Market: currency trend, breadth, positioning, volatility and cross-asset confirmation.
- Cross-Asset Forecast: scenario probabilities and transmission into candidate returns and drawdowns.
- Fundamental/Valuation: company revenue, cost, debt, margin and valuation sensitivity.
- Portfolio/Risk: currency concentration, hedging, tail dependence, funding and settlement.
- Evidence/Governance: source lineage, timestamp integrity, methodology, completeness and reproducibility.

## Acceptance criteria

- Currency conclusions are cause-specific rather than direction-only.
- USD portfolio reporting distinguishes local-currency return from currency translation.
- Hedged and unhedged alternatives are evaluated separately when investable.
- Dollar funding stress is distinguished from ordinary dollar appreciation.
- Market-implied expectations are compared before a candidate receives an expected-return adjustment.
- Currency evidence cannot independently create a candidate or portfolio action.
- All evidence is point-in-time, append-only and replay compatible.
