"""Scheduled paper launch and CIO pending-transaction reporting.

The report is descriptive only. It summarizes the exact canonical CIO construction and
never creates, changes, sizes, approves, or executes a transaction. Paper execution
remains governed by the existing eligibility, freshness, liquidity, cost, portfolio,
idempotency, and reconciliation controls.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo


DEFAULT_PAPER_TRADING_START_AT = datetime(
    2026,
    7,
    29,
    13,
    30,
    tzinfo=timezone.utc,
)
DEFAULT_REPORT_TIMEZONE = "America/Los_Angeles"


def _aware_timestamp(value: str, *, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def paper_trading_start_at() -> datetime:
    configured = os.getenv("CAPITAL_INTELLIGENCE_PAPER_TRADING_START_AT")
    if configured is None or not configured.strip():
        return DEFAULT_PAPER_TRADING_START_AT
    return _aware_timestamp(
        configured.strip(),
        field_name="CAPITAL_INTELLIGENCE_PAPER_TRADING_START_AT",
    )


def paper_trading_launch_open(now: datetime | None = None) -> bool:
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return timestamp.astimezone(timezone.utc) >= paper_trading_start_at()


def paper_trading_launch_label() -> str:
    timezone_name = os.getenv(
        "CAPITAL_INTELLIGENCE_PAPER_REPORT_TIMEZONE",
        DEFAULT_REPORT_TIMEZONE,
    ).strip()
    if not timezone_name:
        timezone_name = DEFAULT_REPORT_TIMEZONE
    try:
        zone = ZoneInfo(timezone_name)
    except Exception as error:
        raise ValueError(
            "CAPITAL_INTELLIGENCE_PAPER_REPORT_TIMEZONE must be a valid IANA timezone"
        ) from error
    local = paper_trading_start_at().astimezone(zone)
    return local.strftime("%A, %B %d, %Y at %-I:%M %p %Z")


def _data_dir() -> Path:
    return Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser()


def pending_report_directory() -> Path:
    configured = os.getenv("CAPITAL_INTELLIGENCE_CIO_REPORT_DIRECTORY")
    path = (
        Path(configured).expanduser()
        if configured and configured.strip()
        else _data_dir() / "cio_reports"
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def pending_report_paths() -> tuple[Path, Path]:
    directory = pending_report_directory()
    return (
        directory / "pending_transactions_latest.json",
        directory / "pending_transactions_latest.md",
    )


def _sequence(value: object) -> list[Any]:
    return list(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _transactions(construction: Mapping[str, Any] | None) -> list[dict[str, object]]:
    if not isinstance(construction, Mapping):
        return []
    target_weights = {
        str(item.get("symbol", "")).strip().upper(): _number(item.get("weight"))
        for item in _sequence(construction.get("target_weights"))
        if isinstance(item, Mapping) and str(item.get("symbol", "")).strip()
    }
    rows: list[dict[str, object]] = []
    for index, item in enumerate(_sequence(construction.get("trades")), start=1):
        if not isinstance(item, Mapping):
            continue
        symbol = str(item.get("symbol", "")).strip().upper()
        if not symbol:
            continue
        from_weight = _number(item.get("from_weight"))
        to_weight = _number(item.get("to_weight"))
        if to_weight is None:
            to_weight = target_weights.get(symbol)
        trade_weight = _number(item.get("trade_weight"))
        if trade_weight is None and from_weight is not None and to_weight is not None:
            trade_weight = to_weight - from_weight
        rows.append(
            {
                "sequence": index,
                "symbol": symbol,
                "side": str(item.get("side", "")).strip().lower() or "review",
                "from_weight": from_weight,
                "to_weight": to_weight,
                "trade_weight": trade_weight,
                "estimated_cost_return": _number(item.get("estimated_cost_return")),
                "reason": str(item.get("reason", "")).strip(),
                "funding_for": [
                    str(value)
                    for value in _sequence(item.get("funding_for"))
                    if str(value).strip()
                ],
                "status": "pending_execution",
            }
        )
    return rows


def build_pending_transaction_report(
    *,
    construction: Mapping[str, Any] | None,
    briefing: Mapping[str, Any] | None,
    generated_at: datetime | None = None,
    execution_state: str | None = None,
) -> dict[str, object]:
    timestamp = generated_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    timestamp = timestamp.astimezone(timezone.utc)
    launch_at = paper_trading_start_at()
    transactions = _transactions(construction)
    blocks = (
        [str(item) for item in _sequence(construction.get("blocks"))]
        if isinstance(construction, Mapping)
        else []
    )
    construction_status = (
        str(construction.get("status", "unavailable"))
        if isinstance(construction, Mapping)
        else "unavailable"
    )
    launch_state = "active" if timestamp >= launch_at else "scheduled"
    if transactions:
        report_state = "pending_transactions"
        summary = (
            f"The CIO has {len(transactions)} pending transaction recommendation"
            f"{'s' if len(transactions) != 1 else ''} for the COMPOUNDING portfolio."
        )
    elif isinstance(construction, Mapping):
        report_state = "no_transaction_recommended"
        summary = "The CIO construction currently recommends no portfolio transaction."
    else:
        report_state = "awaiting_cio_construction"
        summary = "No complete canonical CIO construction is available yet."

    resolved_execution_state = execution_state or (
        "scheduled" if launch_state == "scheduled" else "pending"
    )
    for transaction in transactions:
        transaction["status"] = (
            "executed"
            if resolved_execution_state == "completed"
            else "pending_execution"
        )

    return {
        "schema_version": "cio-pending-transactions.v1",
        "generated_at": timestamp.isoformat(),
        "portfolio_code": "COMPOUNDING",
        "report_state": report_state,
        "summary": summary,
        "paper_trading_start_at": launch_at.isoformat(),
        "paper_trading_start_label": paper_trading_launch_label(),
        "launch_state": launch_state,
        "execution_state": resolved_execution_state,
        "decision_identifier": (
            str(briefing.get("decision_identifier", "")).strip()
            if isinstance(briefing, Mapping)
            else ""
        ),
        "decision_as_of": (
            str(briefing.get("as_of", "")).strip()
            if isinstance(briefing, Mapping)
            else ""
        ),
        "construction_identifier": (
            str(construction.get("request_identifier", "")).strip()
            if isinstance(construction, Mapping)
            else ""
        ),
        "construction_status": construction_status,
        "transaction_count": len(transactions),
        "transactions": transactions,
        "target_cash_weight": (
            _number(construction.get("target_cash_weight"))
            if isinstance(construction, Mapping)
            else None
        ),
        "turnover": (
            _number(construction.get("turnover"))
            if isinstance(construction, Mapping)
            else None
        ),
        "estimated_cost_return": (
            _number(construction.get("estimated_cost_return"))
            if isinstance(construction, Mapping)
            else None
        ),
        "expected_return_improvement": (
            _number(construction.get("expected_return_improvement"))
            if isinstance(construction, Mapping)
            else None
        ),
        "blocks": blocks,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _percentage(value: object) -> str:
    number = _number(value)
    return "—" if number is None else f"{number:.2%}"


def pending_transaction_report_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# CIO Pending Transaction Recommendations",
        "",
        f"**Generated:** {report.get('generated_at', '—')}",
        f"**Portfolio:** {report.get('portfolio_code', 'COMPOUNDING')}",
        f"**Paper trading launch:** {report.get('paper_trading_start_label', '—')}",
        f"**Launch state:** {report.get('launch_state', '—')}",
        f"**Execution state:** {report.get('execution_state', '—')}",
        "",
        str(report.get("summary", "")),
        "",
        "## Portfolio construction",
        "",
        f"- Decision: `{report.get('decision_identifier') or 'unavailable'}`",
        f"- Construction: `{report.get('construction_identifier') or 'unavailable'}`",
        f"- Target cash: {_percentage(report.get('target_cash_weight'))}",
        f"- Turnover: {_percentage(report.get('turnover'))}",
        f"- Estimated implementation cost: {_percentage(report.get('estimated_cost_return'))}",
        f"- Expected return improvement: {_percentage(report.get('expected_return_improvement'))}",
        "",
        "## Pending recommendations",
        "",
    ]
    transactions = [
        item for item in _sequence(report.get("transactions")) if isinstance(item, Mapping)
    ]
    if transactions:
        lines.extend(
            [
                "| # | Symbol | Action | Current | Target | Change | Rationale | Status |",
                "|---:|---|---|---:|---:|---:|---|---|",
            ]
        )
        for item in transactions:
            rationale = str(item.get("reason", "")).replace("|", "\\|") or "—"
            lines.append(
                "| {sequence} | {symbol} | {side} | {from_weight} | {to_weight} | "
                "{trade_weight} | {reason} | {status} |".format(
                    sequence=item.get("sequence", ""),
                    symbol=item.get("symbol", ""),
                    side=str(item.get("side", "")).upper(),
                    from_weight=_percentage(item.get("from_weight")),
                    to_weight=_percentage(item.get("to_weight")),
                    trade_weight=_percentage(item.get("trade_weight")),
                    reason=rationale,
                    status=item.get("status", "pending_execution"),
                )
            )
    else:
        lines.append("No transaction is currently recommended.")
    blocks = [str(item) for item in _sequence(report.get("blocks"))]
    if blocks:
        lines.extend(["", "## Construction blocks", ""])
        lines.extend(f"- {item}" for item in blocks)
    lines.extend(
        [
            "",
            "---",
            "This is a paper-only implementation report. It does not authorize real money.",
            "",
        ]
    )
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def write_pending_transaction_report(
    report: Mapping[str, Any],
) -> tuple[Path, Path]:
    json_path, markdown_path = pending_report_paths()
    _atomic_write(
        json_path,
        json.dumps(dict(report), indent=2, sort_keys=True, allow_nan=False) + "\n",
    )
    _atomic_write(markdown_path, pending_transaction_report_markdown(report))
    return json_path, markdown_path


def publish_pending_transaction_report(
    *,
    construction: Mapping[str, Any] | None,
    briefing: Mapping[str, Any] | None,
    generated_at: datetime | None = None,
    execution_state: str | None = None,
) -> dict[str, object]:
    report = build_pending_transaction_report(
        construction=construction,
        briefing=briefing,
        generated_at=generated_at,
        execution_state=execution_state,
    )
    json_path, markdown_path = write_pending_transaction_report(report)
    return {
        **report,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }


__all__ = [
    "DEFAULT_PAPER_TRADING_START_AT",
    "build_pending_transaction_report",
    "paper_trading_launch_label",
    "paper_trading_launch_open",
    "paper_trading_start_at",
    "pending_report_directory",
    "pending_report_paths",
    "pending_transaction_report_markdown",
    "publish_pending_transaction_report",
    "write_pending_transaction_report",
]
