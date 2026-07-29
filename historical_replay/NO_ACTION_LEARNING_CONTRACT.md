# Governed no-action historical learning

A historical replay cutoff can produce two different types of governed learning observations:

1. **CIO decisions** that reached specialist review and CIO synthesis.
2. **Pre-CIO qualification outcomes** that were rejected before specialist/CIO synthesis.

The second category is not relabeled as a CIO trade decision. Each observation records its decision stage, qualification policy, reasons, opportunity edge, evidence-quality confidence source, asset class, regime, horizon, and model lineage.

For subsequent outcome evaluation, the manifest preserves both:

- `underlying_return_to_next_cutoff`: the asset's raw price return; and
- `realized_return_to_next_cutoff`: decision-relative value used by the governed learning resolver.

For an abstention, avoiding a subsequent loss is positive decision value and missing a subsequent gain is negative decision value. For a supportive action, decision value follows the underlying return. The explicit `realized_outcome` field distinguishes avoided losses, missed opportunities, supported gains, supported losses, and neutral outcomes.

These observations may reduce live confidence or the otherwise supported position size. They may never create a candidate, turn negative current evidence positive, authorize execution, enlarge a position, or promote policy.
