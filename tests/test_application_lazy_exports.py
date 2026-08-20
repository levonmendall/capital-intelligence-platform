from __future__ import annotations

import subprocess
import sys
import textwrap


def _run_isolated(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_application_package_root_does_not_eagerly_load_unrelated_runtime_graphs() -> None:
    result = _run_isolated(
        """
        import sys
        import application

        forbidden = {
            "application.daily_intelligence",
            "application.environment_evidence",
            "application.multi_asset_evidence",
            "application.production_context_executor",
            "application.forecast_support",
        }
        loaded = forbidden.intersection(sys.modules)
        assert not loaded, sorted(loaded)
        """
    )

    assert result.returncode == 0, result.stderr


def test_lazy_root_exports_preserve_public_imports_without_loading_daily_stack() -> None:
    result = _run_isolated(
        """
        import sys

        from application import build_production_context_provider
        assert callable(build_production_context_provider)
        assert "application.forecast_support" in sys.modules
        assert "application.daily_intelligence" not in sys.modules

        from application import DailyIntelligenceStatus
        assert DailyIntelligenceStatus.CURRENT.value == "current"
        assert "application.daily_intelligence" in sys.modules
        """
    )

    assert result.returncode == 0, result.stderr
