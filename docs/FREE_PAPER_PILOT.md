# Free listed-wrapper paper pilot

## Purpose

The institutional all-market readiness path remains the long-term standard for direct global equities, individual bonds, spot FX, direct crypto, futures, options, volatility instruments, and other complex assets.

A free data stack cannot honestly satisfy that standard. This pilot creates a narrower, explicit development authority so controlled paper testing can begin without pretending that free IEX or public data is institutional execution evidence.

The pilot:

- uses the sole `COMPOUNDING` portfolio;
- starts from the existing $250,000 paper capital;
- uses an Alpaca paper account and the free IEX feed;
- invests only through a versioned allowlist of unlevered U.S.-listed securities;
- represents the major economic asset classes through liquid listed wrappers;
- requires the exact CIO decision, exact construction, and exact authenticated user approval;
- uses the existing certified-universe, quote-age, session, portfolio-integrity, fill, reconciliation, and notification controls;
- keeps canonical portfolio implementation on the internal append-only paper executor; and
- separately verifies Alpaca paper order submission and broker fill reconciliation through a governed neutral round trip.

## Economic exposure covered

The allowlist covers:

- U.S. equities
- International equities
- Government bonds
- Investment-grade credit
- High-yield credit
- Cash and Treasury bills
- Broad commodities
- Gold
- Foreign exchange
- Crypto
- Real estate
- Managed futures
- Option strategies
- Volatility
- Market-neutral alternatives

These are economic exposures, not direct authority for every underlying instrument. For example, the managed-futures sleeve uses a listed fund rather than an exchange futures contract, and the option-strategy sleeve uses a listed fund rather than direct option orders.

Direct futures, options, individual bonds, spot FX, direct crypto tokens, non-U.S. listings, leveraged funds, inverse funds, and private assets remain prohibited in the listed-wrapper portfolio pilot.

## Required external setup

Create a free Alpaca paper account and place only its paper credentials in the runtime secret store:

```bash
APCA_API_KEY_ID=...
APCA_API_SECRET_KEY=...
APCA_API_BASE_URL=https://paper-api.alpaca.markets
APCA_DATA_BASE_URL=https://data.alpaca.markets
APCA_DATA_FEED=iex
CAPITAL_INTELLIGENCE_ENVIRONMENT=development
```

Never commit the key or secret. Both the quote adapter and broker-order adapter reject Alpaca's live brokerage endpoint.

## Start the listed-wrapper pilot

### 1. Validate the live free-provider configuration

Run during or outside market hours:

```bash
python run_free_paper_pilot_readiness.py \
  --profiles-output database/free_paper_pilot_profiles.json \
  --output database/free_paper_pilot_readiness.json \
  --require-configuration-ready
```

`configuration_ready` confirms the paper account, allowlisted assets, fractionability, and quote access. `execution_ready_now` is true only while the U.S. market is open and quotes are current.

### 2. Publish the exact eligible universe for the next CIO cycle

```bash
python run_free_paper_pilot_universe.py \
  --output database/free_paper_pilot_publication.json
```

The command selects a decision timestamp two minutes in the future by default. Use the exact returned `decision_at` timestamp for the canonical CIO cycle. The publication expires after one day and cannot be reused for another decision timestamp.

### 3. Run the canonical CIO cycle

Run the existing canonical cycle using the exact `decision_at` produced by the publication command. The cycle must preserve the returned eligible-universe publication identifier in portfolio construction.

### 4. Review and approve the exact construction

Open the authenticated Portfolio surface. Review the proposed symbols, weights, funding, turnover, expected costs, and blocks. Approve only the exact displayed construction.

Approval does not bypass any quote, session, universe, portfolio, or reconciliation control.

### 5. Execute the approved paper construction

During U.S. market hours:

```bash
python run_free_paper_pilot.py \
  --construction database/latest_construction.json \
  --decision-identifier '<exact-cio-decision-id>' \
  --as-of '<exact-decision-at>' \
  --eligible-universe-database database/eligible_universe.db
```

The runner:

1. requires an approved paper environment;
2. verifies the live Alpaca paper account and IEX quotes;
3. rejects any symbol outside the allowlist;
4. enforces at least 20% cash;
5. limits one batch to 10% turnover;
6. enforces per-instrument, crypto-proxy, and volatility-proxy limits;
7. requires exact authenticated user approval;
8. delegates to the canonical internal paper executor; and
9. queues the normal completion notification.

## Verify Alpaca broker order and fill integration

Alpaca is registered in the append-only provider activation system as `alpaca-paper-broker`. The activation authorizes only the paper endpoint, internal paper-order transport, and broker evidence. It does not authorize live trading.

Run the neutral paper verification:

```bash
python run_alpaca_paper_broker_smoke.py \
  --activation config/alpaca_paper_broker_activation.json \
  --symbol BTC/USD \
  --notional 10 \
  --output reports/alpaca-paper-broker-smoke.json \
  --require-reconciled
```

The verifier:

1. authenticates the configured paper credentials;
2. requires the active append-only Alpaca provider activation;
3. submits an idempotently identified $10 paper buy, matching Alpaca's minimum order value;
4. records Alpaca request IDs and order-status snapshots;
5. matches the final order to Alpaca `FILL` account activities;
6. detects missing, duplicate, mismatched, or unreconciled fills;
7. submits a paper sell for the exact filled quantity;
8. verifies the broker position returns to its opening quantity; and
9. persists every event in the hash-chained `alpaca_paper_broker.db` ledger.

This round trip validates transport and reconciliation. It is not a portfolio recommendation and does not add the smoke symbol to the `COMPOUNDING` eligible universe.

## Safety limits

| Control | Pilot limit |
| --- | ---: |
| Minimum cash | 20% |
| Maximum batch turnover | 10% |
| Maximum ordinary instrument | 45% |
| Maximum crypto proxy | 5% |
| Maximum volatility proxy | 2% |
| Maximum quote age while market is open | 5 minutes |
| Gross leverage | 1.0x |
| Margin | Prohibited |
| Broker order submission | Paper endpoint only; governed verification path |
| Broker fill evidence | Append-only and reconciled to Alpaca `FILL` activities |
| Real money | Never authorized |

## What this changes—and what it does not

This makes controlled free-provider paper testing and Alpaca broker transport verification operationally possible. It does not mark the institutional all-market readiness report as passed. It does not certify direct derivatives, individual global bonds, direct international listings, or institutional execution quality.

The canonical portfolio remains the product's sole state authority. Broker verification evidence may support readiness only when the exact provider activation, account environment, request IDs, order snapshots, fill activities, event hashes, and reconciliation conclusion are preserved.
