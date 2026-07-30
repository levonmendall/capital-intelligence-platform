"""Read-only Streamlit surface for research-only Canonical CIO replay evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import streamlit as st


MANIFEST_NAME = "latest-canonical-replay.json"
SUPPORTED_SCHEMA_VERSIONS = frozenset(
    {
        "canonical-historical-replay.v1",
        "canonical-historical-replay.v2",
        "canonical-historical-replay.v3",
        "canonical-historical-replay.v4",
    }
)


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
    if payload.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        return None
    return payload


def _all_observations(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    cutoffs = payload.get("decisions")
    if not isinstance(cutoffs, list):
        return []
    return [
        observation
        for cutoff in cutoffs
        if isinstance(cutoff, Mapping)
        for observation in (
            cutoff.get("decisions")
            if isinstance(cutoff.get("decisions"), list)
            else []
        )
        if isinstance(observation, Mapping)
    ]


def canonical_replay_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    decisions = payload.get("decisions")
    rows = decisions if isinstance(decisions, list) else []
    observations = _all_observations(payload)
    invoked = int(payload.get("canonical_cio_invoked_count", 0) or 0)
    blocked = int(payload.get("blocked_cutoff_count", 0) or 0)
    total = int(payload.get("decision_cutoff_count", len(rows)) or 0)
    state = "Available" if invoked > 0 else "Blocked"
    if invoked > 0 and blocked > 0:
        state = "Partially available"
    qualification_count = int(
        payload.get(
            "qualification_observation_count",
            sum(
                item.get("decision_stage") == "pre_cio_qualification"
                for item in observations
            ),
        )
        or 0
    )
    cio_count = int(
        payload.get(
            "cio_decision_observation_count",
            sum(
                item.get("canonical_cio_decision") is True
                or item.get("decision_stage") == "cio_synthesis"
                for item in observations
            ),
        )
        or 0
    )
    learning_count = int(
        payload.get("learning_observation_count", len(observations)) or 0
    )
    governance_only = int(
        payload.get(
            "governance_only_observation_count",
            sum(item.get("calibration_eligible") is False for item in observations),
        )
        or 0
    )
    calibration_eligible = int(
        payload.get(
            "calibration_eligible_observation_count",
            max(0, learning_count - governance_only),
        )
        or 0
    )
    realized_count = int(
        payload.get(
            "realized_outcome_count",
            sum(
                isinstance(
                    item.get("realized_decision_value_at_horizon"),
                    (int, float),
                )
                for item in observations
            ),
        )
        or 0
    )
    avoided_count = int(
        payload.get(
            "avoided_loss_count",
            sum(item.get("realized_outcome") == "avoided_loss" for item in observations),
        )
        or 0
    )
    missed_count = int(
        payload.get(
            "missed_opportunity_count",
            sum(
                item.get("realized_outcome") == "missed_opportunity"
                for item in observations
            ),
        )
        or 0
    )
    return {
        "state": state,
        "schema_version": payload.get("schema_version"),
        "runtime_version": payload.get("runtime_version"),
        "generated_at": payload.get("generated_at"),
        "start_date": payload.get("start_date"),
        "end_date": payload.get("end_date"),
        "cadence": payload.get("cadence"),
        "strict_replay": payload.get("strict_replay") is True,
        "invoked_cutoffs": invoked,
        "blocked_cutoffs": blocked,
        "total_cutoffs": total,
        "learning_observations": learning_count,
        "cio_decision_observations": cio_count,
        "qualification_observations": qualification_count,
        "calibration_eligible_observations": calibration_eligible,
        "governance_only_observations": governance_only,
        "realized_outcomes": realized_count,
        "outcome_alignment": payload.get("outcome_alignment") or "legacy_next_cutoff",
        "avoided_losses": avoided_count,
        "missed_opportunities": missed_count,
        "research_only": payload.get("research_only") is True,
        "execution_authorized": payload.get("execution_authorized") is True,
        "paper_execution_authorized": payload.get("paper_execution_authorized") is True,
        "real_money_authorized": payload.get("real_money_authorized") is True,
        "policy_promotion_authorized": payload.get("policy_promotion_authorized") is True,
        "performance_claims_authorized": payload.get("performance_claims_authorized") is True,
    }


def canonical_replay_cutoff_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in decisions:
        if not isinstance(item, Mapping):
            continue
        construction = item.get("construction")
        construction_payload = construction if isinstance(construction, Mapping) else {}
        raw_observations = item.get("decisions")
        observations = raw_observations if isinstance(raw_observations, list) else []
        action_counts: dict[str, int] = {}
        avoided = missed = governance_only = 0
        for observation in observations:
            if not isinstance(observation, Mapping):
                continue
            action = str(observation.get("action") or "unavailable")
            action_counts[action] = action_counts.get(action, 0) + 1
            avoided += observation.get("realized_outcome") == "avoided_loss"
            missed += observation.get("realized_outcome") == "missed_opportunity"
            governance_only += observation.get("calibration_eligible") is False
        actions = ", ".join(
            f"{name.replace('_', ' ').title()} × {count}"
            for name, count in sorted(action_counts.items())
        )
        qualification_count = int(
            item.get(
                "qualification_rejection_count",
                sum(
                    isinstance(value, Mapping)
                    and value.get("decision_stage") == "pre_cio_qualification"
                    for value in observations
                ),
            )
            or 0
        )
        learning_count = int(
            item.get("learning_observation_count", len(observations)) or 0
        )
        rows.append(
            {
                "Cutoff": item.get("cutoff"),
                "State": str(item.get("state", "unavailable")).replace(
                    "_", " "
                ).title(),
                "Canonical cycle": (
                    "Invoked" if item.get("canonical_cio_invoked") is True else "Blocked"
                ),
                "Candidates": int(item.get("candidate_count", 0) or 0),
                "CIO decisions": int(item.get("decision_count", 0) or 0),
                "Pre-CIO outcomes": qualification_count,
                "Learning observations": learning_count,
                "Governance only": governance_only,
                "Actions / outcomes": actions or "None",
                "Avoided losses": avoided,
                "Missed opportunities": missed,
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
            "The historical worker will create the first supported manifest after sufficient "
            "point-in-time records are available."
        )
        return

    summary = canonical_replay_summary(payload)
    columns = st.columns(4)
    columns[0].metric("Replay state", summary["state"])
    columns[1].metric("Canonical cutoffs", summary["invoked_cutoffs"])
    columns[2].metric("Blocked cutoffs", summary["blocked_cutoffs"])
    columns[3].metric(
        "Evidence mode", "Strict" if summary["strict_replay"] else "Research bridge"
    )

    learning_columns = st.columns(4)
    learning_columns[0].metric(
        "Learning observations", summary["learning_observations"]
    )
    learning_columns[1].metric("Horizon outcomes", summary["realized_outcomes"])
    learning_columns[2].metric("Avoided losses", summary["avoided_losses"])
    learning_columns[3].metric(
        "Missed opportunities", summary["missed_opportunities"]
    )

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
        + f" · {summary.get('schema_version') or 'unknown schema'}"
        + (
            f" · {summary['runtime_version']}"
            if summary.get("runtime_version")
            else ""
        )
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
        "This is governed research evidence, not an execution surface or verified "
        "performance claim. CIO decisions and pre-CIO qualification outcomes are "
        "reported separately. Only calibration-eligible observations with outcomes "
        "aligned to the original decision horizon may affect live confidence or size."
    )
    st.caption(
        f"CIO decision observations: {summary['cio_decision_observations']} · "
        f"Pre-CIO qualification observations: {summary['qualification_observations']} · "
        f"Calibration eligible: {summary['calibration_eligible_observations']} · "
        f"Governance only: {summary['governance_only_observations']} · "
        f"Outcome alignment: {str(summary['outcome_alignment']).replace('_', ' ')}"
    )

    rows = canonical_replay_cutoff_rows(payload)
    if not rows:
        st.warning("The replay manifest contains no historical cutoffs.")
        return
    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
    )

    blocked = [row for row in rows if row["Canonical cycle"] == "Blocked"]
    if blocked:
        with st.expander("Blocked cutoff details", expanded=False):
            for row in blocked:
                st.write(
                    f"- {row['Cutoff']}: "
                    f"{row['Blocked reason'] or 'required point-in-time evidence was unavailable'}"
                )


__all__ = [
    "MANIFEST_NAME",
    "SUPPORTED_SCHEMA_VERSIONS",
    "canonical_replay_cutoff_rows",
    "canonical_replay_manifest_path",
    "canonical_replay_summary",
    "load_canonical_replay_manifest",
    "render_canonical_historical_replay",
]
