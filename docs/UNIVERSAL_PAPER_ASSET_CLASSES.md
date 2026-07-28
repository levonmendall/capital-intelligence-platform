# Universal Paper Asset-Class Availability

## Scope

The canonical internal paper engine supports every classified liquid public-market family:

- U.S. equities;
- U.S. ETFs;
- cash equivalents;
- fixed income;
- international equities;
- commodities;
- foreign exchange;
- cryptoassets;
- real estate;
- futures;
- options;
- volatility instruments; and
- liquid alternatives.

`other` remains prohibited because an unclassified instrument cannot receive reliable identity, valuation, risk, execution, custody, lifecycle, or evaluation controls.

The governing scope is versioned in:

```text
config/universal_paper_asset_classes.json
```

## Meaning of available

Availability means the class can pass the canonical internal paper path with:

- a classified instrument identity;
- a certified eligible-universe record;
- a paper-eligible instrument profile;
- an asset-appropriate market-session model;
- current point-in-time bid, ask, mark, liquidity, and FX evidence;
- a cost and spread model;
- portfolio construction limits;
- simulated execution and position accounting;
- append-only fill lineage; and
- exact portfolio reconciliation.

This is not the same as provider-connected deployment readiness. A class becomes provider-backed paper-ready only after its licensed sources, bindings, certifications, approvals, launch evidence, human approval, and runtime switch are active.

## Conservative execution boundaries

The universal paper scope remains:

- long-only;
- maximum gross leverage of 1.0;
- unlevered spot for direct FX and crypto;
- long-premium, defined-risk options only;
- fully collateralized notional accounting for futures and volatility futures;
- no naked options;
- no short sales;
- no inverse or leveraged structures unless a future governance policy explicitly certifies them;
- no private assets; and
- no live broker order routing.

Commodity exposure may use governed spot, listed funds, or fully collateralized futures. Fixed income may use individual bonds or listed funds. International assets preserve local currency, FX translation, venue, settlement, and calendar lineage.

## Required validation

Run:

```bash
python run_universal_paper_availability.py \
  --evaluated-at <TIMESTAMP> \
  --output reports/universal-paper-availability.json \
  --require-available
```

The command performs an exact 13-class mechanical rehearsal. It fails when a class is missing from the scope, policy, or simulated-fill result.

The deterministic release plan runs this command before the full test suite. A release cannot pass if universal paper coverage regresses.

## Provider-backed activation

The institutional all-market readiness command remains:

```bash
python run_all_markets_paper_readiness.py \
  --require-paper-ready
```

That command requires genuine provider activations, licensed data, point-in-time history, runtime bindings, derivative certification, decision-information coverage, and active asset-class approvals. The internal universal rehearsal cannot satisfy or bypass those external requirements.

## Product boundary

The product may analyze private-market and other non-executable evidence when legally available, but those records do not become paper-tradable assets. Paper eligibility is limited to classified liquid public instruments that can be valued and reconciled through the canonical portfolio authority.
