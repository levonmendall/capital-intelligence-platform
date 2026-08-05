"""Publish the credential-safe CIO diagnostic audit through Streamlit static files."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from api.config import ApiSettings
from api.routes.cio_diagnostic import build_cio_diagnostic_audit


def audit_output_path(values: Mapping[str, str] | None = None) -> Path:
    resolved = os.environ if values is None else values
    configured = resolved.get(
        "CAPITAL_INTELLIGENCE_CIO_DIAGNOSTIC_PUBLIC_AUDIT_PATH",
        "",
    ).strip()
    return Path(configured or "static/cio-diagnostic.json").expanduser()


def publish_cio_diagnostic_audit(
    *,
    values: Mapping[str, str] | None = None,
) -> dict[str, object]:
    resolved = os.environ if values is None else values
    settings = ApiSettings.from_env(resolved)
    payload = build_cio_diagnostic_audit(settings=settings, values=resolved)
    published = {
        **payload,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": "public-cio-diagnostic-audit.v1",
        "credential_safe": True,
    }
    path = audit_output_path(resolved)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(published, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return published


def main(argv: Sequence[str] | None = None) -> int:
    if argv not in (None, (), []):
        raise ValueError("publish_cio_diagnostic_audit.py accepts no arguments")
    try:
        payload = publish_cio_diagnostic_audit()
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "event": "cio_diagnostic_audit_publication_failed",
                    "error_type": type(error).__name__,
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 2
    print(
        json.dumps(
            {
                "event": "cio_diagnostic_audit_published",
                "active_release": payload.get("active_release"),
                "state": payload.get("state"),
                "all_market_evaluation_complete": payload.get(
                    "all_market_evaluation_complete"
                ),
                "paper_only": True,
                "real_money_authorized": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
