# All-Markets Paper Activation

## What the repository now guarantees

Every classified liquid public-market family has a governed analytical,
construction, execution, portfolio-accounting, and readiness path. The release
suite runs a deterministic mechanical rehearsal across international equities,
fixed income, commodities, FX, crypto, real estate, futures, options,
volatility, and liquid alternatives.

That rehearsal uses fixtures. It proves implementation mechanics and certified
execution lineage; it does not certify an external provider or claim that live
market evidence is available.

## Runtime provider integration

`providers.configured_dataset.ConfiguredDatasetProvider` is the vendor-neutral
landing-zone connector. A binding document controls:

- provider identity and API version;
- HTTPS endpoint paths;
- credential environment-variable references;
- query rendering for symbol, date range, knowledge cutoff, and limits;
- JSON payload extraction;
- observation and availability timestamps;
- record identifiers, quality state, and limitations; and
- every dataset used by the all-market readiness manifest, including derivative
  contracts, margin/collateral, volatility surfaces, calendars, benchmarks, and
  execution inputs.

The checked-in example is:

```text
config/configured_dataset_provider.example.json
```

Create a reviewed binding outside source control, inject its path, and run a
backfill with the existing provider-neutral runner:

```bash
export CAPITAL_INTELLIGENCE_CONFIGURED_DATASET_PROVIDER=/run/secrets/provider-binding.json
python run_provider_backfill.py \
  --plan /run/secrets/provider-backfill-plan.json \
  --output-directory data/provider-backfills/provider-name
```

Use this factory in a backfill plan:

```text
providers.configured_dataset:build_from_environment
```

### Canonical pipeline adapters

Raw provider responses do not enter investment logic directly. The configured connector now has strict adapters for the three canonical complete-universe boundaries:

- `ConfiguredSecurityMasterProvider` accepts only a canonical `security-master-catalog.v1` payload and validates an authoritative point-in-time snapshot before ingestion;
- `ConfiguredUniverseMetricsProvider` accepts point-in-time liquidity and analytical-coverage records and rejects duplicate, future-observed, or future-available metrics; and
- `ConfiguredCandidateScreeningProvider` accepts only `candidate-screening-decision.v1`, preserving exact instrument identity, timestamp, and opportunity-cost context.

Configure their binding documents with:

```text
CAPITAL_INTELLIGENCE_SECURITY_MASTER_DATASET_BINDING
CAPITAL_INTELLIGENCE_UNIVERSE_METRICS_DATASET_BINDING
CAPITAL_INTELLIGENCE_CANDIDATE_SCREENING_DATASET_BINDING
```

Ingest and activate the authoritative catalog:

```bash
python run_security_master.py --require-activation
```

`run_full_universe_screening.py` automatically uses the configured metrics and candidate adapters when explicit `module:function` factories are not supplied.

## Provider activation authority

A provider must not be enabled by editing the repository manifest. Runtime
approval is recorded in the append-only, expiring, hash-chained provider
activation registry.

Start from:

```text
config/provider_activation.example.json
```

After licensing review, historical backfill, reconciliation, service-level
review, and deterministic certification, append the approval:

```bash
python run_provider_activation.py \
  --activation /run/secrets/provider-activation.json \
  --database database/provider-activations.db
```

Inspect active records at a point in time:

```bash
python run_provider_activation.py \
  --status \
  --evaluated-at 2026-07-28T18:00:00+00:00
```

An activation may narrow a provider's source-controlled domains. It cannot add
an undeclared domain or authoritative role. Expired or absent records leave the
provider disabled.

## Decision-information source activation

Maximum decision-information sources use a separate append-only activation registry so licensed news, policy, filings, positioning, physical-market, on-chain, weather, and alternative-data sources do not require source-manifest edits.

```bash
python run_decision_information_activation.py \
  --activation /run/secrets/decision-information-activation.json
```

Start from `config/decision_information_activation.example.json`. Configure canonical record ingestion with `CAPITAL_INTELLIGENCE_DECISION_INFORMATION_DATASET_BINDING`; the reviewed binding must return `decision-information-record.v1` objects with exact event, publication, availability, correction, license, and provenance fields.

Both `run_decision_information_readiness.py` and `run_data_readiness.py` resolve active source approvals at the evaluation timestamp.

## Asset-specific evidence operations

Asset-family approval does not replace candidate evidence. Publish each point-in-time asset-specific packet to the append-only registry:

```bash
python run_asset_specific_evidence.py \
  --packet /run/secrets/asset-evidence-packet.json
```

Inspect the exact packets available to one screening cycle:

```bash
python run_asset_specific_evidence.py \
  --cycle screening:2026-07-28 \
  --as-of 2026-07-28T18:00:00+00:00
```

## Asset-family activation

Every non-core family also requires at least one active, structure-specific
`paper_eligible` approval in `database/asset-class-governance.db`. Direct tokens,
listed funds, cash instruments, futures, and options require separate profiles
when their custody, session, lifecycle, or settlement models differ.

```bash
python run_asset_class_governance.py \
  --approval /run/secrets/asset-class-approval.json
```

## Readiness commands

Prove repository-internal coverage and list external blockers:

```bash
python run_all_markets_paper_readiness.py --require-internal-ready
```

Require actual provider and asset-class activation:

```bash
python run_all_markets_paper_readiness.py \
  --provider-binding /run/secrets/global-market-data-binding.json \
  --provider-binding /run/secrets/global-reference-data-binding.json \
  --provider-binding /run/secrets/fixed-income-data-binding.json \
  --env-file /run/secrets/data-providers.env \
  --require-paper-ready
```

Run the deterministic execution rehearsal:

```bash
python run_all_markets_paper_rehearsal.py --require-complete
```

Run the combined market-data and maximum-information gate:

```bash
python run_data_readiness.py \
  --provider-activation-database database/provider-activations.db \
  --env-file /run/secrets/data-providers.env
```

## External inputs that code cannot create

The product cannot honestly declare all markets paper ready until operators
supply and approve:

1. licensed global reference and historical security-master data;
2. execution-grade prices, bid/ask liquidity, FX conversion, calendars, and
   benchmarks;
3. global fundamentals, filings, and corporate actions;
4. evaluated fixed-income terms, prices, and liquidity;
5. independent multi-venue crypto identity and liquidity validation;
6. futures and options contract definitions, margin/collateral rules, and
   lifecycle events;
7. volatility surfaces and derivative-market validation;
8. sufficient point-in-time historical backfills and revision history;
9. documented storage, backup, derived-analysis, display, and paper-simulation
   rights;
10. active provider certifications, asset-class approvals, operational evidence,
    and final readiness-gate certifications.

Missing external evidence blocks the affected instrument or market. It does not
remove that market from analysis, and it never creates live-trading authority.

## Provider bundle and derivative certification

Paper readiness now requires the concrete provider bundle in `config/all_market_provider_bundle.json` and a current `derivative-data-certification-report.v1`. See [All-Market Institutional Provider Stack](ALL_MARKET_PROVIDER_STACK.md).
