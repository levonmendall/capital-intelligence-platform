# Daily Capital Intelligence Experience

## Purpose

The daily experience answers:

1. What changed?
2. Why does it matter?
3. What opportunity or risk emerged?
4. Should the portfolio change?
5. How confident is the CIO decision?

It is a concise CIO briefing, not a news feed, score dashboard, goal tracker, or display of internal committee mechanics.

## Canonical cycle

```text
Point-in-time evidence
    -> signal and evidence generation
    -> opportunity qualification and ranking
    -> independent specialist analysis
    -> CIO decision
    -> portfolio construction or implementation abstention
    -> thesis monitoring
    -> DailyCapitalIntelligenceSnapshot
```

The current economic-regime, committee, material-change, portfolio-fit, environment, score, and decision-card services remain compatible foundation components while the complete opportunity and CIO layers are implemented.

Every displayed field must share one decision timestamp and linked source identifiers. Presentation code may not rescore evidence, alter a specialist conclusion, manufacture a CIO action, select an unconstrained size, or execute a trade.

## Opening hierarchy

The primary surface should prioritize:

```text
Today's Capital Intelligence

Decision: No material change
Why: The qualified opportunity set and active theses are unchanged.
Portfolio: No action required.
Confidence: 76% — evidence is current with one unresolved market-positioning disagreement.
Would change the conclusion: material earnings revisions, a valuation dislocation, or thesis invalidation.
```

When action is warranted, the same surface identifies the asset, action, expected return, horizon, recommended size, funding implication, thesis, risks, invalidation conditions, confidence, and review date.

The Capital Intelligence Score may appear as supporting environment context. It must not dominate the opening hierarchy, imply expected return, or act as a trading signal.

## Four primary surfaces

1. **Today** — material CIO briefing, qualified opportunity changes, active-thesis changes, action or disciplined no-action, confidence, and review conditions.
2. **Environment** — concise global financial context and the evidence affecting expected returns.
3. **Portfolio** — authorized holdings, constraints, expected portfolio contribution, implementation proposals, costs, and paper activity.
4. **History** — CIO decisions, evidence lineage, thesis transitions, Decision Replay, portfolio outcomes, attribution, and supporting score context.

Internal specialist analyses and dissent are available as progressive analytical detail, not default product navigation.

## Valid daily outcomes

- No material change
- No action required
- Continue monitoring
- New opportunity
- Thesis strengthening
- Thesis weakening
- Portfolio action recommended
- Insufficient evidence
- No superior opportunity

## Honest operating states

| State | Meaning |
| --- | --- |
| `current` | Required evidence is inside freshness and coverage thresholds. |
| `incomplete` | The cycle completed but material evidence or analytical coverage is missing. |
| `stale` | The result exceeds the configured freshness window. |
| `unavailable` | No valid canonical evidence package or decision could be produced. |

Stale, incomplete, and unavailable states must not be relabeled as current. Missing evidence lowers confidence or causes abstention.

## Selective attention

The platform analyzes continuously but interrupts the user only for material opportunity, risk, active-thesis, evidence-quality, implementation, or CIO-decision changes.

Score movement alone does not trigger an alert. Individual goals, retirement targets, preferred risk levels, and personalized investment philosophies may not alter alert eligibility or wording.

## History and auditability

Append-only daily snapshots should support:

- prior-snapshot comparison;
- opportunity-rank changes;
- CIO action and confidence changes;
- active-thesis strengthening, weakening, invalidation, reduction, or exit;
- evidence freshness and coverage changes;
- portfolio implementation and cost records;
- Decision Replay identifiers; and
- later outcome attribution.

Historical context never rewrites what was known, believed, or decided at the original decision time.

## Boundaries

- The interface communicates CIO judgment rather than raw information volume.
- Portfolio access and mandate authorization remain essential security controls, not individualized investment objectives.
- Goal-based onboarding and Personal CIO briefing logic are deprecated and must remain outside the active decision graph during migration.
- The application remains research and paper-only until portfolio optimization, execution controls, walk-forward validation, and governance approval are complete.