"""Complete read-only CIO reports for cycle-level no-action decisions.

A governed CIO cycle can end before candidate-level specialist synthesis when every
candidate is rejected by the opportunity-qualification stage.  In that case the
canonical authority is the persisted ``cycle_disposition`` embedded in the exact
``daily_cio_briefing`` plus the exact-time opportunity queue that supports it.  A
candidate-level ``CIODecision`` or candidate evidence snapshot does not exist and must
not be fabricated merely to satisfy a presentation schema.

This module enriches only read/export presentation.  It reads append-only journal
records, proves exact-time alignment, exposes the qualification funnel and strongest
rejected opportunities, and makes the distinction between cycle-level and
candidate-level decisions explicit.  It cannot rank new candidates, change a hurdle,
change a CIO action, size a position, construct a portfolio, execute a trade, or
authorize real money.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping


_HISTORY_LIMIT = 2000
_CYCLE_MISSING_ISSUES = frozenset(
    {
        "cio_decision:missing_for_decision",
        "decision_evidence_snapshot:missing_for_decision",
        "cio_decision:code_version_not_recorded",
    }
)


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _values(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        text = _clean(value)
        return (text,) if text else ()
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
        return tuple(_clean(item) for item in value if _clean(item))
    return ()


def _history(app: object, event_type: str) -> tuple[Mapping[str, Any], ...]:
    loader = getattr(app, "_history", None)
    values: list[Mapping[str, Any]] = []
    if callable(loader):
        try:
            loaded = loader(event_type, limit=_HISTORY_LIMIT)
        except TypeError:
            try:
                loaded = loader(event_type)
            except (OSError, RuntimeError, TypeError, ValueError):
                loaded = ()
        except (OSError, RuntimeError, ValueError):
            loaded = ()
        if isinstance(loaded, Iterable) and not isinstance(
            loaded, (str, bytes, Mapping)
        ):
            values.extend(item for item in loaded if isinstance(item, Mapping))
    latest = getattr(app, "_latest", None)
    if callable(latest):
        try:
            item = latest(event_type)
        except (OSError, RuntimeError, TypeError, ValueError):
            item = None
        if isinstance(item, Mapping):
            values.insert(0, item)
    return tuple(values)


def _records(bundle: Mapping[str, Any]) -> dict[str, Any]:
    raw = bundle.get("records")
    return dict(raw) if isinstance(raw, Mapping) else {}


def _briefing(bundle: Mapping[str, Any]) -> Mapping[str, Any] | None:
    return _mapping(_records(bundle).get("daily_cio_briefing"))


def _cycle_disposition(
    briefing: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if not isinstance(briefing, Mapping):
        return None
    disposition = _mapping(briefing.get("cycle_disposition"))
    if disposition is None:
        return None
    identifier = _clean(disposition.get("identifier"))
    action = _clean(disposition.get("action"))
    authority = _clean(disposition.get("authority"))
    if not identifier or not action or authority != "CHIEF_INVESTMENT_OFFICER":
        return None
    return disposition


def _as_of(record: Mapping[str, Any] | None) -> str:
    if not isinstance(record, Mapping):
        return ""
    return _clean(record.get("as_of") or record.get("occurred_at"))


def _matching_queue(
    app: object,
    briefing: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    target_as_of = _as_of(briefing)
    if not target_as_of:
        return None
    for queue in _history(app, "opportunity_queue"):
        if _as_of(queue) == target_as_of:
            return queue
    return None


def _candidate_map(app: object) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for candidate in _history(app, "candidate_decision"):
        identifier = _clean(candidate.get("identifier"))
        if identifier and identifier not in result:
            result[identifier] = candidate
    return result


def _specialist_map(app: object) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for packet in _history(app, "specialist_packet"):
        identifier = _clean(packet.get("candidate_identifier"))
        if identifier and identifier not in result:
            result[identifier] = packet
    return result


def _number(record: Mapping[str, Any] | None, *names: str) -> float | None:
    if not isinstance(record, Mapping):
        return None
    for name in names:
        value = record.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            number = float(value)
            if number == number and number not in {float("inf"), float("-inf")}:
                return number
    return None


def _instrument(candidate: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(candidate, Mapping):
        return {}
    value = candidate.get("instrument")
    return dict(value) if isinstance(value, Mapping) else {}


def _evidence_quality(candidate: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(candidate, Mapping):
        return {}
    value = candidate.get("evidence_quality")
    return dict(value) if isinstance(value, Mapping) else {}


def _scenario(candidate: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(candidate, Mapping):
        return {}
    value = candidate.get("scenarios")
    return dict(value) if isinstance(value, Mapping) else {}


def _qualification_rows(queue: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(queue, Mapping):
        return ()
    rejected = queue.get("rejected")
    if not isinstance(rejected, Iterable) or isinstance(rejected, (str, bytes, Mapping)):
        return ()
    return tuple(item for item in rejected if isinstance(item, Mapping))


def _ranked_rows(queue: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(queue, Mapping):
        return ()
    ranked = queue.get("ranked")
    if not isinstance(ranked, Iterable) or isinstance(ranked, (str, bytes, Mapping)):
        return ()
    return tuple(item for item in ranked if isinstance(item, Mapping))


def _funnel(queue: Mapping[str, Any] | None, specialist_map: Mapping[str, Any]) -> dict[str, Any]:
    rejected = _qualification_rows(queue)
    ranked = _ranked_rows(queue)
    all_rows = (*ranked, *rejected)
    lane_counts = Counter(
        _clean(item.get("analysis_lane")) or "unclassified" for item in all_rows
    )
    qualified_ids = tuple(
        _clean(item.get("candidate_identifier")) for item in ranked
    )
    specialist_count = sum(1 for identifier in qualified_ids if identifier in specialist_map)
    return {
        "scope": "opportunity_qualification",
        "candidate_records_considered": len(all_rows),
        "qualified_for_specialist_synthesis": len(ranked),
        "rejected_before_specialist_synthesis": len(rejected),
        "specialist_packets_recorded": specialist_count,
        "cio_candidate_decisions_recorded": len(ranked),
        "market_lane_qualification_counts": dict(sorted(lane_counts.items())),
        "discovery_count_note": (
            "These counts begin at the governed candidate/opportunity-qualification "
            "boundary. Comprehensive discovery/catalog counts remain separate "
            "operational evidence and are not inferred by this report."
        ),
    }


def _candidate_analysis(
    rejection: Mapping[str, Any],
    candidate: Mapping[str, Any] | None,
) -> dict[str, Any]:
    instrument = _instrument(candidate)
    quality = _evidence_quality(candidate)
    scenario = _scenario(candidate)
    expected = _number(candidate, "net_expected_return")
    alternative = _number(rejection, "effective_opportunity_cost")
    edge = _number(rejection, "opportunity_edge")
    if edge is None and expected is not None and alternative is not None:
        edge = expected - alternative
    return {
        "candidate_identifier": _clean(rejection.get("candidate_identifier")),
        "symbol": _clean(instrument.get("symbol")) or None,
        "asset_class": _clean(instrument.get("asset_class")) or None,
        "analysis_lane": _clean(rejection.get("analysis_lane")) or None,
        "net_expected_return": expected,
        "effective_opportunity_cost": alternative,
        "opportunity_edge": edge,
        "best_alternative_identifier": (
            _clean(rejection.get("best_alternative_identifier")) or None
        ),
        "best_alternative_kind": _clean(rejection.get("best_alternative_kind")) or None,
        "expected_downside": _number(candidate, "expected_downside"),
        "probability_of_success": _number(candidate, "probability_of_success"),
        "liquidity_score": _number(candidate, "liquidity_score"),
        "implementation_cost_return": _number(candidate, "implementation_cost_return"),
        "evidence_quality_score": _number(quality, "score"),
        "decision_horizon_days": (
            candidate.get("decision_horizon_days")
            if isinstance(candidate, Mapping)
            else None
        ),
        "scenarios": scenario,
        "payoff_distribution": (
            list(candidate.get("payoff_distribution", ()))
            if isinstance(candidate, Mapping)
            else []
        ),
        "qualification_policy_profile": rejection.get("resolved_policy_profile"),
        "rejection_reasons": list(_values(rejection.get("reasons"))),
    }


def _top_rejected(
    queue: Mapping[str, Any] | None,
    candidates: Mapping[str, Mapping[str, Any]],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    rows = []
    for rejection in _qualification_rows(queue):
        identifier = _clean(rejection.get("candidate_identifier"))
        rows.append(_candidate_analysis(rejection, candidates.get(identifier)))
    rows.sort(
        key=lambda item: (
            item.get("opportunity_edge") is not None,
            float(item.get("opportunity_edge") or float("-inf")),
            float(item.get("net_expected_return") or float("-inf")),
        ),
        reverse=True,
    )
    return rows[:limit]


def _specialist_summary(
    queue: Mapping[str, Any] | None,
    specialists: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    ranked = _ranked_rows(queue)
    if not ranked:
        return {
            "status": "not_applicable_no_candidate_qualified",
            "analyses": [],
            "explanation": (
                "No candidate cleared qualification, so invoking the six specialists "
                "would have bypassed the governed opportunity funnel."
            ),
        }
    analyses: list[dict[str, Any]] = []
    for row in ranked:
        identifier = _clean(row.get("candidate_identifier"))
        packet = specialists.get(identifier)
        analyses.append(
            {
                "candidate_identifier": identifier,
                "packet_recorded": packet is not None,
                "support_ratio": _number(packet, "support_ratio"),
                "independent_support_ratio": _number(packet, "independent_support_ratio"),
                "coverage_ratio": _number(packet, "coverage_ratio"),
                "strongest_dissent": (
                    packet.get("strongest_dissent")
                    if isinstance(packet, Mapping)
                    else None
                ),
                "specialists": (
                    list(packet.get("analyses", ()))
                    if isinstance(packet, Mapping)
                    else []
                ),
            }
        )
    return {"status": "recorded" if all(item["packet_recorded"] for item in analyses) else "incomplete", "analyses": analyses}


def _cycle_auditability(
    bundle: dict[str, Any],
    briefing: Mapping[str, Any],
    disposition: Mapping[str, Any],
    queue: Mapping[str, Any] | None,
) -> None:
    audit = bundle.get("auditability")
    audit_map = dict(audit) if isinstance(audit, Mapping) else {}
    issues = [
        item
        for item in _values(audit_map.get("issues"))
        if item not in _CYCLE_MISSING_ISSUES
    ]
    code_version = _clean(briefing.get("code_version"))
    if not code_version or code_version.lower() == "unknown":
        issues.append("cycle_disposition:code_version_not_recorded")
    if queue is None:
        issues.append("opportunity_queue:missing_for_cycle_disposition")
    else:
        target_as_of = _as_of(briefing)
        if _as_of(queue) != target_as_of:
            issues.append("opportunity_queue:decision_time_mismatch")
    issues = list(dict.fromkeys(issues))
    audit_map.update(
        {
            "status": "auditable" if not issues else "non_auditable",
            "issues": issues,
            "decision_scope": "cycle_level_no_action",
            "cycle_disposition_is_canonical_cio_authority": True,
        }
    )
    bundle["auditability"] = audit_map

    release = bundle.get("release_identity")
    release_map = dict(release) if isinstance(release, Mapping) else {}
    release_map["decision_code_version"] = code_version or None
    release_map["decision_release_recorded"] = bool(
        code_version and code_version.lower() != "unknown"
    )
    bundle["release_identity"] = release_map

    bundle["decision_actions"] = {
        "selected_action": _clean(disposition.get("action")) or None,
        "effective_action": _clean(disposition.get("action")) or None,
        "deferred": False,
        "hysteresis_applied": False,
        "rationale": disposition.get("rationale"),
    }


def _reader_summary_for_cycle(
    bundle: dict[str, Any],
    disposition: Mapping[str, Any],
    strongest: Mapping[str, Any] | None,
) -> None:
    reader = bundle.get("reader_summary")
    summary = dict(reader) if isinstance(reader, Mapping) else {}
    action = _clean(disposition.get("action"))
    auditable = _mapping(bundle.get("auditability")) or {}
    complete = auditable.get("status") == "auditable"
    strongest_text = ""
    if isinstance(strongest, Mapping):
        symbol = _clean(strongest.get("symbol")) or _clean(
            strongest.get("candidate_identifier")
        )
        edge = strongest.get("opportunity_edge")
        alternative = strongest.get("best_alternative_identifier")
        if symbol:
            strongest_text = f" The strongest rejected opportunity was {symbol}"
            if isinstance(edge, (int, float)) and not isinstance(edge, bool):
                strongest_text += f" with a {float(edge):.1%} opportunity edge"
            if alternative:
                strongest_text += f" versus {alternative}"
            strongest_text += "."
    if action == "no_superior_opportunity":
        headline = "No portfolio change — no superior opportunity"
        portfolio_action = (
            "The CIO kept the current portfolio because every candidate failed at "
            "least one governed economic qualification hurdle."
        )
    else:
        headline = "No portfolio change — evidence or authority incomplete"
        portfolio_action = (
            "The CIO authorized no portfolio change because the opportunity set did "
            "not support a complete economic conclusion."
        )
    summary.update(
        {
            "status": "complete" if complete else "incomplete",
            "headline": headline,
            "portfolio_action": portfolio_action,
            "summary": portfolio_action + strongest_text,
            "audit_note": (
                "The cycle-level CIO disposition, exact-time opportunity queue, and "
                "decision code version are aligned."
                if complete
                else "Cycle-level decision lineage is incomplete; see auditability issues."
            ),
        }
    )
    bundle["reader_summary"] = summary


def enrich_report_bundle(app: object, bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Return a more complete investment report without changing decision authority."""

    result = dict(bundle)
    records = _records(result)
    briefing = _mapping(records.get("daily_cio_briefing"))
    queue = _matching_queue(app, briefing)
    candidates = _candidate_map(app)
    specialists = _specialist_map(app)
    disposition = _cycle_disposition(briefing)

    relevant_candidate_ids = {
        _clean(item.get("candidate_identifier"))
        for item in (*_ranked_rows(queue), *_qualification_rows(queue))
        if _clean(item.get("candidate_identifier"))
    }
    relevant_candidates = {
        key: value for key, value in candidates.items() if key in relevant_candidate_ids
    }
    relevant_specialists = {
        key: value for key, value in specialists.items() if key in relevant_candidate_ids
    }

    records["cycle_disposition"] = dict(disposition) if disposition else None
    records["opportunity_queue"] = dict(queue) if queue else None
    records["candidate_decisions_considered"] = list(relevant_candidates.values())
    records["specialist_packets"] = list(relevant_specialists.values())
    result["records"] = records

    top = _top_rejected(queue, candidates)
    result["investment_analysis"] = {
        "decision_scope": (
            "cycle_level_no_action"
            if disposition is not None and records.get("cio_decision") is None
            else "candidate_level"
        ),
        "opportunity_funnel": _funnel(queue, specialists),
        "top_rejected_opportunities": top,
        "specialist_review": _specialist_summary(queue, specialists),
        "portfolio_relative_opportunity": (
            top[0] if top else None
        ),
        "qualification_gaps_that_would_need_to_reverse": (
            list(_values(briefing.get("evidence_that_changes_conclusion")))
            if isinstance(briefing, Mapping)
            else []
        ),
        "reporting_limitations": [
            "Comprehensive discovery/catalog counts are not inferred from the opportunity queue.",
            "Candidates rejected before specialist synthesis correctly have no six-specialist packet.",
        ],
    }

    if (
        disposition is not None
        and isinstance(briefing, Mapping)
        and records.get("cio_decision") is None
    ):
        _cycle_auditability(result, briefing, disposition, queue)
        _reader_summary_for_cycle(result, disposition, top[0] if top else None)
        presence = result.get("record_presence")
        presence_map = dict(presence) if isinstance(presence, Mapping) else {}
        presence_map.update(
            {
                "cycle_disposition": True,
                "opportunity_queue": queue is not None,
                "candidate_decisions_considered": bool(relevant_candidates),
                "specialist_packets": bool(relevant_specialists),
            }
        )
        result["record_presence"] = presence_map
        result["report_schema_version"] = "cio-investment-report.v2-cycle-aware"

    authority = result.get("authority")
    authority_map = dict(authority) if isinstance(authority, Mapping) else {}
    authority_map.update(
        {
            "read_only_export": True,
            "candidate_authority": False,
            "ranking_authority": False,
            "sizing_authority": False,
            "execution_authority": False,
            "paper_only": True,
            "real_money_authorized": False,
        }
    )
    result["authority"] = authority_map
    return result


__all__ = ["enrich_report_bundle"]
