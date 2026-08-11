from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _render_keys() -> set[str]:
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    return set(re.findall(r"^\s*- key:\s*([A-Z0-9_]+)\s*$", text, flags=re.MULTILINE))


def _bundle_external_inputs() -> set[str]:
    payload = json.loads(
        (ROOT / "config" / "all_market_provider_bundle.json").read_text(
            encoding="utf-8"
        )
    )
    names: set[str] = set()
    for member in payload["members"]:
        for field in (
            "credential_environment_variables",
            "binding_environment_variables",
            "contract_reference_environment_variables",
            "license_approval_environment_variables",
            "certification_environment_variables",
        ):
            names.update(str(item) for item in member.get(field, ()))
    return names


def test_render_declares_every_all_market_provider_external_input() -> None:
    missing = sorted(_bundle_external_inputs() - _render_keys())
    assert missing == [], f"Render is missing provider activation inputs: {missing}"


def test_render_declares_direct_redundancy_provider_credentials() -> None:
    required = {
        "CAPITAL_INTELLIGENCE_MASSIVE_OPTIONS_API_KEY",
        "FINRA_CLIENT_ID",
        "FINRA_CLIENT_SECRET",
    }
    missing = sorted(required - _render_keys())
    assert missing == [], f"Render is missing direct provider credentials: {missing}"


def test_render_does_not_embed_provider_secret_values() -> None:
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    for key in _bundle_external_inputs() | {"FINRA_CLIENT_ID", "FINRA_CLIENT_SECRET"}:
        match = re.search(
            rf"^\s*- key:\s*{re.escape(key)}\s*$\n(?P<body>(?:\s{{8,}}.*\n)*)",
            text,
            flags=re.MULTILINE,
        )
        assert match is not None
        body = match.group("body")
        # External provider activation inputs may be set as sync:false or to a
        # repository-local non-secret binding path. They must never embed a secret.
        if "value:" in body:
            assert "config/" in body or "/app/" in body
