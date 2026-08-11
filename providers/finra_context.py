"""FINRA TRACE aggregate context for the fixed-income specialist/environment path.

This module converts public FINRA Treasury aggregate activity into a canonical decision-
information record. It is explicitly market-structure/liquidity context and cannot
satisfy individual-security identity, pricing, history, valuation, or execution evidence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timezone
from typing import Any

import requests

from data.decision_information import (
    DecisionInformationRecord,
    InformationProvenance,
    InformationQualityState,
    InformationSourceType,
    PortfolioImpactChannel,
)
from providers.finra_fixed_income import (
    FINRA_FIXED_INCOME_BASE_URL,
    FINRA_TREASURY_DAILY_AGGREGATES,
    FinraFixedIncomeError,
    build_finra_fixed_income_provider,
)


class FinraContextError(RuntimeError):
    pass


def _number(value: object) -> float:
    if isinstance(value, bool) or value in (None, ""):
        return 0.0
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def collect_finra_fixed_income_context(
    *,
    as_of: datetime,
    http_get: Callable[..., Any] | None = None,
    limit: int = 250,
) -> DecisionInformationRecord | None:
    """Return latest-known TRACE Treasury aggregate context, or None if unconfigured."""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    provider = build_finra_fixed_income_provider()
    if provider is None:
        return None
    cutoff = as_of.astimezone(timezone.utc)
    token, _token_type, _expires = provider._access_token()  # noqa: SLF001 - same governed adapter contract
    getter = http_get or requests.get
    endpoint = f"{FINRA_FIXED_INCOME_BASE_URL}/{FINRA_TREASURY_DAILY_AGGREGATES}"
    try:
        response = getter(
            endpoint,
            params={
                "limit": max(1, min(int(limit), 1000)),
                "fields": (
                    "tradeDate,productCategory,yearsToMaturity,"
                    "dealerCustomerVolume,dealerCustomerCount,"
                    "atsInterdealerVolume,atsInterdealerCount"
                ),
            },
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            timeout=20,
        )
    except requests.RequestException as error:
        raise FinraContextError("FINRA fixed-income context request failed") from error
    status = int(getattr(response, "status_code", 0))
    if not 200 <= status < 300:
        raise FinraContextError(f"FINRA fixed-income context returned HTTP {status or 'unknown'}")
    try:
        payload = response.json()
    except (TypeError, ValueError) as error:
        raise FinraContextError("FINRA fixed-income context returned invalid JSON") from error
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        raise FinraContextError("FINRA fixed-income context response must be an array")

    dated: list[tuple[date, Mapping[str, object]]] = []
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        raw_date = str(item.get("tradeDate") or "").strip()
        try:
            trade_date = date.fromisoformat(raw_date[:10])
        except ValueError:
            continue
        if trade_date <= cutoff.date():
            dated.append((trade_date, item))
    if not dated:
        raise FinraContextError("FINRA returned no point-in-time Treasury aggregate context")
    latest_date = max(item[0] for item in dated)
    rows = tuple(item for trade_date, item in dated if trade_date == latest_date)
    dealer_volume = sum(_number(item.get("dealerCustomerVolume")) for item in rows)
    ats_volume = sum(_number(item.get("atsInterdealerVolume")) for item in rows)
    dealer_count = int(sum(_number(item.get("dealerCustomerCount")) for item in rows))
    ats_count = int(sum(_number(item.get("atsInterdealerCount")) for item in rows))
    categories = tuple(
        sorted(
            {
                str(item.get("productCategory") or "").strip()
                for item in rows
                if str(item.get("productCategory") or "").strip()
            }
        )
    )
    material = {
        "trade_date": latest_date.isoformat(),
        "dealer_customer_volume_metric": dealer_volume,
        "ats_interdealer_volume_metric": ats_volume,
        "dealer_customer_count": dealer_count,
        "ats_interdealer_count": ats_count,
        "aggregate_bucket_count": len(rows),
        "product_categories": categories,
    }
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    published = datetime.combine(latest_date, datetime.min.time(), tzinfo=timezone.utc) + __import__("datetime").timedelta(days=1)
    available = min(cutoff, max(published, datetime.combine(latest_date, datetime.min.time(), tzinfo=timezone.utc)))
    summary = (
        f"FINRA TRACE Treasury aggregate activity for {latest_date.isoformat()}: "
        f"dealer-customer volume metric={dealer_volume:.4f}, ATS interdealer volume metric={ats_volume:.4f}, "
        f"dealer-customer count={dealer_count}, ATS interdealer count={ats_count}, buckets={len(rows)}. "
        "This is aggregate market-structure/liquidity context only and is not an individual Treasury or bond price."
    )
    return DecisionInformationRecord(
        identifier=f"finra-context:treasury:{latest_date.isoformat()}:{digest[:16]}",
        topic="FINRA TRACE U.S. Treasury market activity",
        summary=summary,
        event_at=datetime.combine(latest_date, datetime.min.time(), tzinfo=timezone.utc),
        published_at=available,
        available_at=available,
        knowledge_cutoff=available,
        provenance=InformationProvenance(
            provider="FINRA",
            source_identifier=f"{FINRA_TREASURY_DAILY_AGGREGATES}:{latest_date.isoformat()}",
            source_type=InformationSourceType.REGULATORY,
            retrieved_at=cutoff,
            license_identifier="finra-fixed-income-data",
            usage_rights_identifier="finra-api-program-terms",
            raw_content_hash=digest,
            quality_state=InformationQualityState.LIVE,
            limitations=(
                "Aggregate TRACE Treasury activity only; not individual-security pricing.",
                "Cannot satisfy bond identity, valuation, market-history, liquidity-quote, or execution evidence.",
            ),
        ),
        canonical_event_identifier=f"event:finra:treasury-activity:{latest_date.isoformat()}",
        entities=("FINRA", "U.S. Treasury market"),
        instruments=(),
        geographies=("United States",),
        sectors=("Fixed Income",),
        tags=("fixed-income", "treasury", "trace", "market-structure", "aggregate-context-only"),
        impact_channels=(PortfolioImpactChannel.LIQUIDITY, PortfolioImpactChannel.DISCOUNT_RATE),
        reliability=0.95,
        relevance=0.85,
        materiality=0.65,
        independence=1.0,
    )


__all__ = ["FinraContextError", "collect_finra_fixed_income_context"]
