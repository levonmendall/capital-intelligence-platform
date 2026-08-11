"""Bound terminal all-market screening without changing admission semantics.

The canonical provider-factor publication is intentionally a complete JSON audit
artifact. Loading that artifact together with a complete certified catalog, baseline
signals, enriched signals, and a second validation mapping can create several complete
in-memory representations of a large market lane. This module keeps the publication
unchanged on disk but streams its signal members into a temporary SQLite spool, then
screens fixed-size catalog chunks through the existing provider-enriched validator.

Only compact fields required to reproduce the existing PreselectionPlan, cutoff
observations, provider-factor lineage, and deep-evidence nominations survive each
chunk. No market, factor, evidence, liquidity, freshness, ranking, or authority rule is
changed.
"""
from __future__ import annotations

import json
import re
import sqlite3
import tempfile
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from statistics import fmean
from typing import Mapping, Sequence

from operations.manual_cio_diagnostic import record_manual_cio_diagnostic_progress
from operations.market_discovery_preselection import (
    CandidateSleeve,
    CutoffObservation,
    PreselectionPlan,
    SLEEVES,
    _aware,
    _bucket,
    _tie,
)
from operations.provider_enriched_preselection import (
    PROVIDER_PRESELECTION_SCHEMA,
    provider_enriched_catalog_screening_signals,
    validate_provider_enriched_signals,
)


DEFAULT_TERMINAL_SCREENING_CHUNK_SIZE = 512
_TOP_LEVEL_KEY = re.compile(r'^  (?P<key>"(?:\\.|[^"\\])+"): (?P<value>.*)$')
_SIGNAL_KEY = re.compile(r'^    (?P<key>"(?:\\.|[^"\\])+"): (?P<value>\{.*)$')


class BoundedTerminalScreeningError(RuntimeError):
    """Raised when the canonical publication cannot be streamed safely."""


@dataclass(frozen=True, slots=True)
class BoundedTerminalPreselection:
    plan: PreselectionPlan
    nominated: tuple[object, ...]
    signal_prices: Mapping[str, float]
    signal_observed_at: Mapping[str, datetime]
    preselection_evidence: tuple[tuple[str, tuple[str, ...]], ...]
    provider_factor_authority_established: bool
    publication_failure_reasons: tuple[str, ...]
    screened_signal_count: int


class _PublicationSignalSpool:
    """Stream one canonical pretty-JSON publication into a disk-backed signal index."""

    def __init__(self, publication_path: Path) -> None:
        self.publication_path = publication_path
        self._temporary = tempfile.TemporaryDirectory(prefix="cio-terminal-screening-")
        self.database_path = Path(self._temporary.name) / "signals.sqlite3"
        self.connection = sqlite3.connect(self.database_path)
        self.connection.execute(
            "CREATE TABLE signals (symbol TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        self.metadata: dict[str, object] = {}
        self.signal_count = 0
        self._stream_publication()

    def close(self) -> None:
        try:
            self.connection.close()
        finally:
            self._temporary.cleanup()

    def __enter__(self) -> "_PublicationSignalSpool":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @staticmethod
    def _decode_value(text: str) -> tuple[object, int] | None:
        try:
            return json.JSONDecoder().raw_decode(text.lstrip())
        except json.JSONDecodeError:
            return None

    def _stream_publication(self) -> None:
        if not self.publication_path.exists():
            raise BoundedTerminalScreeningError(
                f"provider preselection publication is unavailable at {self.publication_path}"
            )
        mode = "top"
        pending_key: str | None = None
        pending_value = ""
        signal_symbol: str | None = None
        signal_value = ""
        saw_signals = False
        try:
            handle = self.publication_path.open("r", encoding="utf-8")
        except OSError as error:
            raise BoundedTerminalScreeningError(
                "provider preselection publication cannot be opened"
            ) from error
        with handle:
            for line in handle:
                if mode == "signals":
                    if signal_symbol is not None:
                        signal_value += line
                        decoded = self._decode_value(signal_value)
                        if decoded is not None:
                            value, _end = decoded
                            if not isinstance(value, Mapping):
                                raise BoundedTerminalScreeningError(
                                    "provider publication signal must be a JSON object"
                                )
                            self.connection.execute(
                                "INSERT INTO signals(symbol, payload) VALUES (?, ?)",
                                (
                                    signal_symbol,
                                    json.dumps(
                                        dict(value),
                                        sort_keys=True,
                                        separators=(",", ":"),
                                        allow_nan=False,
                                    ),
                                ),
                            )
                            self.signal_count += 1
                            signal_symbol = None
                            signal_value = ""
                        continue
                    if line.startswith("  }"):
                        mode = "top"
                        continue
                    match = _SIGNAL_KEY.match(line.rstrip("\n"))
                    if match is None:
                        if not line.strip():
                            continue
                        raise BoundedTerminalScreeningError(
                            "provider publication signals are not in canonical streamed form"
                        )
                    signal_symbol = str(json.loads(match.group("key"))).strip().upper()
                    if not signal_symbol:
                        raise BoundedTerminalScreeningError(
                            "provider publication contains an empty signal symbol"
                        )
                    signal_value = match.group("value") + "\n"
                    decoded = self._decode_value(signal_value)
                    if decoded is not None:
                        value, _end = decoded
                        if not isinstance(value, Mapping):
                            raise BoundedTerminalScreeningError(
                                "provider publication signal must be a JSON object"
                            )
                        self.connection.execute(
                            "INSERT INTO signals(symbol, payload) VALUES (?, ?)",
                            (
                                signal_symbol,
                                json.dumps(
                                    dict(value),
                                    sort_keys=True,
                                    separators=(",", ":"),
                                    allow_nan=False,
                                ),
                            ),
                        )
                        self.signal_count += 1
                        signal_symbol = None
                        signal_value = ""
                    continue

                if pending_key is not None:
                    pending_value += line
                    decoded = self._decode_value(pending_value)
                    if decoded is not None:
                        value, _end = decoded
                        self.metadata[pending_key] = value
                        pending_key = None
                        pending_value = ""
                    continue

                match = _TOP_LEVEL_KEY.match(line.rstrip("\n"))
                if match is None:
                    continue
                key = str(json.loads(match.group("key")))
                value_text = match.group("value") + "\n"
                if key == "signals":
                    if not value_text.lstrip().startswith("{"):
                        raise BoundedTerminalScreeningError(
                            "provider publication signals must be a JSON object"
                        )
                    mode = "signals"
                    saw_signals = True
                    continue
                decoded = self._decode_value(value_text)
                if decoded is not None:
                    value, _end = decoded
                    self.metadata[key] = value
                else:
                    pending_key = key
                    pending_value = value_text
        if mode == "signals" or signal_symbol is not None or pending_key is not None:
            raise BoundedTerminalScreeningError(
                "provider preselection publication ended before a JSON value completed"
            )
        if not saw_signals:
            raise BoundedTerminalScreeningError(
                "provider preselection publication does not contain signals"
            )
        if self.metadata.get("schema_version") != PROVIDER_PRESELECTION_SCHEMA:
            raise BoundedTerminalScreeningError(
                "unsupported provider preselection schema"
            )
        if "available_at" not in self.metadata:
            raise BoundedTerminalScreeningError(
                "provider preselection publication available_at is missing"
            )
        self.connection.commit()

    def signals_for(self, records: Sequence[object]) -> dict[str, object]:
        result: dict[str, object] = {}
        cursor = self.connection.cursor()
        for record in records:
            symbol = str(getattr(record, "symbol", "")).strip().upper()
            provider_symbol = str(
                getattr(record, "provider_symbol", symbol)
            ).strip().upper()
            row = cursor.execute(
                "SELECT payload FROM signals WHERE symbol = ?", (symbol,)
            ).fetchone()
            if row is None and provider_symbol and provider_symbol != symbol:
                row = cursor.execute(
                    "SELECT payload FROM signals WHERE symbol = ?", (provider_symbol,)
                ).fetchone()
            if row is None:
                continue
            result[symbol] = json.loads(str(row[0]))
        return result

    def chunk_publication(self, records: Sequence[object], target: Path) -> None:
        payload = {
            "schema_version": self.metadata["schema_version"],
            "available_at": self.metadata["available_at"],
            "source_identifiers": self.metadata.get("source_identifiers", ()),
            "signals": self.signals_for(records),
        }
        target.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )


def _chunks(values: Sequence[object], size: int):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def build_bounded_terminal_preselection(
    records: Sequence[object],
    *,
    as_of: datetime,
    policy: object,
    progress_label: str,
    chunk_size: int = DEFAULT_TERMINAL_SCREENING_CHUNK_SIZE,
) -> BoundedTerminalPreselection:
    """Reproduce complete-consideration preselection with a bounded signal working set."""

    timestamp = _aware(as_of)
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size < 1:
        raise ValueError("chunk_size must be a positive integer")
    publication_path = Path(str(getattr(policy, "provider_preselection_path"))).expanduser()
    eligible: list[object] = []
    exclusions: list[tuple[str, str]] = []
    score_maps: dict[CandidateSleeve, dict[str, float]] = {
        sleeve: {} for sleeve in SLEEVES
    }
    record_by_symbol: dict[str, object] = {}
    signal_prices: dict[str, float] = {}
    signal_observed_at: dict[str, datetime] = {}
    evidence_by_symbol: dict[str, tuple[str, ...]] = {}
    publication_failures: set[str] = set()
    substantive_provider_factor = False
    screened_signal_count = 0

    with _PublicationSignalSpool(publication_path) as spool:
        with tempfile.TemporaryDirectory(prefix="cio-terminal-chunks-") as temporary:
            chunk_path = Path(temporary) / "provider-preselection-chunk.json"
            processed = 0
            for chunk in _chunks(records, chunk_size):
                spool.chunk_publication(chunk, chunk_path)
                chunk_policy = replace(
                    policy,
                    provider_preselection_path=str(chunk_path),
                )
                signals = provider_enriched_catalog_screening_signals(
                    chunk,
                    timestamp,
                    chunk_policy,
                )
                if not isinstance(signals, Mapping):
                    raise BoundedTerminalScreeningError(
                        "provider-enriched screening chunk did not return a mapping"
                    )
                signals = validate_provider_enriched_signals(
                    chunk,
                    signals,
                    required_factors=getattr(
                        policy,
                        "required_provider_preselection_factors",
                    ),
                )
                normalized_signals = {
                    str(symbol).strip().upper(): signal
                    for symbol, signal in signals.items()
                }
                screened_signal_count += len(normalized_signals)
                for record in chunk:
                    symbol = str(getattr(record, "symbol", "")).strip().upper()
                    signal = normalized_signals.get(symbol)
                    if signal is None:
                        exclusions.append(
                            (symbol, "catalog_screening_signal_unavailable")
                        )
                        continue
                    if signal.indicative_price is not None:
                        signal_prices[symbol] = float(signal.indicative_price)
                    substantive_provider_factor = substantive_provider_factor or any(
                        identifier.startswith("provider-factor:")
                        for identifier in signal.evidence_identifiers
                    )
                    publication_failures.update(
                        reason
                        for reason in signal.exclusion_reasons
                        if reason.startswith(
                            "provider_enriched_preselection_publication_invalid:"
                        )
                    )
                    reasons = list(signal.exclusion_reasons)
                    age_seconds = (timestamp - signal.observed_at).total_seconds()
                    freshness_days = int(
                        getattr(policy, "preselection_freshness_days", 3)
                    )
                    if age_seconds < 0 or age_seconds > freshness_days * 86_400:
                        reasons.append("catalog_screening_signal_stale")
                    minimum_liquidity = float(
                        getattr(policy, "preselection_minimum_liquidity_score", 0.0)
                    )
                    if signal.liquidity_score is None:
                        reasons.append("catalog_basic_liquidity_unavailable")
                    elif signal.liquidity_score < minimum_liquidity:
                        reasons.append("catalog_basic_liquidity_failed")
                    if not signal.eligible:
                        reasons.append("catalog_ineligible")
                    if reasons:
                        exclusions.extend(
                            (symbol, reason) for reason in dict.fromkeys(reasons)
                        )
                        continue
                    eligible.append(record)
                    record_by_symbol[symbol] = record
                    signal_observed_at[symbol] = signal.observed_at
                    evidence_by_symbol[symbol] = tuple(signal.evidence_identifiers)
                    values = {
                        CandidateSleeve.QUALITY: signal.quality_score,
                        CandidateSleeve.VALUE: signal.value_score,
                        CandidateSleeve.MOMENTUM: signal.momentum_score,
                        CandidateSleeve.CARRY: signal.carry_score,
                        CandidateSleeve.IMPROVING_CONDITIONS: (
                            signal.improving_conditions_score
                        ),
                    }
                    for sleeve, value in values.items():
                        if value is not None:
                            score_maps[sleeve][symbol] = float(value)
                processed += len(chunk)
                record_manual_cio_diagnostic_progress(
                    f"terminal_screening_chunk:{progress_label}",
                    metrics={
                        "processed_records": processed,
                        "total_records": len(records),
                        "chunk_records": len(chunk),
                    },
                )
                del normalized_signals
                del signals

    authority_established = not records or substantive_provider_factor
    if not authority_established:
        detail = (
            "; " + ", ".join(sorted(publication_failures))
            if publication_failures
            else ""
        )
        raise BoundedTerminalScreeningError(
            f"{progress_label} provider factor authority is unavailable for the "
            f"complete certified catalog{detail}"
        )

    counts = Counter(_bucket(item) for item in eligible)
    for record in eligible:
        symbol = str(getattr(record, "symbol")).strip().upper()
        score_maps[CandidateSleeve.DIVERSIFICATION][symbol] = 1.0 / max(
            1, counts[_bucket(record)]
        )

    rankings = {
        sleeve: tuple(
            sorted(
                values,
                key=lambda symbol: (
                    values[symbol],
                    _tie(timestamp, sleeve, symbol),
                    symbol,
                ),
                reverse=True,
            )
        )
        for sleeve, values in score_maps.items()
    }
    capacity = max(1, len(records))
    selected: list[str] = []
    seen: set[str] = set()
    cursors = {sleeve: 0 for sleeve in SLEEVES}
    while len(selected) < min(capacity, len(eligible)):
        progressed = False
        for sleeve in SLEEVES:
            ranking = rankings[sleeve]
            index = cursors[sleeve]
            while index < len(ranking) and ranking[index] in seen:
                index += 1
            cursors[sleeve] = index + 1
            if index < len(ranking):
                symbol = ranking[index]
                selected.append(symbol)
                seen.add(symbol)
                progressed = True
                if len(selected) == capacity:
                    break
        if not progressed:
            break

    aggregate: list[tuple[float, float, str]] = []
    for record in eligible:
        symbol = str(getattr(record, "symbol")).strip().upper()
        known = [
            values[symbol] for values in score_maps.values() if symbol in values
        ]
        aggregate.append(
            (
                fmean(known) if known else 0.0,
                _tie(timestamp, CandidateSleeve.QUALITY, symbol),
                symbol,
            )
        )
    aggregate.sort(reverse=True)
    for _score, _tie_value, symbol in aggregate:
        if len(selected) >= capacity:
            break
        if symbol not in seen:
            selected.append(symbol)
            seen.add(symbol)
    shadow_limit = int(
        getattr(policy, "preselection_shadow_candidates_per_lane", 0)
    )
    shadow = tuple(
        symbol for _score, _tie_value, symbol in aggregate if symbol not in seen
    )[:shadow_limit]
    measured = tuple(selected) + shadow
    membership = tuple(
        (
            symbol,
            tuple(
                sleeve.value for sleeve in SLEEVES if symbol in score_maps[sleeve]
            ),
        )
        for symbol in measured
    )
    score_rows = tuple(
        (
            symbol,
            tuple(
                (sleeve.value, round(score_maps[sleeve][symbol], 10))
                for sleeve in SLEEVES
                if symbol in score_maps[sleeve]
            ),
        )
        for symbol in measured
    )
    plan = PreselectionPlan(
        catalog_count=len(records),
        eligible_count=len(eligible),
        capacity=capacity,
        selected_symbols=tuple(selected),
        shadow_symbols=shadow,
        sleeve_rankings=tuple(
            (sleeve.value, rankings[sleeve]) for sleeve in SLEEVES
        ),
        sleeve_membership=membership,
        scores=score_rows,
        factor_coverage=tuple(
            (sleeve.value, len(score_maps[sleeve])) for sleeve in SLEEVES
        ),
        exclusions=tuple(exclusions),
    )
    nominated = tuple(
        record_by_symbol[symbol]
        for symbol in plan.selected_symbols
        if symbol in record_by_symbol
    )
    preselection_evidence = tuple(
        (symbol, evidence_by_symbol[symbol])
        for symbol in measured
        if symbol in evidence_by_symbol
    )
    return BoundedTerminalPreselection(
        plan=plan,
        nominated=nominated,
        signal_prices=signal_prices,
        signal_observed_at=signal_observed_at,
        preselection_evidence=preselection_evidence,
        provider_factor_authority_established=authority_established,
        publication_failure_reasons=tuple(sorted(publication_failures)),
        screened_signal_count=screened_signal_count,
    )


def build_bounded_cutoff_observations(
    screening: BoundedTerminalPreselection,
    *,
    asset_class: str,
    selected_prices: Mapping[str, float],
) -> tuple[CutoffObservation, ...]:
    """Rebuild the existing cutoff observations from compact retained signal fields."""

    memberships = dict(screening.plan.sleeve_membership)
    score_map = dict(screening.plan.scores)
    result: list[CutoffObservation] = []
    for cohort, symbols in (
        ("selected", screening.plan.selected_symbols),
        ("below_cutoff", screening.plan.shadow_symbols),
    ):
        for symbol in symbols:
            observed_at = screening.signal_observed_at.get(symbol)
            price = selected_prices.get(symbol) or screening.signal_prices.get(symbol)
            if observed_at is None or price is None:
                continue
            values = [value for _name, value in score_map.get(symbol, ())]
            result.append(
                CutoffObservation(
                    asset_class=asset_class,
                    symbol=symbol,
                    cohort=cohort,
                    observed_at=observed_at,
                    price=float(price),
                    sleeves=memberships.get(symbol, ()),
                    preselection_score=round(
                        fmean(values) if values else 0.0,
                        10,
                    ),
                )
            )
    return tuple(result)


__all__ = [
    "BoundedTerminalPreselection",
    "BoundedTerminalScreeningError",
    "DEFAULT_TERMINAL_SCREENING_CHUNK_SIZE",
    "build_bounded_cutoff_observations",
    "build_bounded_terminal_preselection",
]
