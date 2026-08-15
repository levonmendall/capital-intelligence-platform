"""Persist bounded SEC 13F, Companies House and Deribit research evidence."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from providers.global_public_research import (
    CompaniesHouseProvider,
    DeribitPublicMarketProvider,
    GlobalPublicResearchError,
    SEC13FStructuredDatasetProvider,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(payload), sort_keys=True, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _read_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, Mapping) else {}


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class ResearchLaneResult:
    lane: str
    state: str
    record_count: int
    content_hash: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "lane": self.lane,
            "state": self.state,
            "record_count": self.record_count,
            "content_hash": self.content_hash,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class GlobalPublicResearchMaintenanceReport:
    evaluated_at: datetime
    lanes: tuple[ResearchLaneResult, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "global-public-research-maintenance.v1",
            "evaluated_at": self.evaluated_at.isoformat(),
            "lanes": [item.to_dict() for item in self.lanes],
            "decision_evidence_authority": False,
            "investment_authority": False,
            "execution_authority": False,
            "paper_only": True,
            "real_money_authorized": False,
        }


def _due(state_path: Path, *, now: datetime, interval: timedelta) -> bool:
    completed = _timestamp(_read_json(state_path).get("completed_at"))
    return completed is None or now - completed >= interval


def _sec_13f_lane(
    root: Path,
    *,
    now: datetime,
    values: Mapping[str, str],
    provider_factory: Callable[..., object],
) -> ResearchLaneResult:
    state_path = root / "sec_13f_state.json"
    output_path = root / "sec_13f_latest.json"
    if not _due(state_path, now=now, interval=timedelta(days=7)):
        previous = _read_json(output_path)
        return ResearchLaneResult(
            lane="sec_13f",
            state="fresh",
            record_count=int(previous.get("processed_rows", 0) or 0),
            content_hash=str(previous.get("content_hash") or "") or None,
        )
    if not str(values.get("SEC_USER_AGENT", "")).strip():
        return ResearchLaneResult(
            lane="sec_13f",
            state="unconfigured",
            record_count=0,
            detail="SEC_USER_AGENT is not configured",
        )
    try:
        provider = provider_factory(user_agent=values.get("SEC_USER_AGENT"))
        summary = provider.collect()
        payload = summary.to_dict()
        _write_json(output_path, payload)
        _write_json(
            state_path,
            {
                "completed_at": now.isoformat(),
                "content_hash": summary.content_hash,
                "dataset_url": summary.dataset_url,
            },
        )
        return ResearchLaneResult(
            lane="sec_13f",
            state="stored",
            record_count=summary.processed_rows,
            content_hash=summary.content_hash,
            detail=("bounded/truncated" if summary.truncated else "complete within row budget"),
        )
    except (OSError, RuntimeError, ValueError, GlobalPublicResearchError) as error:
        return ResearchLaneResult(
            lane="sec_13f",
            state="degraded",
            record_count=0,
            detail=f"{type(error).__name__}: {str(error)[:600]}",
        )


def _companies_house_lane(
    root: Path,
    *,
    now: datetime,
    values: Mapping[str, str],
    provider_factory: Callable[..., object],
) -> ResearchLaneResult:
    raw_numbers = str(
        values.get("CAPITAL_INTELLIGENCE_COMPANIES_HOUSE_COMPANY_NUMBERS", "")
    )
    numbers = tuple(
        dict.fromkeys(item.strip().upper() for item in raw_numbers.split(",") if item.strip())
    )
    if not numbers:
        return ResearchLaneResult(
            lane="companies_house",
            state="waiting_for_candidates",
            record_count=0,
            detail=(
                "Set CAPITAL_INTELLIGENCE_COMPANIES_HOUSE_COMPANY_NUMBERS from "
                "resolved UK issuer identities; no global company crawl is attempted."
            ),
        )
    if not str(values.get("COMPANIES_HOUSE_API_KEY", "")).strip():
        return ResearchLaneResult(
            lane="companies_house",
            state="unconfigured",
            record_count=0,
            detail="COMPANIES_HOUSE_API_KEY is not configured",
        )
    state_path = root / "companies_house_state.json"
    if not _due(state_path, now=now, interval=timedelta(hours=24)):
        return ResearchLaneResult(
            lane="companies_house",
            state="fresh",
            record_count=len(numbers),
        )
    try:
        provider = provider_factory(api_key=values.get("COMPANIES_HOUSE_API_KEY"))
        records = []
        for number in numbers[:100]:
            records.append(provider.collect_company(number).to_dict())
        payload = {
            "schema_version": "companies-house-candidate-evidence.v1",
            "evaluated_at": now.isoformat(),
            "records": records,
            "candidate_driven": True,
            "decision_evidence_authority": False,
            "real_money_authorized": False,
        }
        _write_json(root / "companies_house_latest.json", payload)
        _write_json(state_path, {"completed_at": now.isoformat()})
        return ResearchLaneResult(
            lane="companies_house",
            state="stored",
            record_count=len(records),
        )
    except (OSError, RuntimeError, ValueError, GlobalPublicResearchError) as error:
        return ResearchLaneResult(
            lane="companies_house",
            state="degraded",
            record_count=0,
            detail=f"{type(error).__name__}: {str(error)[:600]}",
        )


def _deribit_lane(
    root: Path,
    *,
    now: datetime,
    provider_factory: Callable[..., object],
) -> ResearchLaneResult:
    state_path = root / "deribit_state.json"
    if not _due(state_path, now=now, interval=timedelta(minutes=30)):
        previous = _read_json(root / "deribit_latest.json")
        return ResearchLaneResult(
            lane="deribit",
            state="fresh",
            record_count=int(previous.get("record_count", 0) or 0),
        )
    try:
        provider = provider_factory()
        summaries = []
        record_count = 0
        for currency in ("BTC", "ETH"):
            for kind in ("future", "option"):
                summary = provider.collect(currency, kind=kind)
                summaries.append(summary.to_dict())
                record_count += len(summary.instruments)
        payload = {
            "schema_version": "deribit-public-market-depth.v1",
            "evaluated_at": now.isoformat(),
            "record_count": record_count,
            "summaries": summaries,
            "decision_evidence_authority": False,
            "execution_authority": False,
            "real_money_authorized": False,
        }
        _write_json(root / "deribit_latest.json", payload)
        _write_json(state_path, {"completed_at": now.isoformat()})
        return ResearchLaneResult(
            lane="deribit",
            state="stored",
            record_count=record_count,
        )
    except (OSError, RuntimeError, ValueError, GlobalPublicResearchError) as error:
        return ResearchLaneResult(
            lane="deribit",
            state="degraded",
            record_count=0,
            detail=f"{type(error).__name__}: {str(error)[:600]}",
        )


def maintain_global_public_research(
    *,
    values: Mapping[str, str] | None = None,
    clock: Callable[[], datetime] = _utc_now,
    sec_13f_factory: Callable[..., object] = SEC13FStructuredDatasetProvider,
    companies_house_factory: Callable[..., object] = CompaniesHouseProvider,
    deribit_factory: Callable[..., object] = DeribitPublicMarketProvider,
) -> GlobalPublicResearchMaintenanceReport:
    resolved = dict(os.environ if values is None else values)
    now = clock()
    root = Path(resolved.get("CAPITAL_INTELLIGENCE_DATA_DIR", "database")) / "global_public_research"
    lanes = (
        _sec_13f_lane(
            root,
            now=now,
            values=resolved,
            provider_factory=sec_13f_factory,
        ),
        _companies_house_lane(
            root,
            now=now,
            values=resolved,
            provider_factory=companies_house_factory,
        ),
        _deribit_lane(root, now=now, provider_factory=deribit_factory),
    )
    report = GlobalPublicResearchMaintenanceReport(evaluated_at=now, lanes=lanes)
    _write_json(root / "latest_report.json", report.to_dict())
    return report


__all__ = [
    "GlobalPublicResearchMaintenanceReport",
    "ResearchLaneResult",
    "maintain_global_public_research",
]
