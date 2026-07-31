# ZIP / Main Reconciliation

## Compared artifacts

- Initial provisional canonical: GitHub `main` at `9435b4c4edd882734e47197f84eb4588412cd3af`.
- Current provisional canonical: GitHub `main` at `4742dec18113d03334d28f8d734b701aedefd7a5` after PR #278 merged during the audit.
- Comparison artifact: `capital-intelligence-platform--main 7(1).zip`.
- ZIP SHA-256: `db77ed2e134bd591ef1100076bd40769346f8a82ca8cff35529c3c9401d88770`.
- The ZIP contains no `.git` object database, so no commit SHA can be attributed to it.

## Mechanical comparison

| Measure | Result |
|---|---:|
| ZIP files | 948 |
| Initial audited main files | 948 |
| Current main files | 950 |
| ZIP/current-main common paths | 948 |
| Current-main-only paths | 2 |
| ZIP-only paths | 0 |
| Byte-identical ZIP/current-main common paths | 943 |
| Changed ZIP/current-main common paths | 5 |

The updated ZIP is an exact archive of the initial `9435b4c4...` main tree. It
does not contain the later PR #278 provider-validation changes: five modified
paths plus new `providers/databento_options.py` and
`tests/test_databento_options.py`. It remains comparison evidence rather than
an independent source of truth because it contains no Git object database or
deployment metadata.

## Reconciliation decision

1. Keep GitHub `main` as the only provisional source of truth.
2. Do not copy the ZIP over main; doing so would discard the later certified
   provider-validation work from PR #278.
3. Preserve legacy modules only as compatibility/legacy evidence until active imports and behavioral tests classify them.
4. Use Git commits and reviewed PRs—not archive names—to establish future lineage.

## Deployment relevance

The ZIP and both audited main revisions declare the same Render source and
command: branch `main`, Docker context `.`, `python run_render_service.py`, and
public Streamlit child `python -m streamlit run render_app.py ...`. The actual
deployed SHA remains unverified until Render reports `RENDER_GIT_COMMIT` or
deployment metadata is available.
