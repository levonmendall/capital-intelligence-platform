# Deterministic Release Validation

## One command

The complete functional release gate is:

```bash
python run_release_validation.py
```

The command uses Python 3.11, sets deterministic environment controls, runs each step with an independent timeout, fails on the first error, and writes an incremental report to:

```text
reports/release-validation.json
```

The test suite also writes:

```text
reports/pytest-results.xml
```

CI invokes the same command. There is no separate regime-allocation, weighted-committee, or legacy release pipeline.

## Ordered release plan

The default command runs:

1. Python compilation;
2. platform initialization;
3. complete twelve-stage plan validation;
4. canonical intelligence initialization;
5. universal-market internal-readiness validation;
6. deterministic all-market paper-execution rehearsal;
7. the full deterministic test inventory;
8. Python 3.11 validation-image build;
9. in-container fenced workflow and canonical CIO acceptance; and
10. hardened runtime-image build.

For local diagnostics without Docker:

```bash
python run_release_validation.py --host-only
```

`--host-only` is not a complete release gate.

## Deterministic environment

The command sets:

```text
PYTHONHASHSEED=0
TZ=UTC
LC_ALL=C.UTF-8
LANG=C.UTF-8
PYTHONPATH=<repository root>
CAPITAL_INTELLIGENCE_DAILY_STAGE_BINDINGS=<validation bindings>
```

Validation bindings are synthetic acceptance fixtures and do not authorize production investment activity.

## Duration budgets

Each step has a wall-clock limit:

| Step | Limit |
| --- | ---: |
| Compilation | 5 minutes |
| Initialization | 5 minutes |
| Daily plan validation | 2 minutes |
| Intelligence initialization | 5 minutes |
| Universal-market internal readiness | 2 minutes |
| All-market paper-execution rehearsal | 3 minutes |
| Full test inventory | 25 minutes |
| Validation image build | 10 minutes |
| Container acceptance | 10 minutes |
| Runtime image build | 10 minutes |

The enclosing GitHub Actions job has its own 45-minute limit. A timeout is reported separately from a command failure.

## Diagnostics

After every step, the report is atomically replaced with:

- command and timeout;
- start and completion times;
- measured duration;
- return code;
- status: `passed`, `failed`, or `timed_out`;
- bounded stdout and stderr tails;
- aggregate pass, failure, and timeout counts; and
- explicit no-real-money and no-performance-claims flags.

Diagnostics are bounded to prevent a failing subprocess from exhausting artifact storage while preserving the most relevant trailing output.

## CI and security separation

The validation workflow uploads the JSON and JUnit reports as one release artifact. Security remains an independent workflow containing:

- CodeQL;
- Python dependency audit;
- container high/critical scan evidence; and
- zero-fixable-critical enforcement.

A green functional report cannot hide a security failure, and a green security workflow cannot replace the functional release command.

## Release boundary

This command proves that the repository code, shipped plan, universal market capability map, deterministic all-market execution mechanics, synthetic container workflow, and canonical CIO integration pass on the tested commit. It does not prove licensed provider availability, production dataset or stage-binding approval, historical backfill completion, backup restoration, multi-day burn-in, operational SLO history, market certification, custody or clearing access, or human governance approval. Those remain separate readiness evidence for the same immutable baseline.
