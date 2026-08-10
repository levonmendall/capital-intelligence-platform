"""Certified public forward-research adapters.

The first implementation promotes only matched CFTC managed-money observations from
the strict public decision-information provider into the existing positioning
research contract.  Missing or ambiguous contract matches remain unavailable rather
than neutral.  This evidence does not create candidates, change thresholds, size
positions, or authorize execution.
"""
from __future__ import annotations

import re
from datetime import timedelta

from intelligence.forward_research import (
    ForwardResearchEvidence,
    PositioningEvidenceKind,
    PositioningIntelligenceEngine,
    PositioningObservation,
)
from providers.public_decision_information import (
    PublicDecisionInformationProvider,
    build_public_decision_information_provider,
)


_CFTC_ALIASES: dict[str, tuple[str, ...]] = {
    "CL": ("crude oil", "wti", "light sweet crude"),
    "USO": ("crude oil", "wti", "light sweet crude"),
    "NG": ("natural gas",),
    "GC": ("gold",),
    "GLD": ("gold",),
    "SI": ("silver",),
    "SLV": ("silver",),
    "HG": ("copper",),
    "ZC": ("corn",),
    "ZW": ("wheat",),
    "ZS": ("soybean", "soybeans"),
    "6E": ("euro", "euro fx"),
    "6J": ("japanese yen", "yen"),
    "6B": ("british pound", "pound sterling"),
    "ES": ("s&p 500", "e-mini s&p"),
    "NQ": ("nasdaq-100", "nasdaq 100", "e-mini nasdaq"),
    "ZN": ("10-year", "10 year treasury", "u.s. treasury notes"),
}

_POSITION_RE = re.compile(
    r"Open interest\s+([^;]+);\s+managed-money long\s+([^;]+);\s+"
    r"managed-money short\s+([^;]+)",
    re.IGNORECASE,
)


def _number(value: str) -> float | None:
    normalized = value.strip().replace(",", "")
    if not normalized or normalized.lower() in {"unknown", "none", "null", "nan"}:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def _aliases(candidate: object) -> tuple[str, ...]:
    instrument = getattr(candidate, "instrument")
    symbol = str(getattr(instrument, "symbol", "")).strip().upper()
    name = str(getattr(instrument, "name", "")).strip().casefold()
    root = symbol.split("-")[0].split("_")[0]
    values = [name] if name else []
    values.extend(_CFTC_ALIASES.get(symbol, ()))
    values.extend(_CFTC_ALIASES.get(root, ()))
    return tuple(dict.fromkeys(item.casefold() for item in values if len(item) >= 3))


class PublicForwardResearchProvider:
    """Translate exact matched public observations into research-only evidence."""

    def __init__(self, information: PublicDecisionInformationProvider) -> None:
        if not isinstance(information, PublicDecisionInformationProvider):
            raise TypeError("information must be PublicDecisionInformationProvider")
        self.information = information

    @property
    def name(self) -> str:
        return "certified-public-forward-research"

    def fetch(self, candidate: object) -> ForwardResearchEvidence | None:
        as_of = getattr(candidate, "as_of")
        aliases = _aliases(candidate)
        if not aliases:
            return None
        records = self.information.records(
            start_at=as_of - timedelta(days=14),
            as_of=as_of,
        )
        matched = []
        for record in records:
            if "cftc-positioning-observation" not in {
                item.casefold() for item in record.tags
            }:
                continue
            text = " ".join(
                (
                    record.topic,
                    record.summary,
                    *record.tags,
                    *record.entities,
                )
            ).casefold()
            if not any(alias in text for alias in aliases):
                continue
            parsed = _POSITION_RE.search(record.summary)
            if parsed is None:
                continue
            open_interest = _number(parsed.group(1))
            long_position = _number(parsed.group(2))
            short_position = _number(parsed.group(3))
            if (
                open_interest is None
                or long_position is None
                or short_position is None
                or open_interest <= 0.0
            ):
                continue
            directional = max(
                -1.0,
                min(
                    1.0,
                    (long_position - short_position)
                    / max(long_position + short_position, 1.0),
                ),
            )
            crowding = max(
                0.0,
                min(1.0, abs(long_position - short_position) / open_interest * 2.0),
            )
            confidence = max(
                0.0,
                min(
                    0.95,
                    record.reliability
                    * record.relevance
                    * max(0.60, record.independence),
                ),
            )
            matched.append(
                PositioningObservation(
                    identifier=f"positioning:{record.identifier}",
                    subject_identifier=str(getattr(getattr(candidate, "instrument"), "symbol")),
                    kind=PositioningEvidenceKind.FUTURES_POSITIONING,
                    as_of=as_of,
                    directional_pressure=round(directional, 8),
                    crowding=round(crowding, 8),
                    confidence=round(confidence, 8),
                    evidence_identifiers=(
                        record.identifier,
                        f"public-content:{record.content_hash}",
                    ),
                )
            )
        if not matched:
            return None
        # Keep the newest bounded set. CFTC rows may contain multiple weekly
        # observations for the same contract in the rolling public record file.
        observations = tuple(matched[-8:])
        return ForwardResearchEvidence(
            positioning=PositioningIntelligenceEngine().analyze(observations),
            schema_version="forward-research-evidence.v1+cftc-public-positioning.v1",
        )


def build_public_forward_research_provider() -> PublicForwardResearchProvider | None:
    information = build_public_decision_information_provider()
    if information is None:
        return None
    return PublicForwardResearchProvider(information)


__all__ = [
    "PublicForwardResearchProvider",
    "build_public_forward_research_provider",
]
