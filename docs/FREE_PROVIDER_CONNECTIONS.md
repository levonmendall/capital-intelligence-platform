# Free provider connections

The repository includes one governed connectivity path for six public or free-access services:

| Provider | Connection mode | User action |
|---|---|---|
| FRED | Free registered API key | Set `FRED_API_KEY` |
| SEC EDGAR | Free declared application identity | Set `SEC_USER_AGENT` to an application name plus monitored contact |
| Coinbase Exchange | Public keyless market data | None |
| Kraken Spot | Public keyless market data | None |
| OpenFIGI v3 | Anonymous free access; optional free key for higher limits | Optional `OPENFIGI_API_KEY` |
| GLEIF | Public keyless legal-entity data | None |

Official registration and documentation:

- FRED API keys: <https://fred.stlouisfed.org/docs/api/api_key.html>
- SEC automated access: <https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data>
- Coinbase Exchange API: <https://docs.cdp.coinbase.com/exchange/introduction/welcome>
- Kraken API Center: <https://docs.kraken.com/>
- OpenFIGI API: <https://www.openfigi.com/api>
- GLEIF API: <https://www.gleif.org/en/lei-data/gleif-api/>

## Repository configuration

The authoritative free-service catalog is:

```text
config/free_provider_connections.json
```

The repository-owned public BTC/USD and ETH/USD venue bindings are:

```text
config/crypto_venue_bindings.free.json
```

Configure the common paths:

```bash
export CAPITAL_INTELLIGENCE_FREE_PROVIDER_CATALOG=config/free_provider_connections.json
export CAPITAL_INTELLIGENCE_FREE_PROVIDER_DATABASE=database/free_provider_connections.db
export CAPITAL_INTELLIGENCE_CRYPTO_VENUE_BINDINGS=config/crypto_venue_bindings.free.json
```

Configure the two required user-specific free values:

```bash
export FRED_API_KEY='your-free-fred-key'
export SEC_USER_AGENT='Capital Intelligence your-monitored-email@example.com'
```

An OpenFIGI key is optional:

```bash
export OPENFIGI_API_KEY='your-optional-free-openfigi-key'
```

Never commit these values. Store them in the deployment secret manager or GitHub Actions secrets/variables.

## Verification

Run all probes and persist an append-only report:

```bash
python run_free_provider_connections.py
```

Require every enabled service to be connected:

```bash
python run_free_provider_connections.py --require-all-connected
```

Read the latest persisted report:

```bash
python run_free_provider_connections.py --status
```

The report distinguishes:

- `connected`: structurally valid evidence was returned;
- `credential_required`: a free user-specific value has not been configured;
- `unavailable`: configuration exists but the service or response failed validation;
- `disabled`: the catalog intentionally excludes the service.

Credential values are redacted from errors and are never written to the report database.

## GitHub Actions

`.github/workflows/free-provider-connectivity.yml` runs after relevant changes reach `main`, on demand, and daily.

Configure:

- Actions secret `FRED_API_KEY`;
- repository variable `SEC_USER_AGENT`;
- optional Actions secret `OPENFIGI_API_KEY`.

The workflow always requires Coinbase, Kraken, anonymous OpenFIGI, and GLEIF to be reachable. Once the FRED and SEC values exist, it also requires all six services to connect.

The repository connector can implement and validate the integration, but it cannot create a FRED account key or choose a monitored SEC contact identity on the user's behalf.

## Authority boundary

A successful connectivity report means only that supporting evidence could be retrieved at that time. It does not establish:

- licensed institutional data completeness;
- historical-security-master completeness;
- exchange redistribution rights;
- provider certification;
- all-market data readiness;
- paper-test authorization;
- execution authority;
- broker or real-money authority.

FRED and SEC retain their existing official-source roles. Coinbase and Kraken remain independent venue evidence rather than the complete crypto market. OpenFIGI and GLEIF are supporting identity sources and cannot replace a certified point-in-time global reference-data provider.
