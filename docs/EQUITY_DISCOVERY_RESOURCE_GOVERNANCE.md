# Equity discovery resource governance

## Production incident

The August 3, 2026 production retry progressed through the provider and pagination
repairs, then the Render instance exited with status 137. The active architecture had
collapsed two distinct stages of the governed funnel:

1. broad eligible-universe review; and
2. full decision-evidence preparation.

Every liquid company that passed the inexpensive identity, snapshot, price, and
liquidity screen was receiving both multi-horizon discovery history and the later
10-year candidate-evidence package. The service also runs the API, Streamlit,
historical backfill, backup, readiness watchdog, and paper operator in one container.
Retaining the complete bar payload for every passing company therefore created an
unbounded memory requirement unrelated to investment quality.

## Correction

The U.S.-equity lane now preserves a staged, versioned funnel:

1. Every eligible Alpaca/SEC-listed company remains inside broad identity and current
   snapshot review. No maximum snapshot-universe count is applied by default.
2. Current price, dollar volume, daily movement, and liquidity rank the complete
   snapshot-covered set.
3. The strongest 400 companies receive 550-day multi-horizon analysis. Every current
   holding and every tracked unresolved thesis is included even when it ranks below
   that boundary.
4. Deep history is retrieved and converted to derived features in batches of at most
   25 symbols; each raw batch is released before the next batch is requested.
5. The strongest 64 new companies proceed into the full 10-year candidate-evidence
   stage. Current holdings and tracked theses are added outside that new-candidate
   allowance.
6. Symbols that do not advance remain explicitly classified as
   `outside_deep_evidence_cohort` or `outside_decision_evidence_cohort`; they are not
   represented as fully analyzed or as rejected by the CIO.
7. Prices from deep-reviewed symbols remain available for missed-opportunity and
   unresolved-outcome evaluation.

The 64-company decision cohort can represent up to 64% of portfolio NAV at the 1%
exploratory company cap. Strategic cross-asset wrappers, existing scaled holdings, and
the required cash reserve remain separate, so this operational boundary does not bind
feasible portfolio construction.

## Governance boundary

This correction does not shrink the eligible universe, lower an investment threshold,
change the ranking formula, shorten the evidence window for an admitted candidate,
remove holding review, manufacture evidence, authorize the CIO, alter construction,
execute an order, or enable real money. It restores the intended distinction between
broad screening and decision-eligible evidence while imposing a finite production
memory envelope.
