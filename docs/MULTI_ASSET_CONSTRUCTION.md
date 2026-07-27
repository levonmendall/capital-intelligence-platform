# Governed Multi-Asset Construction

Crypto, unlevered spot FX, and international listed equities remain under the sole `COMPOUNDING` mandate. The canonical construction engine still owns sizing and funding. Expanded markets add mandatory feasibility controls; they do not create new ranking or decision authority.

## Required profile

Every expanded symbol entering construction must have exactly one `MultiAssetInstrumentProfile` preserving instrument, venue, jurisdiction, price and settlement currencies, paper-eligibility approval, custody/settlement identity, and execution-model version.

Missing or extra profile coverage blocks construction.

## Initial paper limits

The default development policy limits:

- crypto to 5% of portfolio weight;
- unlevered spot FX to 10%;
- international equities to 25%;
- aggregate non-base-currency exposure to 35%; and
- one foreign currency to 15%.

These are protective defaults for development and paper testing. They are not claims of optimal allocation and remain subject to later investment-process freeze and governance approval.

## Prohibitions

Crypto and FX must be spot and unlevered. Margin, derivatives, lending, staking, forwards, swaps, options, and synthetic notional exposure are blocked. Expanded assets require an active `paper_eligible` approval.

The wrapper validates the canonical construction result after sizing. A target that breaches an asset-class or currency limit fails closed rather than being published as feasible.

Core U.S. equity, ETF, and Treasury-equivalent construction remains compatible and requires no synthetic expanded-market profile.
