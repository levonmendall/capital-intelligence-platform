# Governed Historical Learning Contract

Every live Canonical CIO candidate must carry a `HistoricalLearningContext` in its immutable specialist packet.

The context resolves only replay evidence available by the live decision timestamp. It prefers exact-symbol observations, then governed asset-class comparables, and records macro-regime, market-regime, decision-horizon, sample-size, strictness, support, abstention, and realized next-cutoff outcome coverage.

Historical learning is a one-way control:

- it may cap specialist and CIO confidence;
- it may reduce the otherwise supported position target;
- it must disclose missing, limited, non-strict, or adverse evidence;
- it cannot raise expected return, confidence, or position size;
- it cannot create a candidate, reverse a negative current assessment, bypass a veto, authorize execution, or promote policy.

When the replay manifest is unavailable, the packet explicitly records that state and caps confidence, but absent evidence does not invent a position-size reduction. Actual limited or adverse historical evidence may reduce size under the governed multiplier.

Historical replay itself receives a `not_applicable` learning context so it cannot consume its own future output. Current point-in-time evidence remains controlling in every live decision.
