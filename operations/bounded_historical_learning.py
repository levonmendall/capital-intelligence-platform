"""Memory-bounded historical-learning manifest access for governed CIO cycles.

The canonical HistoricalLearningResolver owns all selection, calibration, and authority
semantics. This module changes only how its replay manifest is read: one top-level cutoff
is decoded at a time, only candidate-relevant decision fields are retained, and repeated
resolution of the same candidate in one bounded process reuses the immutable resulting
HistoricalLearningContext.

This module cannot create a candidate, change a specialist conclusion, increase expected
return or confidence, size capital, authorize execution, or enable real money.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cio.historical_learning as historical

_CHUNK_CHARS = 64 * 1024
_MAX_SINGLE_VALUE_CHARS = 32 * 1024 * 1024
_COMPACT_FIELDS = (
    "action",
    "decision_stage",
    "decision_horizon_days",
    "final_confidence",
    "recommended_position_weight",
    "realized_return_to_next_cutoff",
    "market_regime",
)
_ORIGINAL_RESOLVE = historical.HistoricalLearningResolver.resolve


class _ManifestNotObject(ValueError):
    pass


class _ManifestChangedDuringRead(RuntimeError):
    pass


class _IncrementalJSONReader:
    """Decode JSON values incrementally without retaining the complete document."""

    def __init__(self, path: Path) -> None:
        self._handle = path.open("r", encoding="utf-8")
        self._decoder = json.JSONDecoder()
        self._buffer = ""
        self._position = 0
        self._eof = False

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> "_IncrementalJSONReader":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _compact(self) -> None:
        if self._position:
            self._buffer = self._buffer[self._position :]
            self._position = 0

    def _fill(self, *, preserve_position: bool = False) -> bool:
        if self._eof:
            return False
        if not preserve_position and self._position:
            self._compact()
        chunk = self._handle.read(_CHUNK_CHARS)
        if not chunk:
            self._eof = True
            return False
        self._buffer += chunk
        return True

    def _skip_space(self) -> None:
        while True:
            while self._position < len(self._buffer) and self._buffer[self._position].isspace():
                self._position += 1
            if self._position < len(self._buffer) or not self._fill():
                return

    def peek(self) -> str | None:
        self._skip_space()
        while self._position >= len(self._buffer):
            if not self._fill():
                return None
            self._skip_space()
        return self._buffer[self._position]

    def expect(self, expected: str) -> None:
        actual = self.peek()
        if actual != expected:
            raise json.JSONDecodeError(
                f"expected {expected!r}", self._buffer, min(self._position, len(self._buffer))
            )
        self._position += 1

    def value(self) -> object:
        self._skip_space()
        start = self._position
        while True:
            try:
                value, end = self._decoder.raw_decode(self._buffer, self._position)
            except json.JSONDecodeError:
                if self._eof:
                    raise
                if start:
                    self._buffer = self._buffer[start:]
                    self._position -= start
                    start = 0
                if len(self._buffer) - start >= _MAX_SINGLE_VALUE_CHARS:
                    raise ValueError(
                        "historical replay JSON value exceeds the bounded parser limit"
                    )
                if not self._fill(preserve_position=True) and self._eof:
                    continue
            else:
                self._position = end
                return value


def _compact_item(raw_item: dict[str, Any], *, cutoff_macro_regime: object) -> dict[str, Any]:
    """Retain exactly the fields consumed by the canonical resolver."""

    symbol = historical._item_symbol(raw_item)
    asset_class = historical._item_asset_class(raw_item)
    compact: dict[str, Any] = {
        "symbol": symbol,
        "asset_class": asset_class.value,
    }
    for field in _COMPACT_FIELDS:
        if field in raw_item:
            compact[field] = raw_item[field]
    # Canonical semantics use the cutoff macro regime only when the item lacks the key.
    if "macro_regime" in raw_item:
        compact["macro_regime"] = raw_item["macro_regime"]
    elif cutoff_macro_regime is not None:
        compact["macro_regime"] = cutoff_macro_regime
    return compact


def _compact_decisions_array(
    reader: _IncrementalJSONReader,
    *,
    candidate: historical.CandidateDecisionRecord,
) -> list[dict[str, Any]]:
    target_symbol = candidate.instrument.symbol.upper()
    target_asset_class = candidate.instrument.asset_class
    compact_cutoffs: list[dict[str, Any]] = []
    reader.expect("[")
    if reader.peek() == "]":
        reader.expect("]")
        return compact_cutoffs
    while True:
        cutoff = reader.value()
        if isinstance(cutoff, dict) and cutoff.get("state") == "completed":
            raw_items = cutoff.get("decisions", [])
            if isinstance(raw_items, list):
                relevant: list[dict[str, Any]] = []
                for raw_item in raw_items:
                    if not isinstance(raw_item, dict):
                        continue
                    symbol = historical._item_symbol(raw_item)
                    asset_class = historical._item_asset_class(raw_item)
                    if symbol != target_symbol and asset_class is not target_asset_class:
                        continue
                    relevant.append(
                        _compact_item(
                            raw_item,
                            cutoff_macro_regime=cutoff.get("macro_regime"),
                        )
                    )
                if relevant:
                    compact_cutoffs.append(
                        {
                            "state": "completed",
                            "macro_regime": cutoff.get("macro_regime"),
                            "decisions": relevant,
                        }
                    )
        delimiter = reader.peek()
        if delimiter == ",":
            reader.expect(",")
            continue
        if delimiter == "]":
            reader.expect("]")
            return compact_cutoffs
        raise json.JSONDecodeError(
            "expected ',' or ']' in historical decisions array", "", 0
        )


def _compact_manifest(
    path: Path,
    *,
    candidate: historical.CandidateDecisionRecord,
) -> tuple[dict[str, Any], tuple[int, int]]:
    before = path.stat()
    metadata: dict[str, Any] = {}
    decisions: list[dict[str, Any]] = []
    with _IncrementalJSONReader(path) as reader:
        if reader.peek() != "{":
            raise _ManifestNotObject("historical replay manifest is not an object")
        reader.expect("{")
        if reader.peek() != "}":
            while True:
                key = reader.value()
                if not isinstance(key, str):
                    raise json.JSONDecodeError("historical manifest key is not a string", "", 0)
                reader.expect(":")
                if key == "decisions" and reader.peek() == "[":
                    decisions = _compact_decisions_array(reader, candidate=candidate)
                else:
                    value = reader.value()
                    if key in {"generated_at", "strict_only"}:
                        metadata[key] = value
                delimiter = reader.peek()
                if delimiter == ",":
                    reader.expect(",")
                    continue
                if delimiter == "}":
                    break
                raise json.JSONDecodeError(
                    "expected ',' or '}' in historical replay manifest", "", 0
                )
        reader.expect("}")
        if reader.peek() is not None:
            raise json.JSONDecodeError("extra data in historical replay manifest", "", 0)
    after = path.stat()
    before_signature = (before.st_mtime_ns, before.st_size)
    after_signature = (after.st_mtime_ns, after.st_size)
    if before_signature != after_signature:
        raise _ManifestChangedDuringRead(
            "historical replay manifest changed during bounded read"
        )
    metadata["decisions"] = decisions
    return metadata, after_signature


@dataclass(frozen=True, slots=True)
class _MemoryManifest:
    payload: str

    def read_text(self, *, encoding: str = "utf-8") -> str:
        if encoding.lower().replace("_", "-") != "utf-8":
            raise ValueError("bounded historical manifest supports UTF-8 only")
        return self.payload


def _cache_key(
    candidate: historical.CandidateDecisionRecord,
    *,
    as_of,
    macro_regime: str,
    market_regime: str,
    signature: tuple[int, int],
) -> tuple[object, ...]:
    return (
        signature,
        candidate.identifier,
        candidate.instrument.symbol.upper(),
        candidate.instrument.asset_class.value,
        candidate.decision_horizon_days,
        as_of.astimezone(historical.UTC).isoformat(),
        macro_regime.strip().lower(),
        market_regime.strip().lower(),
    )


def _bounded_resolve(
    self: historical.HistoricalLearningResolver,
    candidate: historical.CandidateDecisionRecord,
    *,
    as_of,
    macro_regime: str,
    market_regime: str,
) -> historical.HistoricalLearningContext:
    if not isinstance(candidate, historical.CandidateDecisionRecord):
        raise TypeError("candidate must be a CandidateDecisionRecord")
    historical._aware(as_of, field_name="as_of")
    macro_regime = historical._required_text(macro_regime, field_name="macro_regime")
    market_regime = historical._required_text(market_regime, field_name="market_regime")
    try:
        current = self.manifest_path.stat()
        current_signature = (current.st_mtime_ns, current.st_size)
    except OSError as error:
        return historical.HistoricalLearningContext.unavailable(
            candidate_identifier=candidate.identifier,
            as_of=as_of,
            reason=f"Governed historical learning is unavailable: {type(error).__name__}.",
        )

    cache_signature = getattr(self, "_bounded_manifest_signature", None)
    cache = getattr(self, "_bounded_context_cache", None)
    if cache_signature != current_signature or not isinstance(cache, dict):
        cache = {}
        self._bounded_manifest_signature = current_signature
        self._bounded_context_cache = cache
    key = _cache_key(
        candidate,
        as_of=as_of,
        macro_regime=macro_regime,
        market_regime=market_regime,
        signature=current_signature,
    )
    cached = cache.get(key)
    if isinstance(cached, historical.HistoricalLearningContext):
        return cached

    try:
        compact_payload, stable_signature = _compact_manifest(
            self.manifest_path,
            candidate=candidate,
        )
    except _ManifestNotObject:
        return historical.HistoricalLearningContext.unavailable(
            candidate_identifier=candidate.identifier,
            as_of=as_of,
            reason="Governed historical learning manifest is not an object.",
        )
    except _ManifestChangedDuringRead:
        return historical.HistoricalLearningContext.unavailable(
            candidate_identifier=candidate.identifier,
            as_of=as_of,
            reason="Governed historical learning changed during the decision read and was excluded.",
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return historical.HistoricalLearningContext.unavailable(
            candidate_identifier=candidate.identifier,
            as_of=as_of,
            reason=f"Governed historical learning is unavailable: {type(error).__name__}.",
        )

    if stable_signature != current_signature:
        # Do not reuse a point-in-time key if the file changed between the initial stat
        # and the stable bounded read. The next call may resolve the new immutable file.
        self._bounded_manifest_signature = stable_signature
        self._bounded_context_cache = {}
        return historical.HistoricalLearningContext.unavailable(
            candidate_identifier=candidate.identifier,
            as_of=as_of,
            reason="Governed historical learning changed before the decision read and was excluded.",
        )

    proxy = object.__new__(historical.HistoricalLearningResolver)
    proxy.manifest_path = _MemoryManifest(
        json.dumps(compact_payload, separators=(",", ":"), allow_nan=False)
    )
    proxy.minimum_sample_size = self.minimum_sample_size
    proxy.decision_stages = self.decision_stages
    context = _ORIGINAL_RESOLVE(
        proxy,
        candidate,
        as_of=as_of,
        macro_regime=macro_regime,
        market_regime=market_regime,
    )
    # A bounded manual diagnostic executes one canonical cycle. Keep only compact final
    # contexts, never the replay object graph, and cap defensive growth for test callers.
    if len(cache) >= 64:
        cache.clear()
    cache[key] = context
    return context


def install_bounded_historical_learning() -> None:
    """Install the bounded manifest reader idempotently for this process."""

    current = historical.HistoricalLearningResolver.resolve
    if current is _bounded_resolve:
        return
    if current is not _ORIGINAL_RESOLVE:
        raise RuntimeError("historical learning resolver has an unexpected implementation")
    historical.HistoricalLearningResolver.resolve = _bounded_resolve


__all__ = ["install_bounded_historical_learning"]
