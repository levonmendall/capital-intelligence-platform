# Commodity prerequisite for controlled paper testing

## Policy

The controlled paper-trading process cannot begin until commodity markets are
included in the exact decision baseline. This is an execution prerequisite, not
an optional research enhancement.

The platform must have current, licensed, point-in-time evidence for:

- gold;
- silver;
- WTI crude oil;
- Brent crude oil;
- natural gas;
- copper; and
- agriculture.

Each benchmark requires market-price history and a certified forward curve. The
curve requirement prevents an ETF or commodity opportunity from being evaluated
only from a spot price while ignoring contango, backwardation, and roll effects.

## Paper-investable exposure

Direct commodity futures, futures options, and commodity options remain
prohibited. Paper exposure is implemented through certified, unlevered,
non-inverse U.S.-listed ETFs in these categories:

- gold;
- silver;
- oil and energy commodities;
- industrial metals;
- agriculture; and
- broad commodities.

The symbols in `config/commodity_paper_test_scope.json` are examples, not a
static investment universe. The actual proxy must be present in the exact
provider-driven certified eligible-universe publication used by construction.

## Evidence sequence

1. Configure a licensed provider for commodity prices, history, and curves.
2. Backfill and reconcile the required benchmarks.
3. Certify market data, forward curves, timestamps, and usage rights.
4. Screen the provider-driven U.S. ETF universe.
5. Certify at least one eligible proxy in every required category.
6. Create the evidence document using
   `config/commodity_paper_test_evidence.example.json` as a template.
7. Run:

```bash
python run_commodity_readiness.py \
  --evidence /run/secrets/commodity-paper-test-evidence.json \
  --report /run/secrets/commodity-paper-test-readiness.json
```

8. Set:

```text
CAPITAL_INTELLIGENCE_COMMODITY_READINESS_REPORT=/run/secrets/commodity-paper-test-readiness.json
```

9. Begin paper execution only after the command exits successfully.

## Execution enforcement

Both `run_paper_execution.py` and `run_multi_asset_paper_execution.py` require a
ready, unexpired commodity report. The report must:

- have an intact SHA-256 content hash;
- match the construction's exact eligible-universe publication;
- include every required benchmark and proxy category;
- contain current temporal provenance;
- contain licensing and certification evidence;
- keep direct derivatives unauthorized; and
- remain unexpired at the execution timestamp.

A missing, stale, tampered, blocked, future-known, or publication-mismatched
report stops execution before the portfolio or quote providers are accessed.

## Important boundary

This prerequisite does not claim that commodities must always receive an
allocation. It guarantees that gold, silver, oil, and other major commodity
opportunities are evaluated and that approved ETF exposure is available when
the CIO concludes it is a superior use of capital. A valid no-action conclusion
remains allowed.
