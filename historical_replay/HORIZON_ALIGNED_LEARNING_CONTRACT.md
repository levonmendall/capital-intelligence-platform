# Horizon-aligned governed historical learning

The complete replay manifest and the live calibration input serve different governance purposes.

## Complete replay manifest

`latest-canonical-replay.json` retains every governed observation for research and audit, including:

- true CIO decisions;
- pre-CIO analytical qualification outcomes;
- capability-policy-only outcomes;
- raw underlying next-cutoff returns;
- next-cutoff monitoring value;
- raw underlying returns at the original decision horizon; and
- decision-relative value at the original decision horizon.

This complete manifest is displayed in History and retained in the protected certification artifact. It is not itself the live sizing input.

## Calibration-safe sidecar

`latest-canonical-learning.json` is the only historical manifest consumed by live committee and CIO calibration. It:

- excludes observations whose only reason was a capability or authorization boundary;
- retains analytical abstentions and true CIO decisions as distinct observation types;
- uses outcomes measured at each observation's stated decision horizon;
- never substitutes a monthly monitoring result for an annual decision result;
- bounds extreme missed-opportunity regret at -100% only in the live calibration field because the typed learning context uses a return-domain lower bound of -100%; and
- retains the full unbounded decision-relative regret in the complete replay artifact.

The live resolver refuses a sidecar with an unsupported schema or any outcome alignment other than `decision_horizon`.

## Authority boundary

Historical evidence may reduce forecast confidence or the otherwise supported target size. It cannot create a candidate, turn negative current evidence positive, increase expected return, increase confidence, increase position size, bypass specialist vetoes, authorize paper or real-money execution, or promote policy.
