"""Reconcile predictive scenarios with existing forward scenarios.

The canonical robustness path requires one unique scenario for each disclosed label.
Predictive market intelligence therefore combines same-label deltas instead of
appending a second bull/base/bear set.  This preserves every rationale and evidence
identifier while retaining the existing bounded scenario-adjustment limits.
"""

from __future__ import annotations

import hashlib
import json

from intelligence.forward import ForwardIntelligenceBundle, ForwardScenario


def _clip(value: float, low: float, high: float) -> float:
    return round(max(low, min(high, float(value))), 8)


def _identifier(existing: str, predictive: str) -> str:
    digest = hashlib.sha256(
        json.dumps(
            [existing, predictive],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return digest


def reconcile_forward_intelligence(
    existing: ForwardIntelligenceBundle | None,
    predictive: ForwardIntelligenceBundle,
) -> ForwardIntelligenceBundle:
    if existing is None:
        return predictive
    if existing.candidate_identifier != predictive.candidate_identifier:
        raise ValueError("forward-intelligence bundles refer to different candidates")
    if existing.as_of != predictive.as_of:
        raise ValueError("forward-intelligence bundles have different as_of timestamps")

    signals = tuple(
        {
            item.identifier: item
            for item in (*existing.signals, *predictive.signals)
        }.values()
    )
    grouped: dict[str, list[ForwardScenario]] = {}
    for item in (*existing.scenarios, *predictive.scenarios):
        grouped.setdefault(item.label, []).append(item)
    scenarios = tuple(
        ForwardScenario(
            label=label,
            return_delta=_clip(
                sum(item.return_delta for item in values),
                -0.25,
                0.25,
            ),
            probability_delta=_clip(
                sum(item.probability_delta for item in values),
                -0.20,
                0.20,
            ),
            path_drawdown_delta=_clip(
                sum(item.path_drawdown_delta for item in values),
                -0.25,
                0.0,
            ),
            rationale=" ".join(
                dict.fromkeys(item.rationale for item in values)
            ),
            evidence_identifiers=tuple(
                dict.fromkeys(
                    identifier
                    for item in values
                    for identifier in item.evidence_identifiers
                )
            ),
        )
        for label, values in sorted(grouped.items())
    )
    return ForwardIntelligenceBundle(
        identifier=(
            "forward-intelligence:merged:"
            f"{existing.candidate_identifier}:{existing.as_of.isoformat()}:"
            f"{_identifier(existing.identifier, predictive.identifier)}"
        ),
        candidate_identifier=existing.candidate_identifier,
        as_of=existing.as_of,
        signals=signals,
        scenarios=scenarios,
        diagnostics=tuple(
            dict.fromkeys((*existing.diagnostics, *predictive.diagnostics))
        ),
        model_versions=tuple(
            dict.fromkeys((*existing.model_versions, *predictive.model_versions))
        ),
        theme_stage=existing.theme_stage or predictive.theme_stage,
        trend_stage=existing.trend_stage or predictive.trend_stage,
        policy_regime=existing.policy_regime or predictive.policy_regime,
        currency_regime=existing.currency_regime or predictive.currency_regime,
        schema_version="forward-intelligence.v2-predictive-market",
    )


__all__ = ["reconcile_forward_intelligence"]
