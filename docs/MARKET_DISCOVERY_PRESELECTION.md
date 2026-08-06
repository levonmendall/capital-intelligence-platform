# Complete Certified-Universe Investment Review

The canonical discovery process screens the complete certified investment universe for
every market lane scheduled at the decision timestamp.

The process is:

1. Load the complete certified provider catalogs and merge the optional
   provider-neutral `capital-intelligence-certified-investable-catalog.v1`
   publication.
2. Build or reuse the current governed provider-factor publication for the exact
   certified catalog.
3. Apply lifecycle, metadata, freshness, provider-lineage, liquidity, and point-in-time
   evidence checks.
4. Obtain substantive provider-enriched value, momentum, carry, and
   improving-conditions evidence wherever each factor is economically applicable.
5. Deep-analyze every asset that remains eligible and evidence-complete.
6. Forward every asset that passes the governed market and evidence checks into formal
   opportunity qualification.
7. Send every formally qualified candidate through all six independent specialists and
   then to the CIO.
8. Allow portfolio construction to determine feasible sizing only after the CIO has
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

## Complete review does not require a forced candidate

A scheduled lane may truthfully complete with zero nominated assets. That outcome is
valid only when:

- the current certified catalog for the lane is nonempty;
- substantive provider-factor authority was established for the lane;
- every current catalog record has one explicit selected or excluded outcome; and
- no catalog record disappears between discovery, screening, and publication.

A missing catalog, a systemic factor-publication failure, a lane with no substantive
provider-factor lineage, or a partially resolved catalog remains fail-closed. This
distinguishes “the market was fully reviewed and nothing qualified” from “the market was
not evaluated.” It does not lower thresholds merely to produce a candidate or trade.

## No static asset-class or instrument-list authority

The built-in exchange directories, futures roots, and option underlyings are bootstrap
sources, not the boundary of the investment universe. A deployment can set
`CAPITAL_INTELLIGENCE_CERTIFIED_INVESTABLE_CATALOG` to a complete, point-in-time,
provider-neutral publication. Every classified record in that publication is merged
into discovery and receives the same evidence and qualification process.

The publication must attest `complete: true`, preserve stable instrument identities,
and contain no future-known membership. Once configured, a missing, malformed, or
incomplete publication fails closed; the system does not silently revert to a smaller
static list. The former 25,000-directory-record compatibility setting has no active
selection authority. A provider response that reaches the provider-contract
completeness sentinel also fails closed rather than being treated as a complete
universe.

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

Before comprehensive screening begins, the canonical runtime builds or reuses
`database/provider-enriched-preselection.json`, or the path configured through
`CAPITAL_INTELLIGENCE_PROVIDER_PRESELECTION_PATH`. The publication is keyed to the exact
certified-catalog fingerprint so an older or different universe cannot silently satisfy
the current cycle.

Directory markets use bounded exchange-wide provider snapshots to avoid per-security
request fan-out. Derivative and other non-directory records use their provider-native
point-in-time history probes. The publisher writes atomically to persistent state and
has nomination-evidence authority only; it cannot qualify, size, authorize, execute, or
promote an investment.

The publication must use schema
`capital-intelligence-provider-preselection.v1`. For each governed factor, it must
provide either:

- a substantive normalized score between zero and one, the underlying finite raw
  measurement and units, measurement horizon, provider, methodology version,
  point-in-time timestamp, and immutable evidence identifiers; or
- `applicability: not_applicable`, together with a substantive rationale, provider,
  applicability-method version, point-in-time timestamp, and immutable evidence
  identifiers.

At least one substantive factor must be scored for every published new-opportunity
signal. A missing factor is not equivalent to a governed not-applicable determination.
The loader creates separate `provider-factor:` and
`provider-factor-not-applicable:` lineage identifiers and carries them into the
discovery manifest. Missing, stale, future-known, malformed, or unprovenanced factor
evidence makes the affected candidate ineligible. If an entire scheduled lane lacks
substantive provider-factor lineage, the lane itself fails closed instead of being
misreported as a valid all-excluded result. The system never substitutes a neutral
score.

Factor methodology remains asset-specific. Equity value can use normalized earnings or
free-cash-flow yield, while bond, FX, crypto, futures, option, volatility, and alternative
instruments require their own governed models. A factor that is not economically
meaningful is documented as not applicable rather than being used to exclude the asset.

## Capability-based ownership and execution

Every classified public-market family can appear in the active paper universe. The
execution contract no longer contains an asset-class/instrument-type whitelist. The
exact active universe records the provider adapter, instrument structure, session,
custody and settlement identifier, execution model, contract and lifecycle models,
leverage, and risk characteristics required for paper implementation.

The production opportunity engine is always built from the exact active-universe
capability authority. The paper executor must load the same eligible-universe
publication used by construction. A missing or mismatched active publication fails
closed and is never replaced by the historical 15-instrument static pilot list.

Portfolio limits can still reduce or reject an allocation after CIO consideration.
Those controls protect compounding; they do not remove the asset from analysis or CIO
review.

## Scalable portfolio search

The construction optimizer no longer uses a fixed four-state beam. Its search width
expands with the number of CIO-approved intents, uses exact subset-scale capacity for
small sets, and preserves a governed workload ceiling for large sets. Every approved
candidate is retained in the first search generation, while portfolio merit and risk
constraints determine the final owned subset.

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
