"""CIO wrapper that records a fail-open, non-restrictive pre-decision Red Team pass.

The advisory report is computed after the six specialist packet exists and before the
canonical CIO synthesis runs.  It is intentionally *not* supplied as an input to the
authoritative action-selection code.  This guarantees that a severe challenge cannot
remove a viable candidate, introduce a veto, alter a threshold, or reduce a target.
After the CIO decides, the report is appended only to monitoring/explanation lineage.
"""

from __future__ import annotations

import json
import logging
from dataclasses import replace

from cio.committee_advisory import (
    CommitteeAdvisoryReport,
    build_committee_advisory_report,
)
from cio.decision_integrity import ChiefInvestmentOfficer as _IntegrityChiefInvestmentOfficer
from cio.models import CIODecision


_LOGGER = logging.getLogger("capital_intelligence.committee_advisory")
_ADVISORY_PREFIX = "committee-advisory.v1:"


def _safety_payload() -> dict[str, object]:
    return {
        "advisory_only": True,
        "can_authorize_action": False,
        "can_veto_action": False,
        "can_create_evidence_veto": False,
        "can_change_candidate_qualification": False,
        "can_remove_candidate": False,
        "can_change_position_size": False,
        "can_change_cash_hurdle": False,
        "can_change_policy_thresholds": False,
    }


def advisory_monitoring_record(
    report: CommitteeAdvisoryReport | None,
) -> str:
    """Serialize only advisory lineage; never encode an executable instruction."""

    payload = (
        {**_safety_payload(), "status": "unavailable"}
        if report is None
        else report.to_dict()
    )
    return _ADVISORY_PREFIX + json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def attach_committee_advisory(
    decision: CIODecision,
    report: CommitteeAdvisoryReport | None,
) -> CIODecision:
    """Attach advisory lineage without touching any authoritative decision field."""

    if not isinstance(decision, CIODecision):
        raise TypeError("decision must be CIODecision")
    record = advisory_monitoring_record(report)
    monitoring = tuple(dict.fromkeys((*decision.monitoring_indicators, record)))
    challenge_note = (
        " Pre-CIO Red Team advisory was unavailable; the canonical decision remained "
        "unchanged and no candidate restriction was introduced."
        if report is None
        else (
            " Pre-CIO Red Team advisory recorded the strongest counter-case, evidence "
            "overlap, disagreement, and specialist input depth. It has no vote, veto, "
            "qualification, sizing, threshold, or trade authority."
        )
    )
    return replace(
        decision,
        monitoring_indicators=monitoring,
        explanation=decision.explanation + challenge_note,
    )


class ChiefInvestmentOfficer(_IntegrityChiefInvestmentOfficer):
    """Canonical CIO plus an advisory-only Red Team observation boundary."""

    def synthesize(
        self,
        candidate,
        universe,
        specialists,
        *,
        capital_comparison=None,
        prior_context=None,
        analysis_lane: str = "acquisition",
    ) -> CIODecision:
        # Compute the challenge before the authoritative CIO decision, but never pass
        # the challenge into the action-selection call below.  This is the mechanical
        # guarantee that Red Team severity cannot suppress an otherwise viable asset.
        try:
            advisory = build_committee_advisory_report(
                candidate,
                specialists,
                capital_comparison=capital_comparison,
            )
        except Exception:
            advisory = None
            _LOGGER.exception(
                "pre-CIO committee advisory failed for %s; continuing without restriction",
                getattr(candidate, "identifier", "unknown"),
            )

        decision = super().synthesize(
            candidate,
            universe,
            specialists,
            capital_comparison=capital_comparison,
            prior_context=prior_context,
            analysis_lane=analysis_lane,
        )
        try:
            return attach_committee_advisory(decision, advisory)
        except Exception:
            _LOGGER.exception(
                "committee advisory lineage attachment failed for %s; preserving CIO decision",
                getattr(candidate, "identifier", "unknown"),
            )
            return decision


__all__ = [
    "ChiefInvestmentOfficer",
    "advisory_monitoring_record",
    "attach_committee_advisory",
]
