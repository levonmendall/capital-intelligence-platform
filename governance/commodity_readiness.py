"""Fail-closed commodity prerequisite for controlled paper execution.

Direct commodity futures and options remain prohibited.  Before any controlled
paper execution begins, the exact eligible-universe publication must contain
certified, unlevered U.S.-listed fund proxies for the required commodity groups,
and the decision process must have current licensed benchmark and curve evidence
for the underlying markets.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping


class CommodityReadinessError(RuntimeError):
    """Raised when commodity scope or evidence cannot authorize paper testing."""


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _timestamp(value: object, *, field_name: str) -> datetime:
    text = _text(value, field_name=field_name).replace("Z", "+00:00")
    try:
        return _aware(datetime.fromisoformat(text), field_name=field_name)
    except ValueError as error:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from error


def _boolean(value: object, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a bool")
    return value


def _positive_number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    normalized = float(value)
    if normalized <= 0:
        raise ValueError(f"{field_name} must be positive")
    return normalized


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _load_object(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CommodityReadinessError(
            f"cannot read commodity JSON document {str(source)!r}"
        ) from error
    if not isinstance(payload, dict):
        raise CommodityReadinessError("commodity JSON document must be an object")
    return payload


@dataclass(frozen=True, slots=True)
class CommodityBenchmarkRequirement:
    identifier: str
    minimum_history_years: float
    require_forward_curve: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identifier",
            _text(self.identifier, field_name="benchmark identifier").lower(),
        )
        object.__setattr__(
            self,
            "minimum_history_years",
            _positive_number(
                self.minimum_history_years,
                field_name="minimum_history_years",
            ),
        )
        _boolean(self.require_forward_curve, field_name="require_forward_curve")


@dataclass(frozen=True, slots=True)
class CommodityProxyRequirement:
    category: str
    minimum_eligible_proxies: int
    example_symbols: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "category",
            _text(self.category, field_name="proxy category").lower(),
        )
        if (
            isinstance(self.minimum_eligible_proxies, bool)
            or not isinstance(self.minimum_eligible_proxies, int)
            or self.minimum_eligible_proxies < 1
        ):
            raise ValueError("minimum_eligible_proxies must be a positive integer")
        normalized = tuple(
            _text(item, field_name="example symbol").upper()
            for item in self.example_symbols
        )
        if len(normalized) != len(set(normalized)):
            raise ValueError("example_symbols cannot contain duplicates")
        object.__setattr__(self, "example_symbols", normalized)


@dataclass(frozen=True, slots=True)
class CommodityPaperTestScope:
    identifier: str
    maximum_evidence_age_hours: float
    required_benchmarks: tuple[CommodityBenchmarkRequirement, ...]
    required_proxy_categories: tuple[CommodityProxyRequirement, ...]
    require_us_listed_etf: bool = True
    require_unlevered: bool = True
    prohibit_inverse: bool = True
    prohibit_direct_derivatives: bool = True
    schema_version: str = "commodity-paper-test-scope.v1"

    def __post_init__(self) -> None:
        for field_name in ("identifier", "schema_version"):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "maximum_evidence_age_hours",
            _positive_number(
                self.maximum_evidence_age_hours,
                field_name="maximum_evidence_age_hours",
            ),
        )
        if not self.required_benchmarks:
            raise ValueError("required_benchmarks cannot be empty")
        if not self.required_proxy_categories:
            raise ValueError("required_proxy_categories cannot be empty")
        benchmark_ids = tuple(item.identifier for item in self.required_benchmarks)
        proxy_categories = tuple(item.category for item in self.required_proxy_categories)
        if len(benchmark_ids) != len(set(benchmark_ids)):
            raise ValueError("required benchmark identifiers cannot repeat")
        if len(proxy_categories) != len(set(proxy_categories)):
            raise ValueError("required proxy categories cannot repeat")
        for field_name in (
            "require_us_listed_etf",
            "require_unlevered",
            "prohibit_inverse",
            "prohibit_direct_derivatives",
        ):
            _boolean(getattr(self, field_name), field_name=field_name)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CommodityPaperTestScope":
        benchmarks = payload.get("required_benchmarks")
        proxies = payload.get("required_proxy_categories")
        if not isinstance(benchmarks, list) or not isinstance(proxies, list):
            raise ValueError(
                "required_benchmarks and required_proxy_categories must be arrays"
            )
        return cls(
            identifier=str(payload["identifier"]),
            maximum_evidence_age_hours=float(
                payload["maximum_evidence_age_hours"]
            ),
            required_benchmarks=tuple(
                CommodityBenchmarkRequirement(
                    identifier=str(item["identifier"]),
                    minimum_history_years=float(item["minimum_history_years"]),
                    require_forward_curve=bool(
                        item.get("require_forward_curve", True)
                    ),
                )
                for item in benchmarks
            ),
            required_proxy_categories=tuple(
                CommodityProxyRequirement(
                    category=str(item["category"]),
                    minimum_eligible_proxies=int(
                        item.get("minimum_eligible_proxies", 1)
                    ),
                    example_symbols=tuple(
                        str(symbol) for symbol in item.get("example_symbols", ())
                    ),
                )
                for item in proxies
            ),
            require_us_listed_etf=bool(payload.get("require_us_listed_etf", True)),
            require_unlevered=bool(payload.get("require_unlevered", True)),
            prohibit_inverse=bool(payload.get("prohibit_inverse", True)),
            prohibit_direct_derivatives=bool(
                payload.get("prohibit_direct_derivatives", True)
            ),
            schema_version=str(
                payload.get("schema_version", "commodity-paper-test-scope.v1")
            ),
        )


def load_commodity_scope(
    path: str | Path = "config/commodity_paper_test_scope.json",
) -> CommodityPaperTestScope:
    return CommodityPaperTestScope.from_dict(_load_object(path))


def _benchmark_blockers(
    requirement: CommodityBenchmarkRequirement,
    evidence: Mapping[str, Any],
    *,
    assessed_at: datetime,
    knowledge_cutoff: datetime,
    maximum_age: timedelta,
) -> tuple[list[str], list[str]]:
    prefix = f"benchmark:{requirement.identifier}"
    blockers: list[str] = []
    identifiers: list[str] = []
    try:
        observed_at = _timestamp(evidence["observed_at"], field_name="observed_at")
        available_at = _timestamp(evidence["available_at"], field_name="available_at")
        retrieved_at = _timestamp(evidence["retrieved_at"], field_name="retrieved_at")
    except (KeyError, TypeError, ValueError) as error:
        return [f"{prefix}: invalid temporal provenance ({error})"], identifiers
    if not (observed_at <= available_at <= retrieved_at <= knowledge_cutoff <= assessed_at):
        blockers.append(f"{prefix}: future-known or inconsistent temporal provenance")
    if assessed_at - retrieved_at > maximum_age:
        blockers.append(f"{prefix}: evidence is stale")
    for field_name in (
        "licensed_use_approved",
        "point_in_time_supported",
        "market_price_ready",
        "history_ready",
    ):
        if evidence.get(field_name) is not True:
            blockers.append(f"{prefix}: {field_name} is not approved")
    if requirement.require_forward_curve and evidence.get("forward_curve_ready") is not True:
        blockers.append(f"{prefix}: forward_curve_ready is not approved")
    try:
        history_years = float(evidence.get("history_years", 0.0))
    except (TypeError, ValueError):
        history_years = 0.0
    if history_years < requirement.minimum_history_years:
        blockers.append(
            f"{prefix}: history is shorter than {requirement.minimum_history_years:g} years"
        )
    for field_name in (
        "source_identifier",
        "market_data_certification_identifier",
    ):
        value = evidence.get(field_name)
        if not isinstance(value, str) or not value.strip():
            blockers.append(f"{prefix}: {field_name} is unavailable")
        else:
            identifiers.append(value.strip())
    if requirement.require_forward_curve:
        curve = evidence.get("curve_certification_identifier")
        if not isinstance(curve, str) or not curve.strip():
            blockers.append(f"{prefix}: curve_certification_identifier is unavailable")
        else:
            identifiers.append(curve.strip())
    return blockers, identifiers


def _proxy_blockers(
    category: str,
    evidence: Mapping[str, Any],
    *,
    eligible_universe_publication_identifier: str,
    scope: CommodityPaperTestScope,
) -> tuple[list[str], list[str]]:
    symbol = str(evidence.get("symbol", "UNKNOWN")).strip().upper() or "UNKNOWN"
    prefix = f"proxy:{category}:{symbol}"
    blockers: list[str] = []
    identifiers: list[str] = []
    if str(evidence.get("category", "")).strip().lower() != category:
        blockers.append(f"{prefix}: category mismatch")
    if scope.require_us_listed_etf:
        if str(evidence.get("asset_class", "")).strip().lower() != "us_etf":
            blockers.append(f"{prefix}: exposure is not a U.S.-listed ETF")
        if str(evidence.get("country_code", "")).strip().upper() != "US":
            blockers.append(f"{prefix}: listing country is not US")
    if scope.require_unlevered and evidence.get("unlevered") is not True:
        blockers.append(f"{prefix}: proxy is leveraged or leverage is unverified")
    if scope.prohibit_inverse and evidence.get("inverse") is not False:
        blockers.append(f"{prefix}: inverse exposure is prohibited or unverified")
    if scope.prohibit_direct_derivatives and evidence.get("direct_derivative") is not False:
        blockers.append(f"{prefix}: direct derivative exposure is prohibited")
    for field_name in (
        "in_eligible_universe",
        "paper_eligible",
        "liquidity_ready",
        "execution_inputs_ready",
        "cost_model_ready",
    ):
        if evidence.get(field_name) is not True:
            blockers.append(f"{prefix}: {field_name} is not approved")
    if (
        str(evidence.get("eligible_universe_publication_identifier", "")).strip()
        != eligible_universe_publication_identifier
    ):
        blockers.append(f"{prefix}: eligible-universe publication mismatch")
    for field_name in (
        "instrument_identifier",
        "market_data_certification_identifier",
        "execution_certification_identifier",
    ):
        value = evidence.get(field_name)
        if not isinstance(value, str) or not value.strip():
            blockers.append(f"{prefix}: {field_name} is unavailable")
        else:
            identifiers.append(value.strip())
    sources = evidence.get("source_identifiers", ())
    if not isinstance(sources, list) or not sources:
        blockers.append(f"{prefix}: source_identifiers are unavailable")
    else:
        for value in sources:
            if isinstance(value, str) and value.strip():
                identifiers.append(value.strip())
            else:
                blockers.append(f"{prefix}: source_identifiers contain invalid values")
                break
    return blockers, identifiers


def evaluate_commodity_readiness(
    *,
    scope: CommodityPaperTestScope,
    evidence: Mapping[str, Any],
    assessed_at: datetime | None = None,
) -> dict[str, Any]:
    if not isinstance(scope, CommodityPaperTestScope):
        raise TypeError("scope must be CommodityPaperTestScope")
    timestamp = assessed_at or _timestamp(evidence["as_of"], field_name="as_of")
    timestamp = _aware(timestamp, field_name="assessed_at")
    knowledge_cutoff = _timestamp(
        evidence["knowledge_cutoff"],
        field_name="knowledge_cutoff",
    )
    expires_at = _timestamp(evidence["expires_at"], field_name="expires_at")
    if knowledge_cutoff > timestamp:
        raise CommodityReadinessError("knowledge_cutoff cannot follow assessed_at")
    blockers: list[str] = []
    if expires_at <= timestamp:
        blockers.append("commodity evidence is expired")
    for field_name in (
        "identifier",
        "baseline_identifier",
        "process_version",
        "code_version",
        "eligible_universe_publication_identifier",
    ):
        value = evidence.get(field_name)
        if not isinstance(value, str) or not value.strip():
            blockers.append(f"{field_name} is unavailable")
    evidence_identifier = str(evidence.get("identifier", "unidentified")).strip()
    publication_identifier = str(
        evidence.get("eligible_universe_publication_identifier", "")
    ).strip()
    benchmark_values = evidence.get("benchmarks")
    proxy_values = evidence.get("proxies")
    if not isinstance(benchmark_values, list):
        benchmark_values = []
        blockers.append("benchmarks must be an array")
    if not isinstance(proxy_values, list):
        proxy_values = []
        blockers.append("proxies must be an array")
    benchmark_map: dict[str, Mapping[str, Any]] = {}
    for item in benchmark_values:
        if not isinstance(item, Mapping):
            blockers.append("benchmarks contain a non-object value")
            continue
        identifier = str(item.get("identifier", "")).strip().lower()
        if not identifier:
            blockers.append("benchmark identifier is unavailable")
            continue
        if identifier in benchmark_map:
            blockers.append(f"benchmark:{identifier}: duplicate evidence")
            continue
        benchmark_map[identifier] = item
    evidence_identifiers: list[str] = [evidence_identifier]
    maximum_age = timedelta(hours=scope.maximum_evidence_age_hours)
    benchmark_coverage: list[dict[str, Any]] = []
    for requirement in scope.required_benchmarks:
        item = benchmark_map.get(requirement.identifier)
        if item is None:
            blockers.append(f"benchmark:{requirement.identifier}: evidence unavailable")
            benchmark_coverage.append(
                {"identifier": requirement.identifier, "ready": False}
            )
            continue
        item_blockers, identifiers = _benchmark_blockers(
            requirement,
            item,
            assessed_at=timestamp,
            knowledge_cutoff=knowledge_cutoff,
            maximum_age=maximum_age,
        )
        blockers.extend(item_blockers)
        evidence_identifiers.extend(identifiers)
        benchmark_coverage.append(
            {"identifier": requirement.identifier, "ready": not item_blockers}
        )
    proxies_by_category: dict[str, list[Mapping[str, Any]]] = {}
    for item in proxy_values:
        if not isinstance(item, Mapping):
            blockers.append("proxies contain a non-object value")
            continue
        category = str(item.get("category", "")).strip().lower()
        proxies_by_category.setdefault(category, []).append(item)
    proxy_coverage: list[dict[str, Any]] = []
    for requirement in scope.required_proxy_categories:
        ready_count = 0
        for item in proxies_by_category.get(requirement.category, ()): 
            item_blockers, identifiers = _proxy_blockers(
                requirement.category,
                item,
                eligible_universe_publication_identifier=publication_identifier,
                scope=scope,
            )
            if not item_blockers:
                ready_count += 1
                evidence_identifiers.extend(identifiers)
        if ready_count < requirement.minimum_eligible_proxies:
            blockers.append(
                f"proxy:{requirement.category}: requires "
                f"{requirement.minimum_eligible_proxies} eligible proxy/proxies; "
                f"found {ready_count}"
            )
        proxy_coverage.append(
            {
                "category": requirement.category,
                "ready_count": ready_count,
                "required_count": requirement.minimum_eligible_proxies,
                "ready": ready_count >= requirement.minimum_eligible_proxies,
            }
        )
    if evidence.get("direct_derivatives_authorized") is not False:
        blockers.append("direct commodity derivatives must remain unauthorized")
    report: dict[str, Any] = {
        "schema_version": "commodity-paper-test-readiness-report.v1",
        "identifier": f"commodity-readiness:{evidence_identifier}",
        "assessed_at": timestamp.isoformat(),
        "expires_at": expires_at.isoformat(),
        "scope_identifier": scope.identifier,
        "evidence_identifier": evidence_identifier,
        "baseline_identifier": evidence.get("baseline_identifier"),
        "process_version": evidence.get("process_version"),
        "code_version": evidence.get("code_version"),
        "eligible_universe_publication_identifier": publication_identifier,
        "ready": not blockers,
        "blockers": sorted(set(blockers)),
        "benchmark_coverage": benchmark_coverage,
        "proxy_coverage": proxy_coverage,
        "direct_derivatives_authorized": False,
        "evidence_identifiers": list(dict.fromkeys(evidence_identifiers)),
    }
    report["content_hash"] = hashlib.sha256(
        _canonical_json(report).encode("utf-8")
    ).hexdigest()
    return report


def build_commodity_readiness_report(
    *,
    scope_path: str | Path,
    evidence_path: str | Path,
    assessed_at: datetime | None = None,
) -> dict[str, Any]:
    return evaluate_commodity_readiness(
        scope=load_commodity_scope(scope_path),
        evidence=_load_object(evidence_path),
        assessed_at=assessed_at,
    )


def write_commodity_readiness_report(
    report: Mapping[str, Any],
    path: str | Path,
) -> None:
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def require_commodity_readiness_report(
    path: str | Path,
    *,
    as_of: datetime,
    eligible_universe_publication_identifier: str | None,
) -> Mapping[str, Any]:
    timestamp = _aware(as_of, field_name="as_of")
    payload = _load_object(path)
    if payload.get("schema_version") != "commodity-paper-test-readiness-report.v1":
        raise CommodityReadinessError("unsupported commodity readiness report schema")
    expected_hash = payload.get("content_hash")
    if not isinstance(expected_hash, str) or not expected_hash.strip():
        raise CommodityReadinessError("commodity readiness report hash is unavailable")
    unsigned = dict(payload)
    unsigned.pop("content_hash", None)
    actual_hash = hashlib.sha256(
        _canonical_json(unsigned).encode("utf-8")
    ).hexdigest()
    if actual_hash != expected_hash:
        raise CommodityReadinessError("commodity readiness report hash is invalid")
    if payload.get("ready") is not True:
        blockers = payload.get("blockers", ())
        detail = "; ".join(str(item) for item in blockers) or "not certified"
        raise CommodityReadinessError(
            f"commodity paper-test prerequisite is blocked: {detail}"
        )
    if payload.get("direct_derivatives_authorized") is not False:
        raise CommodityReadinessError(
            "commodity readiness cannot authorize direct derivatives"
        )
    expires_at = _timestamp(payload.get("expires_at"), field_name="expires_at")
    assessed_at = _timestamp(payload.get("assessed_at"), field_name="assessed_at")
    if assessed_at > timestamp:
        raise CommodityReadinessError("commodity readiness report is future-known")
    if expires_at <= timestamp:
        raise CommodityReadinessError("commodity readiness report is expired")
    publication = _text(
        eligible_universe_publication_identifier,
        field_name="eligible_universe_publication_identifier",
    )
    if payload.get("eligible_universe_publication_identifier") != publication:
        raise CommodityReadinessError(
            "commodity readiness report does not match the construction universe"
        )
    return payload


__all__ = [
    "CommodityPaperTestScope",
    "CommodityReadinessError",
    "build_commodity_readiness_report",
    "evaluate_commodity_readiness",
    "load_commodity_scope",
    "require_commodity_readiness_report",
    "write_commodity_readiness_report",
]
