# All-Market Institutional Provider Stack

## Purpose

This stack supplies the broad price, identity, history, fixed-income, crypto, derivative-contract, margin, and volatility evidence needed to activate governed paper trading across every classified liquid public-market family.

The repository implements the complete connector, normalization, certification, readiness, and append-only activation path. It does not manufacture commercial contracts, secrets, exchange entitlements, or legal approvals. Those remain explicit deployment evidence and the system fails closed until they exist.

## Selected stack

| Role | Selected authority | Operating boundary |
|---|---|---|
| Global execution-grade market data | LSEG Data Platform plus Databento | LSEG supplies broad global prices, FX, commodities, benchmarks and calendars. Databento supplies direct equities, futures and options quotes, trades, definitions and execution inputs for entitled venues. Two ready providers are required for this role. |
| Historical reference and corporate actions | LSEG DataScope | Historical identifiers, listings, delistings, corporate actions, calendars and benchmark membership must retain publication and availability lineage. |
| Global fundamentals | LSEG fundamentals and filings | Normalized values must preserve original filing, acceptance, revision and restatement boundaries. |
| Evaluated fixed income | ICE Data Services | Evaluated prices, yields, terms, accrued interest, duration, calls, ratings, defaults and liquidity require methodology and timestamp certification. |
| Broad historical multi-asset | EODHD | Used for research history and cross-checking. End-of-day data is never treated as execution-grade bid/ask liquidity or a survivorship-safe security master by itself. |
| Independent crypto validation | Coinbase Exchange and Kraken | Both venues must be live, separately certified and mapped to the same canonical instrument identity. Public connectivity is not custody, execution, storage-rights or paper-simulation approval. |
| Derivative contract definitions | Databento | Point-in-time definitions, multipliers, strikes, expirations, exercise style, tick sizes, venue and lifecycle data. |
| Margin and collateral | CME, OCC and ICE clearing schedules | All three sources are required. Schedules must be mapped to exact contracts and effective timestamps before they can govern simulated capital. |
| Volatility surfaces | Governed derived surface compiler | Builds point-in-time surfaces from certified option quotes, contract definitions, rates and dividends. The report records source identities, breadth, freshness, method version and model limitations. |

## Source-controlled components

- `config/all_market_provider_bundle.json` — exact provider roles, redundancy and required evidence.
- `config/provider_bindings/*.example.json` — provider-neutral normalization templates. Placeholder URLs are rejected by the readiness authority.
- `config/eodhd_instrument_bindings.all_markets.json` — representative historical replay seeds; never the complete universe authority.
- `config/crypto_venue_bindings.all_markets.json` — canonical Coinbase/Kraken mappings for the initial broad crypto validation set.
- `config/provider_activations/all_markets/*.example.json` — disabled human-completion activation documents.
- `run_all_market_provider_bundle.py` — assesses credentials, bindings, contracts, license approvals, certifications and append-only activations.
- `run_crypto_venue_validation.py` — validates every configured Coinbase/Kraken pair for freshness, crossed books and cross-venue divergence without granting custody or execution authority.
- `run_volatility_surface.py` — builds canonical point-in-time volatility surfaces.
- `run_derivative_data_certification.py` — certifies contract, margin and volatility evidence.
- `run_all_markets_paper_readiness.py` — requires the provider bundle and derivative certification before reporting `paper_ready`.

## Activation sequence

1. Execute commercial agreements and confirm permitted storage, retention, internal display, derived analytics and paper simulation.
2. Provision API credentials through the deployment secret manager.
3. Replace each example normalization binding with the reviewed account-specific endpoint, schema and timestamp mapping.
4. Backfill point-in-time history and reconcile identifiers, currencies, calendars, corporate actions and prices.
5. Certify each provider against freshness, completeness, provenance, revisions, outages and service-level policy. Run `run_crypto_venue_validation.py --require-valid` for every configured Coinbase/Kraken mapping and retain the report as venue-validation evidence.
6. Build derivative contract, margin and volatility evidence and run `run_derivative_data_certification.py --require-certified`.
7. Complete the provider activation templates, setting `enabled` and every approval field only after human review.
8. Place the completed activation documents in one reviewed directory and append them with `run_provider_activation_package.py --activation-directory ...`; the command rejects missing, extra, disabled, expired or future activations before writing.
9. Run `run_all_market_provider_bundle.py --require-active`.
10. Run `run_all_markets_paper_readiness.py --derivative-data-certification ... --require-paper-ready`.

No activation grants live-trading or real-money authority.
