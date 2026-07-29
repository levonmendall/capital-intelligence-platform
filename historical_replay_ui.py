"""Read-only Streamlit surface for research-only Canonical CIO replay evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import streamlit as st


MANIFEST_NAME = "latest-canonical-replay.json"


def canonical_replay_manifest_path(
    environ: Mapping[str, str] | None = None,
) -> Path:
    values = os.environ if environ is None else environ
    data_root = Path(
        values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database")
    ).expanduser()
    historical_root = Path(
        values.get(
            "CAPITAL_INTELLIGENCE_HISTORICAL_DATA_DIR",
            str(data_root / "historical_replay"),
        )
    ).expanduser()
    return historical_root / "manifests" / MANIFEST_NAME


def load_canonical_replay_manifest(
    path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    resolved = Path(path) if path is not None else canonical_replay_manifest_path(environ)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != "canonical-historical-replay.v1":
        return None
    return payload


def canonical_replay_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    decisions = payload.get("decisions")
    rows = decisions if isinstance(decisions, list) else []
    invoked = int(payload.get("canonical_cio_invoked_count", 0) or 0)
    blocked = int(payload.get("blocked_cutoff_count", 0) or 0)
    total = int(payload.get("decision_cutoff_count", len(rows)) or 0)
    state = "Available" if invoked > 0 else "Blocked"
    if invoked > 0 and blocked > 0:
        state = "Partially available"
    return {
        "state": state,
        "generated_at": payload.get("generated_at"),
        "start_date": payload.get("start_date"),
        "end_date": payload.get("end_date"),
        "cadence": payload.get("cadence"),
        "strict_replay": payload.get("strict_replay") is True,
        "invoked_cutoffs": invoked,
        "blocked_cutoffs": blocked,
        "total_cutoffs": total,
        "research_only": payload.get("research_only") is True,
        "execution_authorized": payload.get("execution_authorized") is True,
        "paper_execution_authorized": payload.get("paper_execution_authorized") is True,
        "real_money_authorized": payload.get("real_money_authorized") is True,
        "policy_promotion_authorized": payload.get("policy_promotion_authorized") is True,
        "performance_claims_authorized": payload.get("performance_claims_authorized") is True,
    }


def _cutoff_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in decisions:
        if not isinstance(item, Mapping):
            continue
        construction = item.get("construction")
        construction_payload = construction if isinstance(construction, Mapping) else {}
        decision_items = item.get("decisions")
        canonical_decisions = decision_items if isinstance(decision_items, list) else []
        action_counts: dict[str, int] = {}
        for decision in canonical_decisions:
            if not isinstance(decision, Mapping):
                continue
            action = str(decision.get("action") or "unavailable")
            action_counts[action] = action_counts.get(action, 0) + 1
        actions = ", ".join(
            f"{name.replace('_', ' ').title()} × {count}"
            for name, count in sorted(action_counts.items())
        )
        rows.append(
            {
                "Cutoff": item.get("cutoff"),
                "State": str(item.get("state", "unavailable")).replace(
                    "_", " "
                ).title(),
                "Canonical CIO": (
                    "Invoked" if item.get("canonical_cio_invoked") is True else "Blocked"
                ),
                "Candidates": int(item.get("candidate_count", 0) or 0),
                "Decisions": int(item.get("decision_count", 0) or 0),
                "Actions": actions or "None",
                "Construction": str(
                    construction_payload.get("status") or "none"
                ).replace("_", " ").title(),
                "Blocked reason": item.get("error") or "",
            }
        )
    return rows


def render_canonical_historical_replay() -> None:
    """Render sanitized canonical replay status inside the History surface."""

    st.markdown("#### Historical learning")
    payload = load_canonical_replay_manifest()
    if payload is None:
        st.info(
            "Canonical CIO historical replay has not completed on this operating host yet. "
            "The historical worker will create the first manifest after sufficient "
            "point-in-time records are available."
        )
        return

    summary = canonical_replay_summary(payload)
    columns = st.columns(4)
    columns[0].metric("Replay state", summary["state"])
    columns[1].metric("Canonical cutoffs", summary["invoked_cutoffs"])
    columns[2].metric("Blocked cutoffs", summary["blocked_cutoffs"])
    columns[3].metric("Evidence mode", "Strict" if summary["strict_replay"] else "Research bridge")

    period = " · ".join(
        str(value)
        for value in (
            summary.get("start_date"),
            summary.get("end_date"),
            summary.get("cadence"),
        )
        if value
    )
    st.caption(
        f"Generated {summary.get('generated_at') or 'at an unavailable time'}"
        + (f" · {period}" if period else "")
    )

    unsafe_flags = {
        "execution": summary["execution_authorized"],
        "paper execution": summary["paper_execution_authorized"],
        "real money": summary["real_money_authorized"],
        "policy promotion": summary["policy_promotion_authorized"],
        "performance claims": summary["performance_claims_authorized"],
    }
    enabled = [name for name, value in unsafe_flags.items() if value]
    if enabled or not summary["research_only"]:
        st.error(
            "Historical replay safety state is invalid. Review before using the report: "
            + ", ".join(enabled or ["research_only is false"])
        )
        return

    st.info(
        "This is research evidence from the production CIO decision process, not an "
        "execution surface or verified performance claim. Historical target weights "
        "never change the active paper portfolio."
    )

    rows = _cutoff_rows(payload)
    if not rows:
        st.warning("The replay manifest contains no historical cutoffs.")
        return
    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
    )

    blocked = [row for row in rows if row["Canonical CIO"] == "Blocked"]
    if blocked:
        with st.expander("Blocked cutoff details", expanded=False):
            for row in blocked:
                st.write(
                    f"- {row['Cutoff']}: "
                    f"{row['Blocked reason'] or 'required point-in-time evidence was unavailable'}"
                )


__all__ = [
    "MANIFEST_NAME",
    "canonical_replay_manifest_path",
    "canonical_replay_summary",
    "load_canonical_replay_manifest",
    "render_canonical_historical_replay",
]
