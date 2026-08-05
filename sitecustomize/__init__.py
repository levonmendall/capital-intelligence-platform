"""Process-local deployment metadata and headline-credential safety.

Python imports ``sitecustomize`` during interpreter startup when this repository is on
``sys.path``. Two independent, narrow protections live here:

* map Render's deployed commit into the canonical CIO code-version variable for
  append-only decision lineage; and
* for the public headline collector only, map the canonical Render EODHD token name
  to the legacy source alias and redact provider secrets from JSON output.

These controls do not alter investment evidence, candidate selection, ranking, CIO
authority, position sizing, construction, paper execution, or real-money permissions.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Any


_HEADLINE_COLLECTOR = "run_public_headline_collector.py"
_FORCE_ENVIRONMENT = "CAPITAL_INTELLIGENCE_FORCE_HEADLINE_SECRET_GUARD"
_CREDENTIAL_ENVIRONMENT_NAMES = (
    "FINNHUB_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
    "EODHD_API_KEY",
    "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN",
    "MARKETAUX_API_TOKEN",
)
_RENDER_RELEASE_ENVIRONMENT = "RENDER_GIT_COMMIT"
_CODE_VERSION_ENVIRONMENT = "CAPITAL_INTELLIGENCE_CODE_VERSION"
_REDACTED = "[REDACTED]"


def configure_code_version(
    environment: MutableMapping[str, str] | None = None,
) -> str | None:
    """Populate canonical code-version lineage from Render deployment metadata.

    An explicitly configured canonical value always wins. Other environment-specific
    commit variables are deliberately not promoted at interpreter startup because test
    and build runners can change them between subprocesses. The function returns the
    resolved value and leaves the environment unchanged when Render metadata is absent.
    """

    values = os.environ if environment is None else environment
    existing = str(values.get(_CODE_VERSION_ENVIRONMENT, "")).strip()
    if existing:
        return existing
    candidate = str(values.get(_RENDER_RELEASE_ENVIRONMENT, "")).strip()
    if candidate:
        values[_CODE_VERSION_ENVIRONMENT] = candidate
        return candidate
    return None


def _enabled() -> bool:
    forced = os.getenv(_FORCE_ENVIRONMENT, "").strip().lower()
    return Path(sys.argv[0]).name == _HEADLINE_COLLECTOR or forced in {
        "1",
        "true",
        "yes",
        "on",
    }


def _credential_values() -> tuple[str, ...]:
    values = {
        value
        for name in _CREDENTIAL_ENVIRONMENT_NAMES
        if len(value := os.getenv(name, "").strip()) >= 4
    }
    return tuple(sorted(values, key=len, reverse=True))


def _redact_text(value: str) -> str:
    text = value
    for secret in _credential_values():
        text = text.replace(secret, _REDACTED)
    text = re.sub(
        r"(?i)(\b(?:api[_ -]?key|apikey|api_token|access_token|token)\b"
        r"(?:\s+as)?\s*[:=]?\s+)([A-Za-z0-9._~+/=-]{8,})",
        rf"\1{_REDACTED}",
        text,
    )
    text = re.sub(
        r"(?i)([?&](?:api[_-]?key|apikey|api_token|access_token|token)=)"
        r"([^&\s]+)",
        rf"\1{_REDACTED}",
        text,
    )
    text = re.sub(
        r"(?i)(\bBearer\s+)([A-Za-z0-9._~+/=-]{8,})",
        rf"\1{_REDACTED}",
        text,
    )
    return text


def _sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, Mapping):
        return {
            _sanitize(key) if isinstance(key, str) else key: _sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(_sanitize(item) for item in value)
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value


def _activate() -> None:
    canonical_eodhd = os.getenv(
        "CAPITAL_INTELLIGENCE_EODHD_API_TOKEN",
        "",
    ).strip()
    if canonical_eodhd and not os.getenv("EODHD_API_KEY", "").strip():
        os.environ["EODHD_API_KEY"] = canonical_eodhd

    original_dumps = json.dumps
    original_dump = json.dump

    def safe_dumps(value: Any, *args: Any, **kwargs: Any) -> str:
        return original_dumps(_sanitize(value), *args, **kwargs)

    def safe_dump(value: Any, fp: Any, *args: Any, **kwargs: Any) -> None:
        original_dump(_sanitize(value), fp, *args, **kwargs)

    json.dumps = safe_dumps
    json.dump = safe_dump


configure_code_version()
if _enabled():
    _activate()


__all__ = ["configure_code_version"]
