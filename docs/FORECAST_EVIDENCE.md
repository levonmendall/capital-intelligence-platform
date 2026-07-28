# Governed Forecast Evidence

## Authority boundary

Forecast records remain supporting evidence. A forecast does not create or qualify a candidate, alter the opportunity ranking, determine a position size, issue a CIO action, or authorize execution.

Every forecast record permanently states:

```text
supporting_only = true
independent_decision_authority = false
```

A completed screening cycle may attach forecasts only to an already-qualified candidate. When a reviewed candidate-specific scenario translation is present, the evidence is delivered to the **Cross-Asset Forecast & Scenario Specialist**. The specialist issues an independent analytical position—supportive, neutral, opposed, or abstain—but the CIO remains the only investment-action authority.

## Separation from other specialists

The Forecast & Scenario Specialist evaluates:

- calibrated forward scenario distributions;
- model agreement, historical calibration, and forecast stability;
- forecast-horizon alignment with the candidate decision horizon;
- candidate-specific return effects under each scenario;
- expected path drawdown and drawdown probability;
- cross-asset confirmation across rates, credit, FX, commodities, equities, volatility, and crypto; and
- observable forecast revisions or regime changes that require review.

It does not duplicate the Market Strategist’s trend, momentum, breadth, positioning, or liquidity mandate. It does not duplicate the Macro Strategist’s current economic-regime diagnosis. It cannot veto evidence, block implementation, propose funding, or determine final size.

## Forecast record contract

`GovernedForecastEvidence` preserves:

- forecast target;
- as-of timestamp and exact knowledge cutoff;
- generation timestamp;
- horizon end and computed horizon length;
- mutually exclusive scenario names and probabilities that sum to one;
- confidence;
- calibration method and sample size;
- historical accuracy;
- model and data-vintage versions;
- evidence and originating-fact identifiers;
- limitations; and
- invalidation conditions.

A forecast generated after the decision, or using evidence after the decision cutoff, cannot enter the production context.

## Candidate translation contract

`CandidateForecastSupport` binds one or more forecasts to one already-qualified candidate and one exact decision boundary.

Version 1 references remain lineage-only. Version 2 may additionally carry a reviewed specialist translation containing:

- exactly one candidate return impact for every scenario in every referenced forecast;
- expected path drawdown for every scenario;
- model-agreement and forecast-stability measures;
- material path-drawdown probability;
- cross-asset signals and contradictory evidence;
- review conditions;
- translation method; and
- translation model version.

Partial scenario coverage fails closed. Scenario mappings cannot reference undeclared forecasts. The translation record still declares no candidate-creation, ranking, sizing, decision, or execution authority.

## Production context

`ForecastSupportingProductionContextProvider` wraps the canonical production-context adapter. It:

1. verifies both append-only forecast stores;
2. rejects references outside the qualified candidate set;
3. loads each exact forecast and enforces point-in-time usability;
4. rejects conflicting data or model versions;
5. requires complete scenario translation before creating a specialist context;
6. combines multiple forecasts using disclosed confidence, calibration, accuracy, and sample support;
7. attaches a `CrossAssetForecastSpecialistContext` to the candidate; and
8. adds exact forecast, translation, evidence, model, and data identities to the immutable manifest.

A reference without a complete version 2 translation remains lineage-only. In that case the Forecast & Scenario Specialist abstains and contributes no return adjustment.

## CIO reconciliation

The forecast specialist’s expected-return impact is reconciled only after independent review. The reconciliation policy:

- excludes forecast abstentions;
- discounts evidence shared with the baseline candidate model or other specialists;
- applies a lower forecast adjustment share than the other return specialists;
- imposes a smaller forecast-specific per-role cap; and
- preserves the CIO as sole action and final-sizing authority.

## Persistence

Two append-only SHA-256 chains remain active:

- `SQLiteForecastEvidenceStore` for forecast records;
- `SQLiteCandidateForecastSupportStore` for candidate references and reviewed scenario translations.

Updates and deletes are prohibited. Exact replay is idempotent; conflicting content under an existing identifier fails.

## Command

Record a reviewed forecast:

```bash
python run_forecast_evidence.py --forecast artifacts/forecast.json
```

Record a candidate reference or version 2 specialist translation after screening:

```bash
python run_forecast_evidence.py \
  --candidate-support artifacts/candidate-forecast-support.json
```

Inspect the latest usable forecast for a target and cutoff:

```bash
python run_forecast_evidence.py \
  --latest-target "global real GDP growth" \
  --knowledge-cutoff 2026-07-27T11:55:00+00:00
```

A forecast record does not certify a provider, approve an asset class, authorize real money, or guarantee a realized outcome.
