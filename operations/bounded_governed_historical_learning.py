"""Memory-bound the governed historical-learning wrapper in release diagnostics.

The canonical governed resolver remains the authority for calibration eligibility,
qualification/CIO separation, confidence ceilings, and position-size controls. This
module changes only its input representation inside the isolated manual CIO diagnostic:
the large learning manifest is streamed into a candidate-relevant compact temporary
manifest, then the unchanged governed resolver is executed against that compact input.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import cio.governed_historical_learning as governed
import cio.historical_learning as historical
from operations import bounded_historical_learning as bounded

_LEARNING_METADATA_FIELDS = frozenset(
    {
        "generated_at",
        "strict_only",
        "schema_version",
        "outcome_alignment",
        "macro_coverage_satisfied",
        "required_macro_datasets",
        "certification_ready",
        "governance_only_observation_count",
        "bounded_calibration_outcome_count",
        "macro_excluded_observation_count",
        "qualification_observation_count",
        "cio_decision_observation_count",
    }
)
_ORIGINAL_GOVERNED_RESOLVE = governed.HistoricalLearningResolver.resolve


def _compact_learning_manifest(
    path: Path,
    *,
    candidate: historical.CandidateDecisionRecord,
) -> tuple[dict[str, Any], tuple[int, int]]:
    """Stream one learning manifest while retaining only governed fields and comparables."""

    before = path.stat()
    metadata: dict[str, Any] = {}
    decisions: list[dict[str, Any]] = []
    with bounded._IncrementalJSONReader(path) as reader:
        if reader.peek() != "{":
            raise bounded._ManifestNotObject("historical learning manifest is not an object")
        reader.expect("{")
        if reader.peek() != "}":
            while True:
                key = reader.value()
                if not isinstance(key, str):
                    raise json.JSONDecodeError(
                        "historical learning manifest key is not a string", "", 0
                    )
                reader.expect(":")
                if key == "decisions" and reader.peek() == "[":
                    decisions = bounded._compact_decisions_array(
                        reader,
                        candidate=candidate,
                    )
                else:
                    value = reader.value()
                    if key in _LEARNING_METADATA_FIELDS:
                        metadata[key] = value
                delimiter = reader.peek()
                if delimiter == ",":
                    reader.expect(",")
                    continue
                if delimiter == "}":
                    break
                raise json.JSONDecodeError(
                    "expected ',' or '}' in historical learning manifest", "", 0
                )
        reader.expect("}")
        if reader.peek() is not None:
            raise json.JSONDecodeError("extra data in historical learning manifest", "", 0)
    after = path.stat()
    before_signature = (before.st_mtime_ns, before.st_size)
    after_signature = (after.st_mtime_ns, after.st_size)
    if before_signature != after_signature:
        raise bounded._ManifestChangedDuringRead(
            "historical learning manifest changed during bounded read"
        )
    metadata["decisions"] = decisions
    return metadata, after_signature


def _governed_cache_key(
    candidate: historical.CandidateDecisionRecord,
    *,
    as_of,
    macro_regime: str,
    market_regime: str,
    signature: tuple[int, int],
) -> tuple[object, ...]:
    return bounded._cache_key(
        candidate,
        as_of=as_of,
        macro_regime=macro_regime,
        market_regime=market_regime,
        signature=signature,
    )


def _unavailable(
    candidate: historical.CandidateDecisionRecord,
    *,
    as_of,
    reason: str,
) -> historical.HistoricalLearningContext:
    return historical.HistoricalLearningContext.unavailable(
        candidate_identifier=candidate.identifier,
        as_of=as_of,
        reason=reason,
    )


def _bounded_governed_resolve(
    self: governed.HistoricalLearningResolver,
    candidate: historical.CandidateDecisionRecord,
    *,
    as_of,
    macro_regime: str,
    market_regime: str,
) -> historical.HistoricalLearningContext:
    """Execute unchanged governed semantics against a compact temporary manifest."""

    if not isinstance(candidate, historical.CandidateDecisionRecord):
        raise TypeError("candidate must be a CandidateDecisionRecord")
    historical._aware(as_of, field_name="as_of")
    macro_regime = historical._required_text(macro_regime, field_name="macro_regime")
    market_regime = historical._required_text(market_regime, field_name="market_regime")
    try:
        current = self.manifest_path.stat()
        current_signature = (current.st_mtime_ns, current.st_size)
    except OSError:
        return _unavailable(
            candidate,
            as_of=as_of,
            reason=(
                "Calibration-safe historical learning is unavailable because the "
                "horizon-aligned learning manifest has not completed."
            ),
        )

    cache_signature = getattr(self, "_bounded_governed_manifest_signature", None)
    cache = getattr(self, "_bounded_governed_context_cache", None)
    if cache_signature != current_signature or not isinstance(cache, dict):
        cache = {}
        self._bounded_governed_manifest_signature = current_signature
        self._bounded_governed_context_cache = cache
    key = _governed_cache_key(
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
        compact_payload, stable_signature = _compact_learning_manifest(
            self.manifest_path,
            candidate=candidate,
        )
    except bounded._ManifestNotObject:
        return _unavailable(
            candidate,
            as_of=as_of,
            reason=(
                "Calibration-safe historical learning is unavailable because the "
                "horizon-aligned learning manifest has not completed."
            ),
        )
    except bounded._ManifestChangedDuringRead:
        return _unavailable(
            candidate,
            as_of=as_of,
            reason="Historical learning changed during the decision read and was excluded.",
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        return _unavailable(
            candidate,
            as_of=as_of,
            reason=f"Calibration-safe historical learning is unavailable: {type(error).__name__}.",
        )

    if stable_signature != current_signature:
        self._bounded_governed_manifest_signature = stable_signature
        self._bounded_governed_context_cache = {}
        return _unavailable(
            candidate,
            as_of=as_of,
            reason="Historical learning changed before the decision read and was excluded.",
        )

    compact_text = json.dumps(compact_payload, separators=(",", ":"), allow_nan=False)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            prefix="capital-intelligence-learning-",
            delete=False,
        ) as handle:
            handle.write(compact_text)
            temporary_path = Path(handle.name)

        proxy = object.__new__(governed.HistoricalLearningResolver)
        proxy.manifest_path = temporary_path
        proxy.minimum_sample_size = self.minimum_sample_size
        proxy.decision_stages = self.decision_stages
        context = _ORIGINAL_GOVERNED_RESOLVE(
            proxy,
            candidate,
            as_of=as_of,
            macro_regime=macro_regime,
            market_regime=market_regime,
        )
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass

    if len(cache) >= 64:
        cache.clear()
    cache[key] = context
    return context


def install_bounded_governed_historical_learning() -> None:
    """Install both base and governed bounded readers idempotently for this process."""

    bounded.install_bounded_historical_learning()
    current = governed.HistoricalLearningResolver.resolve
    if current is _bounded_governed_resolve:
        return
    if current is not _ORIGINAL_GOVERNED_RESOLVE:
        raise RuntimeError(
            "governed historical learning resolver has an unexpected implementation"
        )
    governed.HistoricalLearningResolver.resolve = _bounded_governed_resolve


__all__ = ["install_bounded_governed_historical_learning"]
