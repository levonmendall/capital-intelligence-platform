# Retired code boundaries

The repository preserves removed executable code through Git history rather than by
keeping dormant Python under an `archive/` package.

`tests/test_retired_code_boundaries.py` enforces three repository invariants:

1. approved retired paths must remain absent unless a separately reviewed architecture
   change explicitly restores them;
2. active Python may not import retired module namespaces; and
3. the canonical CIO, committee, opportunity, construction, paper-execution, API, and
   Streamlit authority modules must remain present.

The guard covers the discontinued investor-personalization and Personal CIO surfaces,
the Institutional Market Score v2 and shadow stack, the disconnected pre-canonical
intelligence decision architecture, retired analytical wrapper orchestration, and
isolated unused compatibility modules removed by the 2026-08-03 cleanup program.

This is an architectural regression guard, not an assertion that every unlisted module
is active. Unknown code still requires import, entrypoint, workflow, and test-ownership
evidence before deletion.
