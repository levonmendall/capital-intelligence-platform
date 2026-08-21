from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import api.cio_diagnostic as cio_diagnostic


def test_public_static_telemetry_audit_is_importable():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/capture_render_production_telemetry.py",
            "--help",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--expected-release" in result.stdout
    assert "ModuleNotFoundError" not in result.stderr


def test_live_telemetry_route_is_registered_as_get():
    routes = {
        getattr(route, "path", ""): route for route in cio_diagnostic.router.routes
    }
    route = routes["/v1/operations/cio-diagnostic/telemetry"]
    assert "GET" in route.methods


def test_render_telemetry_workflow_uses_public_static_audit():
    workflow = Path(".github/workflows/render-production-telemetry.yml").read_text(
        encoding="utf-8"
    )
    assert "onrender.com/app/static/cio-diagnostic.json\n" in workflow
    assert "python scripts/capture_render_production_telemetry_resilient.py" in workflow
    assert "python scripts/enrich_stage_isolated_prequalification_telemetry.py" in workflow
    assert "capture_render_production_telemetry_canonical.py" not in workflow
    assert "onrender.com/v1/operations/cio-diagnostic\n" not in workflow