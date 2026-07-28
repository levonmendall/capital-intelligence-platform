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
- records internal simulated fills only; and
- remains unavailable in staging and production.

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

Direct futures, options, individual bonds, spot FX, direct crypto tokens, non-U.S. listings, leveraged funds, inverse funds, and private assets remain prohibited in the pilot.

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

Never commit the key or secret. The adapter rejects the live Alpaca brokerage endpoint.

## Start the pilot

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

1. requires `CAPITAL_INTELLIGENCE_ENVIRONMENT=development`;
2. verifies the live Alpaca paper account and IEX quotes;
3. rejects any symbol outside the allowlist;
4. enforces at least 20% cash;
5. limits one batch to 10% turnover;
6. enforces per-instrument, crypto-proxy, and volatility-proxy limits;
7. requires exact user approval;
8. delegates to the canonical internal paper executor; and
9. queues the normal completion notification.

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
| Broker order submission | Not implemented |
| Real money | Never authorized |

## What this changes—and what it does not

This change makes controlled free-provider paper testing operationally possible. It does not mark the institutional all-market readiness report as passed. It does not certify direct derivatives, individual global bonds, direct international listings, or institutional execution quality.

Outcomes from this pilot may be used as paper-operation evidence only when their exact data source, decision timestamp, universe publication, model version, construction, approval, quote, fill, and reconciliation lineage are preserved.
