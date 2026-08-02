# Complete Certified-Universe Investment Review

The canonical discovery process screens the complete certified investment universe for
every market lane scheduled at the decision timestamp.

The process is:

1. Load the complete certified catalog.
2. Apply lifecycle, metadata, freshness, provider-lineage, liquidity, and point-in-time
   evidence checks.
3. Obtain substantive provider-enriched value, momentum, carry, and
   improving-conditions evidence.
4. Deep-analyze every asset that remains eligible and evidence-complete.
5. Forward every asset that passes the governed market and evidence checks into formal
   opportunity qualification.
6. Send every formally qualified candidate through all six independent specialists and
   then to the CIO.
7. Allow portfolio construction to determine feasible sizing only after the CIO has
   considered the candidate.

## No candidate-count cutoff

Scores and sleeve rankings determine review order and provide an auditable explanation
of relative merit. They do not create a top-N shortlist.

The canonical runtime does not apply:

- the former 200-candidate deep-analysis limit;
- the former 20- or 24-instrument per-lane shortlist limits;
- a committee-attention quota;
- a CIO-review quota; or
- a portfolio-construction quota that can prevent prior CIO consideration.

Current holdings and tracked instruments remain part of the continuity path, but they
are not granted exclusive access to a bounded opportunity allocation. Every ordinary
asset that passes the same governed checks is analyzed as well.

Inherited `maximum_deep_candidates_per_lane` and `selected_*` configuration values are
retained only so older configuration files can still be read. They are not active
decision authorities. Discovery manifests explicitly record
`candidate_count_limit_applied: false`.

## What can still exclude an asset

Removing arbitrary count limits does not weaken the investment process. An asset can
still be excluded when it is not certified, is outside the approved market scope, has
incomplete or stale evidence, lacks factor provenance, fails lifecycle or instrument
integrity checks, lacks sufficient history, falls below the liquidity floor, has
unavailable point-in-time market evidence, or fails formal opportunity qualification.

The system does not lower return, evidence, liquidity, downside, cost, cash-hurdle, or
portfolio-risk standards merely to increase the number of candidates.

## Provider-enriched factors remain mandatory

The canonical runtime does not populate value, momentum, carry, or
improving-conditions scores from catalog completeness, symbol order, spread metadata,
deterministic tie-breaking, or another synthetic proxy.

Before comprehensive discovery runs, the provider pipeline must publish
`database/provider-enriched-preselection.json` or set
`CAPITAL_INTELLIGENCE_PROVIDER_PRESELECTION_PATH` to another governed publication.

The publication must use schema
`capital-intelligence-provider-preselection.v1` and contain, for every eligible
new-opportunity candidate:

- a normalized score between zero and one for value, momentum, carry, and improving
  conditions;
- the underlying finite raw measurement and its units;
- the measurement horizon;
- provider identity and methodology version;
- point-in-time observation and availability timestamps; and
- one or more immutable provider evidence identifiers.

The loader creates factor-specific lineage identifiers and carries them into the
discovery manifest. A score without factor-specific provider lineage is unavailable.
Missing, stale, future-known, malformed, or incomplete factor evidence makes the
affected candidate ineligible. The system does not substitute a neutral score.

Factor methodology remains asset-specific. Equity value can use normalized earnings or
free-cash-flow yield, while bond, FX, crypto, futures, and option value and carry require
their own governed models. A factor remains unavailable when an appropriate model or
certified evidence source does not exist.

## Committee and CIO invariant

The formal opportunity queue has complete candidate coverage: every supplied candidate
is represented as either qualified or rejected with reasons. There is no ranked-queue
slice.

For every qualified queue item, the canonical CIO cycle:

- creates the six-specialist packet;
- records the specialist evidence, concerns, vetoes, and portfolio recommendation;
- sends the complete packet to the CIO;
- records the CIO decision; and
- only then performs portfolio construction across all actionable decisions.

Portfolio constraints may reduce an approved target or leave it at zero, but they do not
erase the fact that the candidate received specialist and CIO consideration.

Discovery remains nomination-only. It cannot independently qualify, size, authorize,
execute, or promote an investment. CIO-only authority, fail-closed evidence handling,
the cash hurdle, independent construction, append-only lineage, and paper-only execution
remain binding.
