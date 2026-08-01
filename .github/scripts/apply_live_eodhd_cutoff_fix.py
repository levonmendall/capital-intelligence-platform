from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match in {path}, found {count}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


provider_path = ROOT / "providers/eodhd.py"
replace_once(
    provider_path,
    "from dataclasses import dataclass\n",
    "from dataclasses import dataclass, replace\n",
)
replace_once(
    provider_path,
    'EODHD_SOURCE_VERSION = "eodhd-rest.v1"\n',
    'EODHD_SOURCE_VERSION = "eodhd-rest.v1"\n'
    '_LIVE_DATASET_QUERY_GRACE = timedelta(minutes=5)\n',
)
replace_once(
    provider_path,
    "        retrieved_at = self._now()\n"
    "        dataset_type = query.dataset_type\n",
    "        retrieved_at = self._now()\n"
    "        snapshot_query = query\n"
    "        live_retrieval_limitations: tuple[str, ...] = ()\n"
    "        if retrieved_at > query.as_of:\n"
    "            retrieval_delay = retrieved_at - query.as_of\n"
    "            if retrieval_delay <= _LIVE_DATASET_QUERY_GRACE:\n"
    "                snapshot_query = replace(query, as_of=retrieved_at)\n"
    "                live_retrieval_limitations = (\n"
    "                    \"live retrieval availability is recorded at collection time; \"\n"
    "                    f\"the requested cutoff was {query.as_of.isoformat()}\",\n"
    "                )\n"
    "        dataset_type = query.dataset_type\n",
)
replace_once(
    provider_path,
    "        return ProviderDatasetSnapshot(\n"
    "            query=query,\n",
    "        return ProviderDatasetSnapshot(\n"
    "            query=snapshot_query,\n",
)
replace_once(
    provider_path,
    "            limitations=limitations,\n"
    "        )\n\n"
    "    def _fetch_bars(\n",
    "            limitations=tuple((*live_retrieval_limitations, *limitations)),\n"
    "        )\n\n"
    "    def _fetch_bars(\n",
)


test_path = ROOT / "tests/test_eodhd_provider.py"
replace_once(
    test_path,
    "from datetime import datetime, timezone\n",
    "from datetime import datetime, timedelta, timezone\n",
)
replace_once(
    test_path,
    "def provider_for(payloads, *, policy=None, sleepers=None) -> EODHDProvider:\n",
    "def provider_for(\n"
    "    payloads,\n"
    "    *,\n"
    "    policy=None,\n"
    "    sleepers=None,\n"
    "    clock=None,\n"
    ") -> EODHDProvider:\n",
)
replace_once(
    test_path,
    "        clock=lambda: NOW,\n"
    "        http_get=http_get,\n",
    "        clock=clock or (lambda: NOW),\n"
    "        http_get=http_get,\n",
)
anchor = (
    "def test_symbol_directory_remains_non_authoritative_history() -> None:\n"
)
new_tests = '''def test_live_dataset_snapshot_records_actual_retrieval_availability() -> None:\n    retrieved_at = NOW + timedelta(seconds=90)\n    provider = provider_for(\n        [FakeResponse({"General": {"Code": "AAPL", "Exchange": "US"}})],\n        clock=lambda: retrieved_at,\n    )\n\n    snapshot = provider.fetch_dataset(\n        ProviderDatasetQuery(\n            dataset_type=ProviderDatasetType.FUNDAMENTALS,\n            provider_symbol="AAPL.US",\n            as_of=NOW,\n        )\n    )\n\n    assert snapshot.query.as_of == retrieved_at\n    assert snapshot.available_at == retrieved_at\n    assert any("requested cutoff" in item for item in snapshot.limitations)\n\n\ndef test_historical_dataset_query_still_fails_closed_after_live_grace() -> None:\n    provider = provider_for(\n        [FakeResponse({"General": {"Code": "AAPL", "Exchange": "US"}})],\n        clock=lambda: NOW,\n    )\n\n    with pytest.raises(ValueError, match="snapshot was not available at query as_of"):\n        provider.fetch_dataset(\n            ProviderDatasetQuery(\n                dataset_type=ProviderDatasetType.FUNDAMENTALS,\n                provider_symbol="AAPL.US",\n                as_of=NOW - timedelta(minutes=6),\n            )\n        )\n\n\n'''
replace_once(test_path, anchor, new_tests + anchor)


canonical_validate = '''name: Validate Capital Intelligence Platform\n\non:\n  push:\n    branches:\n      - main\n\n  pull_request:\n    branches:\n      - main\n\n  workflow_dispatch:\n\npermissions:\n  contents: read\n\njobs:\n  validate:\n    runs-on: ubuntu-latest\n    timeout-minutes: 45\n\n    env:\n      PYTHONPATH: ${{ github.workspace }}\n      CAPITAL_INTELLIGENCE_DAILY_STAGE_BINDINGS: ${{ github.workspace }}/deploy/canonical-daily-stage-bindings.validation.json\n\n    steps:\n      - name: Check out repository\n        uses: actions/checkout@f548e57e544e1ff5a4c46bf1e1b8685f8e4a348a # v7.0.1\n        with:\n          persist-credentials: false\n\n      - name: Set up Python\n        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7\n        with:\n          python-version: "3.11"\n          cache: pip\n\n      - name: Upgrade pip\n        run: python -m pip install --upgrade pip\n\n      - name: Install locked runtime dependencies\n        run: pip install --require-hashes -r requirements.lock\n\n      - name: Install development dependencies\n        run: pip install -r requirements-dev.txt\n\n      - name: Install browser-test dependencies\n        run: pip install -r requirements-browser.txt\n\n      - name: Verify dependency consistency\n        run: python -m pip check\n\n      - name: Verify runtime lock integrity\n        run: python scripts/verify_requirements_lock.py\n\n      - name: Install Chromium for real Streamlit browser tests\n        run: python -m playwright install --with-deps chromium\n\n      - name: Run desktop and iPhone Streamlit browser gate\n        env:\n          CAPITAL_INTELLIGENCE_BROWSER_TESTS: "1"\n        run: >-\n          pytest -q\n          tests/browser/test_streamlit_browser.py\n          tests/browser/test_sticky_primary_navigation.py\n\n      - name: Run deterministic release validation\n        run: timeout --signal=TERM 40m python run_release_validation.py --report reports/release-validation.json\n\n      - name: Publish release diagnostics\n        if: always()\n        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4\n        with:\n          name: release-validation-results\n          path: |\n            reports/release-validation.json\n            reports/golden-end-to-end-gate.json\n            reports/event-quality-benchmark.json\n            reports/pytest-results.xml\n            reports/browser/\n          if-no-files-found: ignore\n          retention-days: 14\n'''
(ROOT / ".github/workflows/validate.yml").write_text(
    canonical_validate,
    encoding="utf-8",
)

for relative in (
    ".github/workflows/trigger-weekend-cio-run.yml",
    ".github/workflows/trigger-weekend-cio-comment.yml",
    ".github/workflows/materialize-live-eodhd-cutoff-fix.yml",
    ".github/scripts/apply_live_eodhd_cutoff_fix.py",
):
    path = ROOT / relative
    if path.exists():
        path.unlink()
