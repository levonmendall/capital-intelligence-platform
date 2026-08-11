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


def test_render_declares_current_repository_provider_secret_aliases() -> None:
    # These are the provider-native secret families currently used in the repository.
    # Render must expose them as external slots so runtime normalization can see them.
    required = {
        "ALPHA_VANTAGE_API_KEY",
        "APCA_API_KEY_ID",
        "APCA_API_SECRET_KEY",
        "BEA_API_KEY",
        "DATABENTO_API_KEY",
        "EIA_API_KEY",
        "EODHD_API_KEY",
        "FINRA_API_KEY",
        "FRED_API_KEY",
        "MASSIVE_API_KEY",
        "NASA_API_KEY",
        "OPEN_FIGI_API_KEY",
        "TRADIER_API_KEY",
        "TWELVE_API_KEY",
        "USDA_NASS_API_KEY",
        "US_CENSUS_API_KEY",
    }
    missing = sorted(required - _render_keys())
    assert missing == [], f"Render is missing repository provider secret aliases: {missing}"


def test_render_does_not_embed_provider_secret_values() -> None:
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    protected = _bundle_external_inputs() | {
        "FINRA_CLIENT_ID",
        "FINRA_CLIENT_SECRET",
        "FINRA_API_KEY",
        "TRADIER_API_KEY",
        "NASA_API_KEY",
        "US_CENSUS_API_KEY",
    }
    for key in protected:
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
