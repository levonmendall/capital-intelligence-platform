# Removed legacy analytical orchestration — 2026-08-03

The retired `AnalyticalEngineCycleExecutor` and `LiquidityAwareCycleExecutor` wrappers
were removed after confirming that supported production scheduling uses the canonical
headless CIO operating path instead.

Individual macro, valuation, breadth, momentum, risk, credit, and liquidity engines
remain available through their append-only stores and read-only APIs. Normalization,
synthesis, and governance records remain supported. Tests that exclusively exercised
the removed wrappers were deleted from mixed integration files; active API tests were
preserved.

Git history is the source archive. No investment or execution authority changed.
