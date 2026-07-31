# Current State Audit

Audit baseline: 2026-07-31 UTC. GitHub `main` is provisional canonical; the uploaded ZIP is comparison evidence only.

## Source and deployment identity

| Item | Evidence | Status |
|---|---|---|
| Repository | `levonmendall/capital-intelligence-platform-` | Provisional canonical |
| Initial audited `main` | `9435b4c4edd882734e47197f84eb4588412cd3af` | Exact SHA compared byte-for-byte with the ZIP |
| Current `main` | `4742dec18113d03334d28f8d734b701aedefd7a5` | PR #278 merged after the initial comparison; this is the PR-stack rebase base |
| Render declaration | `render.yaml`: branch `main`, Docker runtime, `dockerCommand: python run_render_service.py`, `autoDeployTrigger: checksPass` | Exact configured source and command |
| Container source | Docker build context `.`, `Dockerfile` runtime stage | Exact configured source |
| Render public entrypoint | `run_render_service.py` supervisor; public child is `python -m streamlit run render_app.py ...` | Exact configured entrypoint |
| Actual deployed SHA | Intended to be exposed through `RENDER_GIT_COMMIT` / `CAPITAL_INTELLIGENCE_RELEASE` | **Unverified**: the live host was inaccessible from this audit environment and GitHub exposes no Render deployment status for the commit |

The updated ZIP is byte-identical to the initial audited SHA `9435b4c4...`.
Current main then advanced through PR #278 with seven provider-validation path
changes (five modified, two added). The ZIP is therefore now a historical
comparison artifact, not a copy of current main. No production claim or merge
may treat either repository SHA as the deployed SHA until the live service
reports it or Render deployment metadata confirms it.

## Executive conclusion

The investment domain is materially more mature than the uploaded ZIP and already encodes the central governing constraints: one `COMPOUNDING` portfolio, $250,000 starting capital, CIO-only action selection, construction after decision, paper-only execution, append-only journals, point-in-time contracts, and fail-closed provider gates. The immediate risk is operational composition, not missing investment strategies.

The production surface is not yet safe for unauthenticated public use. Authentication-disabled mode creates an administrator principal. Render also launches a headless operator while Streamlit can run a second paper-execution worker. The UI runtime relies on nested source reads, source transformations, monkey patches, and `exec`. Health coverage is limited to Streamlit. Deployment documentation and actual commands disagree. These issues must be corrected in the ordered PR sequence before strategy expansion.

## Complete active path

1. Public event and economic/market acquisition enters through `providers/public_live_information.py`, `public_live_collection_runtime.py`, configured dataset providers, FRED/SEC adapters, and provider activation/readiness contracts.
2. Daily interpretation is assembled by `application/daily_intelligence.py`, the public-information record set, environment evidence, and reporting/UI adapters. Current records carry fixed relevance/materiality metadata but do not yet provide the requested benchmarked semantic clustering, novelty, corroboration, exposure mapping, and market confirmation.
3. Eligible-universe and complete-universe controls live in `application/eligible_universe.py`, `screening/orchestration.py`, security-master modules, governance manifests, and `operations/comprehensive_market_discovery.py`. Partial universe coverage is rejected by the production CIO executor.
4. `committee/specialists.py` creates exactly six governed analyses: macro/economic, market, cross-asset forecast/scenario, fundamental/valuation, portfolio/risk/implementation, and evidence/governance.
5. `cio/service.py` is the sole investment-action synthesizer. Specialist analyses may support, oppose, abstain, veto, or constrain; they do not authorize a portfolio change.
6. `application/cio_cycle.py` persists candidate, specialist, decision, construction, evaluation, thesis, and briefing lineage. `portfolio/construction_engine.py` converts approved CIO decisions into feasible non-executing intents and sizes the portfolio after costs and constraints.
7. Internal paper implementation is performed through governed execution orchestration and canonical simulated fills. Alpaca paper code is a separate transport/round-trip validation surface and must not publish canonical portfolio state.
8. Execution reconciles fills, cash, positions, and expected construction before state publication. Integrity-specialist checks are non-voting and cannot create authority.
9. `portfolio/state.py` and `canonical_portfolio.db` are the canonical portfolio state authority; CIO/journal stores are append-only decision lineage, not competing portfolio state.
10. Evaluation and historical replay use point-in-time boundaries and append-only evidence, but complete provider-era and survivorship certification is unfinished.
11. FastAPI reads repository projections. Streamlit presents Today, Environment, Portfolio, and History. Presentation cannot authorize CIO decisions, construction, or real-money execution.

## Confirmed findings

| Finding | Evidence | Required PR |
|---|---|---|
| Auth-off administrator | `AuthenticationService.principal_for_access_token()` returns `AuthenticatedPrincipal.testing_system()` with `ADMINISTRATOR` | PR1 |
| Two paper runtime authorities | Render starts `run_autonomous_paper_operator.py --loop`; `app.py` injects `render_background_paper_execution_worker()` | PR2 |
| Runtime source rewriting | `render_app.py` execs `secure_app.py`; `secure_app.py` rewrites/execs `app.py`; `app.py` rewrites/execs `app_impl.py` and monkey-patches UI | PR3 |
| Incomplete production health | Render checks only `/_stcore/health`; supervisor has five children | PR4 |
| Topology drift | Render, Dockerfile, Compose, README, and local commands use different process sets and UI entrypoints | PR5 |
| Filesystem-time ordering | Archive/report/backup selectors use `st_mtime` in multiple active modules | PR6 |
| Operational sprawl | 87 root `run_*.py` scripts; 20+ Python modules exceed 1,000 lines; source-text assertions are present | PR5/PR7/PR8/PR9 |
| Event quality gap | Collection exists; requested semantic clustering/novelty/corroboration/materiality/confirmation/exposure benchmark is not a certified active gate | PR10 |
| Market-scope ambiguity | Broad monitored/provider manifests coexist with a 15-instrument bounded pilot and blocked all-market providers | PR11 |
| Execution boundary needs explicit certification | Internal simulated fills and Alpaca paper transport coexist; live money remains prohibited | PR2/PR9/PR12 |
| Historical certification incomplete | ALFRED vintages, older SEC archives, reference data, actions, delistings, membership, liquidity and availability-era coverage remain gaps | PR11 |
| Experiment not formally frozen | Launch policy exists, but it is not a versioned multi-week hypothesis/measurement/promotion protocol | PR12 |

## Authority impact of this audit

No CIO, construction, governance, execution, or real-money authority is changed by the audit documents. No strategy engine is added.

## Validation record

- PR1-focused authorization, API, Streamlit, paper-control, and Render tests: **37 passed**.
- Python compilation and `requirements.lock` integrity: passed.
- The original repository-wide ordering failure was corrected in ordered PR6;
  the complete local stack subsequently passed **1,738 tests** with two
  opt-in browser skips on a host without Chromium.
- GitHub's exact final-tree gate on current-main compatibility passed the real
  Streamlit desktop/iPhone browser suite, deterministic release validation,
  CodeQL, dependency/container security review, pilot readiness, historical
  validation, and operational completion.
- Merge remains blocked until Render independently confirms the exact deployed
  Git SHA and production entrypoint.
