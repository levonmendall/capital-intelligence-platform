"""Publish the CIO audit with exact stage-isolated prequalification progress."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence

from operations.stage_isolated_prequalification_projection import (
    project_stage_isolated_prequalification,
)
from publish_cio_diagnostic_audit import audit_output_path, publish_cio_diagnostic_audit


def publish_stage_isolated_cio_diagnostic_audit() -> dict[str, object]:
    values = os.environ
    payload = publish_cio_diagnostic_audit(values=values)
    published = project_stage_isolated_prequalification(payload, values=values)
    path = audit_output_path(values)
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
        raise ValueError("publish_cio_diagnostic_audit_stage_isolated.py accepts no arguments")
    try:
        payload = publish_stage_isolated_cio_diagnostic_audit()
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "event": "stage_isolated_cio_diagnostic_audit_publication_failed",
                    "error_type": type(error).__name__,
                    "credential_safe": True,
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 2
    progress = payload.get("stage_isolated_evidence_progress")
    print(
        json.dumps(
            {
                "event": "stage_isolated_cio_diagnostic_audit_published",
                "active_release": payload.get("active_release"),
                "state": payload.get("state"),
                "stage": payload.get("stage"),
                "stage_isolated_progress": progress,
                "credential_safe": True,
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
