"""Broad U.S.-equity discovery for the governed paper portfolio.

The discovery lane scans the authenticated Alpaca U.S.-equity master list,
intersects it with the official SEC ticker/exchange identity file, ranks the
complete eligible set from batched IEX snapshots, and deepens the strongest
names with point-in-time daily bars. Discovery can nominate candidates but has
no CIO, construction, execution, or real-money authority.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import pstdev
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from cio import CandidateAssetClass
from operations.free_paper_pilot import FreePaperPilotInstrument
from providers.alpaca_paper import AlpacaPaperClient, create_alpaca_paper_client
from providers.sec_edgar import SECEdgarProvider

_ALLOWED_EXCHANGES = frozenset({"NYSE", "NASDAQ", "AMEX", "ARCA", "BATS", "NYSEARCA"})
_US_EQUITY_DISCOVERY_TIMEZONE = ZoneInfo("America/New_York")
_FUND_NAME_MARKERS = (
    " ETF",
    " FUND",
    " PORTFOLIO",
    " INDEX",
    " ETN",
    " ACQUISITION CORP",
    " UNITS",
    " WARRANT",
)


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def us_equity_discovery_scheduled(as_of: datetime) -> bool:
    """Return whether fresh U.S.-equity discovery is scheduled at ``as_of``."""

    timestamp = _aware(as_of, field_name="as_of")
    return timestamp.astimezone(_US_EQUITY_DISCOVERY_TIMEZONE).weekday() < 5


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _clip(value: float, minimum: float = -1.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


def _period_return(closes: Sequence[float], periods: int) -> float:
    if len(closes) <= periods or closes[-periods - 1] <= 0.0:
        return 0.0
    return closes[-1] / closes[-periods - 1] - 1.0


@dataclass(frozen=True, slots=True)
class EquityDiscoveryPolicy:
    """Versioned broad-screen and decision-evidence resource policy."""

    version: str = "broad-us-equity-discovery.v3-bounded-decision-evidence"
    maximum_snapshot_assets: int | None = None
    snapshot_batch_size: int = 200
    # Every eligible symbol is snapshot-screened. The strongest 400 then receive
    # multi-horizon history, which is more than six times the default decision cohort.
    deep_shortlist_count: int | None = 400
    # Sixty-four new companies can represent 64% of NAV at the 1% exploratory cap;
    # strategic wrappers, current holdings, and the required cash reserve remain separate.
    selected_candidate_count: int | None = 64
    # Deep-history payloads are processed and released in bounded batches.
    deep_history_batch_size: int = 25
    minimum_price: float = 5.0
    minimum_daily_dollar_volume: float = 5_000_000.0
    minimum_history_bars: int = 252
    deep_history_days: int = 550
    exploratory_position_weight: float = 0.01
    scaled_position_weight: float = 0.05

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("version cannot be empty")
        for name in (
            "snapshot_batch_size",
            "deep_history_batch_size",
            "minimum_history_bars",
            "deep_history_days",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in (
            "maximum_snapshot_assets",
            "deep_shortlist_count",
            "selected_candidate_count",
        ):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise ValueError(f"{name} must be a positive integer or None")
        if (
            self.deep_shortlist_count is not None
            and self.selected_candidate_count is not None
            and self.deep_shortlist_count < self.selected_candidate_count
        ):
            raise ValueError("deep_shortlist_count must cover selected candidates")
        if not 0.0 < self.exploratory_position_weight <= self.scaled_position_weight <= 0.10:
            raise ValueError("equity discovery weights are invalid")
        if self.minimum_price <= 0.0 or self.minimum_daily_dollar_volume <= 0.0:
            raise ValueError("discovery price and liquidity floors must be positive")


@dataclass(frozen=True, slots=True)
class DiscoveredEquity:
    symbol: str
    name: str
    cik: str
    venue: str
    instrument_identifier: str
    score: float
    daily_return: float
    one_month_return: float
    three_month_return: float
    six_month_return: float
    twelve_month_return: float
    relative_strength: float
    annualized_volatility: float
    maximum_drawdown: float
    average_daily_dollar_volume: float
    current_price: float
    bar_count: int
    evidence_identifiers: tuple[str, ...]

    def instrument(
        self,
        *,
        currently_owned: bool,
        policy: EquityDiscoveryPolicy,
    ) -> FreePaperPilotInstrument:
        return FreePaperPilotInstrument(
            symbol=self.symbol,
            instrument_identifier=self.instrument_identifier,
            name=self.name,
            execution_asset_class=CandidateAssetClass.US_EQUITY,
            economic_exposure="us_equity",
            venue=self.venue,
            country_code="US",
            currency="USD",
            instrument_type="common_stock",
            maximum_weight=(
                policy.scaled_position_weight
                if currently_owned
                else policy.exploratory_position_weight
            ),
            issuer_cik=self.cik,
        )


@dataclass(frozen=True, slots=True)
class EquityDiscoveryResult:
    identifier: str
    as_of: datetime
    policy_version: str
    screened_asset_count: int
    snapshot_covered_count: int
    deep_shortlist_count: int
    selected: tuple[DiscoveredEquity, ...]
    observed_prices: tuple[tuple[str, float, str], ...]
    exclusions: tuple[tuple[str, str], ...]
    security_master_snapshot_identifier: str

    def instruments_for_holdings(
        self,
        held_symbols: Sequence[str],
        *,
        policy: EquityDiscoveryPolicy | None = None,
    ) -> tuple[FreePaperPilotInstrument, ...]:
        resolved = policy or EquityDiscoveryPolicy()
        held = {str(item).strip().upper() for item in held_symbols if str(item).strip()}
        return tuple(
            item.instrument(currently_owned=item.symbol in held, policy=resolved)
            for item in self.selected
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "as_of": self.as_of.isoformat(),
            "policy_version": self.policy_version,
            "screened_asset_count": self.screened_asset_count,
            "snapshot_covered_count": self.snapshot_covered_count,
            "deep_shortlist_count": self.deep_shortlist_count,
            "selected": [
                {
                    "symbol": item.symbol,
                    "name": item.name,
                    "cik": item.cik,
                    "venue": item.venue,
                    "instrument_identifier": item.instrument_identifier,
                    "score": item.score,
                    "daily_return": item.daily_return,
                    "one_month_return": item.one_month_return,
                    "three_month_return": item.three_month_return,
                    "six_month_return": item.six_month_return,
                    "twelve_month_return": item.twelve_month_return,
                    "relative_strength": item.relative_strength,
                    "annualized_volatility": item.annualized_volatility,
                    "maximum_drawdown": item.maximum_drawdown,
                    "average_daily_dollar_volume": item.average_daily_dollar_volume,
                    "current_price": item.current_price,
                    "bar_count": item.bar_count,
                    "evidence_identifiers": list(item.evidence_identifiers),
                }
                for item in self.selected
            ],
            "observed_prices": [
                {"symbol": symbol, "price": price, "source_identifier": source}
                for symbol, price, source in self.observed_prices
            ],
            "exclusions": [list(item) for item in self.exclusions],
            "security_master_snapshot_identifier": self.security_master_snapshot_identifier,
            "paper_only": True,
            "real_money_authorized": False,
        }


def _sec_equity_map(
    provider: SECEdgarProvider,
) -> tuple[dict[str, tuple[str, str, str, str]], str]:
    snapshot = provider.fetch_security_master()
    instruments = {item.instrument_id: item for item in snapshot.instruments}
    result: dict[str, tuple[str, str, str, str]] = {}
    for listing in snapshot.listings:
        instrument = instruments.get(listing.instrument_id)
        if instrument is None or instrument.issuer_id is None:
            continue
        prefix = "SEC:CIK:"
        if not instrument.issuer_id.startswith(prefix):
            continue
        cik = instrument.issuer_id[len(prefix) :]
        result[listing.symbol] = (
            cik,
            instrument.name,
            listing.venue,
            instrument.instrument_id,
        )
    identifier = f"sec-company-master:{snapshot.retrieved_at.isoformat()}"
    return result, identifier


def _eligible_assets(
    raw_assets: Sequence[Mapping[str, Any]],
    sec_map: Mapping[str, tuple[str, str, str, str]],
    *,
    excluded_symbols: set[str],
    maximum: int | None,
) -> tuple[dict[str, Mapping[str, Any]], tuple[tuple[str, str], ...]]:
    eligible: dict[str, Mapping[str, Any]] = {}
    excluded: list[tuple[str, str]] = []
    for asset in raw_assets:
        symbol = str(asset.get("symbol", "")).strip().upper()
        if not symbol or symbol in excluded_symbols:
            continue
        name = str(asset.get("name", "")).strip()
        exchange = str(asset.get("exchange", "")).strip().upper()
        reason: str | None = None
        if str(asset.get("status", "")).lower() != "active":
            reason = "inactive"
        elif asset.get("tradable") is not True:
            reason = "not_tradable"
        elif str(asset.get("class", "us_equity")).lower() not in {
            "us_equity",
            "equity",
        }:
            reason = "not_us_equity"
        elif exchange not in _ALLOWED_EXCHANGES:
            reason = "unsupported_exchange"
        elif symbol not in sec_map:
            reason = "missing_sec_company_identity"
        elif any(marker in f" {name.upper()}" for marker in _FUND_NAME_MARKERS):
            reason = "non_operating_company_name"
        if reason is not None:
            excluded.append((symbol, reason))
            continue
        eligible[symbol] = asset
        if maximum is not None and len(eligible) >= maximum:
            break
    return eligible, tuple(excluded)


def _snapshot_row(
    snapshot: Mapping[str, Any],
    *,
    as_of: datetime,
) -> tuple[float, float, float, str] | None:
    daily = snapshot.get("dailyBar")
    previous = snapshot.get("prevDailyBar")
    if not isinstance(daily, Mapping) or not isinstance(previous, Mapping):
        return None
    close = _number(daily.get("c"))
    prior_close = _number(previous.get("c"))
    volume = _number(daily.get("v"))
    observed = _timestamp(daily.get("t"))
    if (
        close is None
        or prior_close is None
        or volume is None
        or close <= 0.0
        or prior_close <= 0.0
        or volume < 0.0
        or observed is None
        or observed > as_of
    ):
        return None
    return close, close * volume, close / prior_close - 1.0, observed.isoformat()


def _bar_features(
    raw: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime,
    minimum_bars: int,
) -> tuple[list[float], list[float], datetime] | None:
    selected: dict[datetime, tuple[float, float]] = {}
    for item in raw:
        observed = _timestamp(item.get("t"))
        close = _number(item.get("c"))
        volume = _number(item.get("v"))
        if (
            observed is None
            or observed > as_of
            or close is None
            or close <= 0.0
            or volume is None
            or volume < 0.0
        ):
            continue
        selected[observed] = (close, volume)
    ordered = sorted(selected.items())
    if len(ordered) < minimum_bars:
        return None
    closes = [value[0] for _, value in ordered]
    volumes = [value[1] for _, value in ordered]
    return closes, volumes, ordered[-1][0]


def _deep_candidate(
    *,
    symbol: str,
    raw_bars: Sequence[Mapping[str, Any]],
    assets: Mapping[str, Mapping[str, Any]],
    sec_map: Mapping[str, tuple[str, str, str, str]],
    snapshot_rows: Mapping[str, tuple[float, float, float, str]],
    benchmark_return: float,
    timestamp: datetime,
    minimum_history_bars: int,
) -> tuple[DiscoveredEquity, tuple[str, float, str]] | None:
    features = _bar_features(
        raw_bars,
        as_of=timestamp,
        minimum_bars=minimum_history_bars,
    )
    if features is None:
        return None
    closes, volumes, latest = features
    daily = [
        closes[index] / closes[index - 1] - 1.0
        for index in range(1, len(closes))
        if closes[index - 1] > 0.0
    ]
    volatility = pstdev(daily[-252:]) * math.sqrt(252.0) if len(daily) >= 2 else 0.0
    peak = closes[0]
    drawdown = 0.0
    for close in closes:
        peak = max(peak, close)
        drawdown = min(drawdown, close / peak - 1.0)
    one = _period_return(closes, 21)
    three = _period_return(closes, 63)
    six = _period_return(closes, 126)
    twelve = _period_return(closes, 252)
    relative = twelve - benchmark_return
    momentum = 0.15 * one + 0.25 * three + 0.25 * six + 0.35 * twelve
    consistency = sum(value > 0.0 for value in (one, three, six, twelve)) / 4.0
    adv = sum(
        closes[index] * volumes[index]
        for index in range(max(0, len(closes) - 20), len(closes))
    ) / min(20, len(closes))
    snapshot = snapshot_rows.get(symbol)
    daily_return = 0.0 if snapshot is None else snapshot[2]
    liquidity = _clip((math.log10(max(adv, 1.0)) - 6.0) / 4.0, 0.0, 1.0)
    score = (
        0.30 * _clip(relative / 0.40, -1.0, 1.0)
        + 0.25 * _clip(momentum / 0.40, -1.0, 1.0)
        + 0.15 * _clip(daily_return / 0.10, -1.0, 1.0)
        + 0.15 * liquidity
        + 0.15 * consistency
        - 0.08 * _clip(volatility / 1.0, 0.0, 1.0)
        + 0.05 * _clip((drawdown + 0.60) / 0.60, 0.0, 1.0)
    )
    cik, name, venue, sec_instrument_id = sec_map[symbol]
    price_source = (
        f"alpaca-iex-discovery:{symbol}:{latest.isoformat()}:{len(closes)}"
    )
    candidate = DiscoveredEquity(
        symbol=symbol,
        name=name,
        cik=cik,
        venue=(str(assets[symbol].get("exchange", "")).strip().upper() or venue),
        instrument_identifier=f"instrument:us-equity:{symbol.lower()}",
        score=round(score, 8),
        daily_return=round(daily_return, 8),
        one_month_return=round(one, 8),
        three_month_return=round(three, 8),
        six_month_return=round(six, 8),
        twelve_month_return=round(twelve, 8),
        relative_strength=round(relative, 8),
        annualized_volatility=round(volatility, 8),
        maximum_drawdown=round(drawdown, 8),
        average_daily_dollar_volume=round(adv, 8),
        current_price=round(closes[-1], 8),
        bar_count=len(closes),
        evidence_identifiers=(
            price_source,
            f"sec-company-identity:{cik}:{symbol}:{sec_instrument_id}",
        ),
    )
    return candidate, (symbol, round(closes[-1], 8), price_source)


def discover_us_equities(
    *,
    as_of: datetime,
    held_symbols: Sequence[str] = (),
    tracked_symbols: Sequence[str] = (),
    excluded_symbols: Sequence[str] = (),
    client: AlpacaPaperClient | None = None,
    sec_provider: SECEdgarProvider | None = None,
    policy: EquityDiscoveryPolicy | None = None,
) -> EquityDiscoveryResult:
    """Screen the broad list and return the decision-evidence company cohort."""

    timestamp = _aware(as_of, field_name="as_of")
    resolved = policy or EquityDiscoveryPolicy()
    if not us_equity_discovery_scheduled(timestamp):
        local_date = timestamp.astimezone(_US_EQUITY_DISCOVERY_TIMEZONE).date()
        material = {
            "as_of": timestamp.isoformat(),
            "policy": resolved.version,
            "schedule": "weekend_market_closed",
        }
        digest = hashlib.sha256(
            json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return EquityDiscoveryResult(
            identifier=(
                f"equity-discovery:{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}:"
                f"{digest[:16]}"
            ),
            as_of=timestamp,
            policy_version=resolved.version,
            screened_asset_count=0,
            snapshot_covered_count=0,
            deep_shortlist_count=0,
            selected=(),
            observed_prices=(),
            exclusions=(("__lane__", "weekend_market_closed"),),
            security_master_snapshot_identifier=(
                f"schedule:us-equity:{local_date.isoformat()}:closed"
            ),
        )

    alpaca = client or create_alpaca_paper_client()
    sec = sec_provider or SECEdgarProvider()
    sec_map, sec_identifier = _sec_equity_map(sec)
    raw_assets = alpaca.assets(status="active", asset_class="us_equity")
    blocked = {
        str(item).strip().upper()
        for item in excluded_symbols
        if str(item).strip()
    }
    assets, structural_exclusions = _eligible_assets(
        raw_assets,
        sec_map,
        excluded_symbols=blocked,
        maximum=resolved.maximum_snapshot_assets,
    )
    exclusions = list(structural_exclusions)

    snapshot_rows: dict[str, tuple[float, float, float, str]] = {}
    symbols = tuple(sorted(assets))
    for start in range(0, len(symbols), resolved.snapshot_batch_size):
        batch = symbols[start : start + resolved.snapshot_batch_size]
        for symbol, snapshot in alpaca.snapshots(batch).items():
            row = _snapshot_row(snapshot, as_of=timestamp)
            if row is not None:
                snapshot_rows[symbol] = row

    preliminary: list[tuple[float, str]] = []
    for symbol, (price, dollar_volume, daily_return, _observed) in snapshot_rows.items():
        if (
            price < resolved.minimum_price
            or dollar_volume < resolved.minimum_daily_dollar_volume
        ):
            continue
        liquidity = _clip(
            (math.log10(max(dollar_volume, 1.0)) - 6.0) / 4.0,
            0.0,
            1.0,
        )
        gain = _clip(daily_return / 0.10, -1.0, 1.0)
        preliminary.append((0.65 * gain + 0.35 * liquidity, symbol))
    preliminary.sort(key=lambda item: (item[0], item[1]), reverse=True)

    held = {
        str(item).strip().upper() for item in held_symbols if str(item).strip()
    }
    tracked = {
        str(item).strip().upper() for item in tracked_symbols if str(item).strip()
    }
    protected = held | tracked
    ranked_symbols = [symbol for _score, symbol in preliminary]
    deep_limit = (
        len(ranked_symbols)
        if resolved.deep_shortlist_count is None
        else resolved.deep_shortlist_count
    )
    shortlist = ranked_symbols[:deep_limit]
    for symbol in sorted(protected):
        if symbol in assets and symbol not in shortlist:
            shortlist.append(symbol)
    deep_symbols = set(shortlist)
    for symbol in ranked_symbols:
        if symbol not in deep_symbols:
            exclusions.append((symbol, "outside_deep_evidence_cohort"))

    benchmark_payload = alpaca.historical_bars(
        ("VTI",),
        start=timestamp - timedelta(days=resolved.deep_history_days),
        end=timestamp,
        timeframe="1Day",
    )
    benchmark = _bar_features(
        benchmark_payload.get("VTI", ()),
        as_of=timestamp,
        minimum_bars=resolved.minimum_history_bars,
    )
    benchmark_return = (
        0.0 if benchmark is None else _period_return(benchmark[0], 252)
    )

    selected: list[DiscoveredEquity] = []
    observed_prices: list[tuple[str, float, str]] = []
    for start in range(0, len(shortlist), resolved.deep_history_batch_size):
        batch = tuple(shortlist[start : start + resolved.deep_history_batch_size])
        batch_bars = alpaca.historical_bars(
            batch,
            start=timestamp - timedelta(days=resolved.deep_history_days),
            end=timestamp,
            timeframe="1Day",
        )
        for symbol in batch:
            if symbol not in assets or symbol not in sec_map:
                continue
            result = _deep_candidate(
                symbol=symbol,
                raw_bars=batch_bars.get(symbol, ()),
                assets=assets,
                sec_map=sec_map,
                snapshot_rows=snapshot_rows,
                benchmark_return=benchmark_return,
                timestamp=timestamp,
                minimum_history_bars=resolved.minimum_history_bars,
            )
            if result is None:
                exclusions.append((symbol, "insufficient_deep_history"))
                continue
            candidate, observed = result
            selected.append(candidate)
            observed_prices.append(observed)
        del batch_bars

    selected.sort(
        key=lambda item: (
            item.score,
            item.relative_strength,
            item.average_daily_dollar_volume,
            item.symbol,
        ),
        reverse=True,
    )
    new_limit = (
        len(selected)
        if resolved.selected_candidate_count is None
        else resolved.selected_candidate_count
    )
    chosen_new = [item for item in selected if item.symbol not in protected][:new_limit]
    chosen_symbols = {item.symbol for item in chosen_new} | {
        item.symbol for item in selected if item.symbol in protected
    }
    selected_symbols = [
        item for item in selected if item.symbol in chosen_symbols
    ]
    for item in selected:
        if item.symbol not in chosen_symbols:
            exclusions.append((item.symbol, "outside_decision_evidence_cohort"))

    material = {
        "as_of": timestamp.isoformat(),
        "policy": resolved.version,
        "screened": len(assets),
        "snapshot_covered": len(snapshot_rows),
        "deep_symbols": shortlist,
        "selected": [(item.symbol, item.score) for item in selected_symbols],
        "protected": sorted(protected),
        "sec": sec_identifier,
    }
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return EquityDiscoveryResult(
        identifier=(
            f"equity-discovery:{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}:"
            f"{digest[:16]}"
        ),
        as_of=timestamp,
        policy_version=resolved.version,
        screened_asset_count=len(assets),
        snapshot_covered_count=len(snapshot_rows),
        deep_shortlist_count=len(shortlist),
        selected=tuple(selected_symbols),
        observed_prices=tuple(sorted(observed_prices)),
        exclusions=tuple(exclusions),
        security_master_snapshot_identifier=sec_identifier,
    )


__all__ = [
    "DiscoveredEquity",
    "EquityDiscoveryPolicy",
    "EquityDiscoveryResult",
    "discover_us_equities",
    "us_equity_discovery_scheduled",
]
