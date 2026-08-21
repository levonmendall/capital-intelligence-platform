"""Typed, credential-safe attribution for release evidence prequalification.

The evidence plane remains fail-closed. This module does not decide whether evidence is
acceptable and cannot promote an instrument, create a CIO request, or authorize execution.
It only converts already-sanitized release-qualifier provenance into a bounded,
machine-readable readiness result so production diagnostics identify the failing boundary
without weakening any existing freshness, completeness, or provider rule.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence


class EvidencePrequalificationState(str, Enum):
    READY = "ready"
    FAILED = "failed"


class EvidencePrequalificationReason(str, Enum):
    READY = "ready"
    MISSING_PROVIDER = "missing_provider"
    PROVIDER_ERROR = "provider_error"
    STALE = "stale"
    INCOMPLETE = "incomplete"
    INVALID_PAYLOAD = "invalid_payload"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    FALLBACK_EXHAUSTED = "fallback_exhausted"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    RESOURCE_BUSY = "resource_busy"
    INTERNAL_ERROR = "internal_error"


_PROVIDER_NAMES = (
    "alpaca", "tradier", "massive", "cme", "eodhd", "yahoo", "fred", "sec",
    "databento", "deribit", "openfigi", "fca", "esma", "jpx", "hkex", "nasdaq",
    "oecd", "imf", "bis", "world bank", "eia", "cftc",
)

_STAGE_CAPABILITIES = {
    "qualified_global_discovery_snapshot": "global_discovery_snapshot",
    "qualified_us_equity_discovery_snapshot": "us_equity_discovery_snapshot",
    "qualified_evidence_universe": "evidence_universe",
    "qualified_paper_evidence_snapshot": "paper_evidence_snapshot",
    "component_qualified_evidence_maintenance": "evidence_maintenance",
    "continuous_evidence_plane": "evidence_maintenance",
}

_WATCHDOG_PHASE_CAPABILITIES = {
    "reference": "reference_components",
    "reference_acquisition": "reference_components",
    "reference_binding": "reference_components",
    "public_live": "public_live_information",
    "us_equity_discovery": "us_equity_discovery",
    "discovery_bootstrap": "comprehensive_discovery",
    "discovery_preparation": "comprehensive_discovery",
    "comprehensive_discovery": "comprehensive_discovery",
    "paper_evidence": "paper_evidence",
    "global_finalizer": "generation_publication",
    "finalize": "generation_publication",
}


@dataclass(frozen=True, slots=True)
class EvidencePrequalificationAttribution:
    state: EvidencePrequalificationState
    reason: EvidencePrequalificationReason
    capability: str
    required_information: str | None = None
    failure_stage: str | None = None
    error_type: str | None = None
    root_error_type: str | None = None
    provider: str | None = None
    fallback_providers_attempted: tuple[str, ...] = ()
    affected_instrument_count: int | None = None
    freshness_age_seconds: float | None = None
    freshness_limit_seconds: float | None = None
    completeness: str = "unknown"
    detail: str = ""
    terminal: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "reason": self.reason.value,
            "capability": self.capability,
            "required_information": self.required_information,
            "failure_stage": self.failure_stage,
            "error_type": self.error_type,
            "root_error_type": self.root_error_type,
            "provider": self.provider,
            "fallback_providers_attempted": list(self.fallback_providers_attempted),
            "affected_instrument_count": self.affected_instrument_count,
            "freshness_age_seconds": self.freshness_age_seconds,
            "freshness_limit_seconds": self.freshness_limit_seconds,
            "completeness": self.completeness,
            "detail": self.detail[:1600],
            "terminal": self.terminal,
            "credential_safe": True,
            "paper_only": True,
            "real_money_authorized": False,
        }


_CHILD_PATTERN = re.compile(
    r"child_stage=(?P<stage>[^;]+);\s*"
    r"child_error_type=(?P<error_type>[^;]+);\s*"
    r"child_detail=(?P<detail>.*)$",
    flags=re.IGNORECASE | re.DOTALL,
)


def _text(value: object, *, limit: int = 1600) -> str:
    return str(value or "").strip()[:limit]


def _extract_named_token(text: str, name: str, *, limit: int = 240) -> str | None:
    match = re.search(
        rf"(?i)(?:^|[;\s,]){re.escape(name)}\s*[=:]\s*([A-Za-z0-9_.:-]+)", text
    )
    if match is None:
        return None
    value = match.group(1).strip().lower()
    return value[:limit] or None


def _extract_number(text: str, names: Sequence[str]) -> float | None:
    for name in names:
        match = re.search(
            rf"(?i)(?:^|[;\s,]){re.escape(name)}\s*[=:]\s*([0-9]+(?:\.[0-9]+)?)",
            text,
        )
        if match is not None:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    return None


def _extract_count(text: str) -> int | None:
    value = _extract_number(text, ("affected_instrument_count", "instrument_count", "affected_count"))
    return None if value is None else max(0, int(value))


def _extract_providers(text: str) -> tuple[str | None, tuple[str, ...]]:
    lowered = text.lower()
    observed: list[str] = []
    for provider in _PROVIDER_NAMES:
        if re.search(rf"(?<![a-z0-9]){re.escape(provider)}(?![a-z0-9])", lowered):
            normalized = provider.replace(" ", "_")
            if normalized not in observed:
                observed.append(normalized)

    explicit_primary = re.search(
        r"(?i)(?:primary_)?provider\s*[=:]\s*([A-Za-z0-9_.-]+)", text
    )
    provider = (
        explicit_primary.group(1).strip().lower()
        if explicit_primary is not None
        else (observed[0] if observed else None)
    )

    fallback: list[str] = []
    explicit_fallback = re.search(
        r"(?i)fallback(?:_providers)?(?:_attempted)?\s*[=:]\s*([^;]+)", text
    )
    if explicit_fallback is not None:
        for raw in re.split(r"[,|>\s]+", explicit_fallback.group(1)):
            normalized = raw.strip().lower()
            if normalized and normalized not in {"none", "false", "0"}:
                if normalized != provider and normalized not in fallback:
                    fallback.append(normalized)
    elif "fallback" in lowered and len(observed) > 1:
        fallback.extend(item for item in observed if item != provider)
    return provider, tuple(fallback[:12])


def _watchdog_capability(stage: str, error_type: str, detail: str) -> str | None:
    if (
        stage.strip().lower() != "release_prequalification_parent_watchdog"
        and error_type.strip().lower() != "parentstalltimeout"
    ):
        return None
    phase = _extract_named_token(detail, "prequalification_phase")
    if phase is None:
        return None
    return _WATCHDOG_PHASE_CAPABILITIES.get(phase)


def _capability(stage: str, detail: str) -> str:
    normalized_stage = stage.strip().lower()
    if normalized_stage in _STAGE_CAPABILITIES:
        candidate = _STAGE_CAPABILITIES[normalized_stage]
        if candidate != "evidence_maintenance":
            return candidate

    lowered = detail.lower()
    if any(token in lowered for token in ("reference", "instrument-master", "futures", "option definition")):
        return "reference_components"
    if "public live" in lowered or "public_live" in lowered:
        return "public_live_information"
    if "historical" in lowered or "market_history" in lowered:
        return "historical_evidence"
    if "paper evidence" in lowered or "paper_evidence" in lowered:
        return "paper_evidence"
    if "equity discovery" in lowered or "us equity" in lowered:
        return "us_equity_discovery"
    if "discovery" in lowered or "catalog" in lowered:
        return "comprehensive_discovery"
    if "memory lane" in lowered or "memory_limited" in lowered:
        return "operational_memory_lane"
    if "qualified generation" in lowered or "generation" in lowered:
        return "generation_publication"
    return _STAGE_CAPABILITIES.get(normalized_stage, "evidence_maintenance")


def _reason(*, detail: str, error_type: str, return_code: int | None) -> EvidencePrequalificationReason:
    lowered = detail.lower()
    type_name = error_type.lower()
    if return_code == 124 or "deadline" in lowered or "timed out" in lowered or "timeout" in type_name:
        return EvidencePrequalificationReason.DEADLINE_EXCEEDED
    if return_code == 125 or any(
        token in lowered for token in ("memory_limited", "memory limited", "out of memory", "oom", "memoryerror")
    ):
        return EvidencePrequalificationReason.RESOURCE_EXHAUSTED
    if return_code == 126 or "memory lane busy" in lowered or "heavy_memory_lane_busy" in lowered:
        return EvidencePrequalificationReason.RESOURCE_BUSY
    if any(token in lowered for token in (
        "fallback exhausted", "fallbacks exhausted", "all providers failed",
        "no provider succeeded", "no provider could",
    )):
        return EvidencePrequalificationReason.FALLBACK_EXHAUSTED
    if any(token in lowered for token in (
        "missing provider", "provider is not configured", "provider not configured",
        "api key is required", "api token is required", "credential is required",
        "credentials are required",
    )):
        return EvidencePrequalificationReason.MISSING_PROVIDER
    if any(token in lowered for token in ("stale", "freshness", "too old", "expired evidence", "expired snapshot")):
        return EvidencePrequalificationReason.STALE
    if any(token in lowered for token in (
        "jsondecodeerror", "invalid payload", "malformed", "schema mismatch",
        "integrity mismatch", "digest mismatch", "unreadable", "not an object",
    )) or type_name in {"jsondecodeerror", "unicodeerror"}:
        return EvidencePrequalificationReason.INVALID_PAYLOAD
    if any(token in lowered for token in (
        "429", "rate limit", "http 5", "connectionerror", "connection error",
        "connection reset", "provider error", "provider unavailable", "request failed",
    )):
        return EvidencePrequalificationReason.PROVIDER_ERROR
    if any(token in lowered for token in (
        "not qualified", "incomplete", "missing evidence", "missing snapshot",
        "no previously qualified", "coverage is not qualified", "coverage incomplete",
        "returned success without a qualified generation",
    )):
        return EvidencePrequalificationReason.INCOMPLETE
    return EvidencePrequalificationReason.INTERNAL_ERROR


def ready_prequalification_attribution(*, capability: str = "all_required_evidence") -> EvidencePrequalificationAttribution:
    return EvidencePrequalificationAttribution(
        state=EvidencePrequalificationState.READY,
        reason=EvidencePrequalificationReason.READY,
        capability=_text(capability, limit=160) or "all_required_evidence",
        completeness="complete",
        terminal=False,
    )


def failed_prequalification_attribution(
    *, detail: object, metrics: Mapping[str, int] | None = None
) -> EvidencePrequalificationAttribution:
    raw_detail = _text(detail)
    child = _CHILD_PATTERN.search(raw_detail)
    if child is None:
        stage = "evidence_prequalification"
        error_type = ""
        child_detail = raw_detail
    else:
        stage = _text(child.group("stage"), limit=160) or "continuous_evidence_plane"
        error_type = _text(child.group("error_type"), limit=120)
        child_detail = _text(child.group("detail"))

    start_error = re.search(r"evidence qualifier could not start:\s*([A-Za-z0-9_.]+)", raw_detail)
    if not error_type and start_error is not None:
        error_type = start_error.group(1)[:120]

    root_match = re.search(
        r"(?i)(?:failed|failure|error):\s*([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception))\s*:",
        child_detail,
    )
    root_error_type = root_match.group(1)[:120] if root_match is not None else None

    return_code = None
    if metrics is not None:
        raw_code = metrics.get("qualifier_return_code")
        negative = metrics.get("qualifier_return_code_negative", 0)
        if isinstance(raw_code, int) and not isinstance(raw_code, bool):
            return_code = -raw_code if negative else raw_code

    provider, fallback_providers = _extract_providers(child_detail)
    freshness_age = _extract_number(child_detail, ("freshness_age_seconds", "evidence_age_seconds", "age_seconds"))
    freshness_limit = _extract_number(child_detail, ("freshness_limit_seconds", "max_age_seconds", "maximum_age_seconds"))
    reason = _reason(
        detail=child_detail or raw_detail,
        error_type=root_error_type or error_type,
        return_code=return_code,
    )
    completeness = "incomplete" if reason in {
        EvidencePrequalificationReason.INCOMPLETE,
        EvidencePrequalificationReason.MISSING_PROVIDER,
        EvidencePrequalificationReason.STALE,
        EvidencePrequalificationReason.FALLBACK_EXHAUSTED,
    } else "unknown"
    diagnostic_detail = child_detail or raw_detail
    capability = _watchdog_capability(stage, error_type, diagnostic_detail) or _capability(stage, diagnostic_detail)

    return EvidencePrequalificationAttribution(
        state=EvidencePrequalificationState.FAILED,
        reason=reason,
        capability=capability,
        required_information=_extract_named_token(diagnostic_detail, "required_information"),
        failure_stage=stage,
        error_type=error_type or None,
        root_error_type=root_error_type,
        provider=provider,
        fallback_providers_attempted=fallback_providers,
        affected_instrument_count=_extract_count(child_detail),
        freshness_age_seconds=freshness_age,
        freshness_limit_seconds=freshness_limit,
        completeness=completeness,
        detail=diagnostic_detail,
        terminal=True,
    )


__all__ = [
    "EvidencePrequalificationAttribution",
    "EvidencePrequalificationReason",
    "EvidencePrequalificationState",
    "failed_prequalification_attribution",
    "ready_prequalification_attribution",
]
