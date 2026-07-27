# Multi-Asset Thesis and Outcome Evaluation

## Governing rule

> **Every recommendation is compared against all other available uses of capital, implemented at the portfolio level, continuously monitored against an explicit thesis, and evaluated afterward using the exact evidence available when the decision was made.**

## Purpose

Crypto, spot FX, and international listed positions must be evaluated in the canonical portfolio base currency without hiding the economic source of the result.

The core point-in-time evaluator remains authoritative for:

- selection;
- sizing;
- timing;
- implementation cost;
- comparison with cash, benchmark, passive portfolio, and every original capital alternative;
- confidence calibration; and
- decision-process quality.

The multi-asset authority adds a complementary decomposition:

```text
local asset return
+ currency translation
+ local/currency interaction
= gross base-currency return
- implementation cost
= net base-currency return
```

It does not reconstruct the original decision, change the CIO action, alter the thesis, or revise portfolio construction.

## Point-in-time observation

`MultiAssetReturnObservation` preserves:

- decision snapshot, CIO decision, living thesis, instrument, symbol, and asset class;
- asset-class approval and evaluation-model version;
- base and price currencies;
- decision, implementation, horizon, observation, and knowledge-cutoff timestamps;
- local prices at decision, implementation, and horizon;
- FX rates to the portfolio base currency at all three boundaries;
- implementation cost;
- quote, FX, source, and evidence identifiers.

The observation fails closed when timestamps are misordered, the cutoff predates observation, prices or rates are invalid, a base-currency asset uses a rate other than `1.0`, or a non-base-currency asset lacks decision, implementation, and horizon FX lineage.

## Attribution

`MultiAssetReturnAttribution` records both position-level returns and portfolio-level contributions. The following identities are enforced:

```text
gross base return = local return + currency return + interaction
net base return = gross base return - implementation cost
net portfolio contribution
  = local contribution
  + currency contribution
  + interaction contribution
  + implementation-cost contribution
```

This prevents a profitable international position from being described as successful local security selection when the result actually came from currency appreciation. It also exposes a local winner that became a base-currency loss because of adverse FX movement.

## Canonical evaluation integration

`MultiAssetPointInTimeEvaluator` validates the observation against the immutable `DecisionEvidenceSnapshot`, then supplies base-currency realized returns to the existing `PointInTimeDecisionEvaluator`.

The original decision snapshot fingerprint, capital-alternative set, specialist packet, policies, models, code version, and thesis remain unchanged. Missing or extra alternative outcomes still block evaluation.

Implementation cost supplied to the core evaluator is the portfolio contribution of the asset-level cost, avoiding double counting.

## Living-thesis integration

`MultiAssetThesisEvidenceAdapter` validates the observation against an existing `LivingThesis`. It produces:

1. A `MultiAssetThesisAssessment` preserving local, currency, interaction, cost, and net return.
2. The standard `ThesisEvidenceUpdate` consumed by the existing `ThesisMonitor`.

Only net base-currency performance is placed in `performance_since_approval`. The decomposition remains separately auditable. The adapter may identify currency as material, but it cannot issue a portfolio action; thesis monitoring may only propose CIO review.

## Persistence

`SQLiteMultiAssetEvaluationStore` is append-only and SHA-256 chained. Updates and deletes are prohibited. Exact replay is idempotent; conflicting content under an existing identifier fails.

## Command

```bash
python run_multi_asset_attribution.py \
  --observation artifacts/multi-asset-return-observation.json \
  --implemented-weight 0.08
```

The command validates and persists the observation and attribution. It does not infer missing prices, FX rates, implementation costs, alternative outcomes, or thesis evidence.

## Product boundary

History and decision replay may show:

- local asset return;
- currency return;
- interaction;
- implementation cost;
- net base-currency return; and
- portfolio contribution.

The product remains paper-only, development remains open, and no performance claim is permitted merely because attribution is available.
