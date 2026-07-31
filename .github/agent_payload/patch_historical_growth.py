from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected 1 match, found {count}: {old[:120]!r}")
    write(path, content.replace(old, new, 1))


replace_once(
    "cio/historical_learning.py",
    '''    limitations: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    subordinate_to_current_evidence: bool = True
''',
    '''    limitations: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    growth_calibration_multiplier: float = 1.0
    ensemble_calibration_authorized: bool = False
    subordinate_to_current_evidence: bool = True
''',
)
replace_once(
    "cio/historical_learning.py",
    '''        object.__setattr__(
            self,
            "median_realized_return",
''',
    '''        growth_multiplier = _finite(
            self.growth_calibration_multiplier,
            field_name="growth_calibration_multiplier",
            minimum=0.85,
            maximum=1.10,
        )
        object.__setattr__(self, "growth_calibration_multiplier", growth_multiplier)
        if not isinstance(self.ensemble_calibration_authorized, bool):
            raise TypeError("ensemble_calibration_authorized must be a bool")
        object.__setattr__(
            self,
            "median_realized_return",
''',
)
replace_once(
    "cio/historical_learning.py",
    '''            "confidence_ceiling": self.confidence_ceiling,
            "summary": self.summary,
''',
    '''            "confidence_ceiling": self.confidence_ceiling,
            "growth_calibration_multiplier": self.growth_calibration_multiplier,
            "ensemble_calibration_authorized": self.ensemble_calibration_authorized,
            "summary": self.summary,
''',
)
replace_once(
    "cio/historical_learning.py",
    '''    def validate_for(self, candidate_identifier: str, *, completed_at: datetime) -> None:
''',
    '''    @property
    def effective_position_multiplier(self) -> float:
        """Return bounded meta-allocation calibration without investment authority."""

        if not self.ensemble_calibration_authorized:
            return self.position_size_multiplier
        return round(
            min(
                1.10,
                self.position_size_multiplier * self.growth_calibration_multiplier,
            ),
            8,
        )

    def validate_for(self, candidate_identifier: str, *, completed_at: datetime) -> None:
''',
)
replace_once(
    "cio/historical_learning.py",
    '''        if limited:
            confidence_ceiling = min(confidence_ceiling, 0.70)
        limitations = [
''',
    '''        if limited:
            confidence_ceiling = min(confidence_ceiling, 0.70)
        calibration_authorized = (
            status is HistoricalLearningStatus.AVAILABLE
            and strict_replay
            and len(realized_values) >= self.minimum_sample_size
        )
        growth_calibration = 1.0
        if calibration_authorized:
            outcome_signal = (hit_rate - 0.50) * 0.12
            return_signal = max(-0.03, min(0.03, median_realized * 0.25))
            growth_calibration = min(
                1.10,
                max(0.90, 1.0 + outcome_signal + return_signal),
            )
        limitations = [
''',
)
replace_once(
    "cio/historical_learning.py",
    '''            f"Live size is capped at {size_multiplier:.1%} of the otherwise supported target "
            f"and confidence cannot exceed {confidence_ceiling:.1%}. Current evidence remains controlling."
''',
    '''            f"Live conservative size multiplier is {size_multiplier:.1%}; bounded ensemble "
            f"calibration is {growth_calibration:.1%}; confidence cannot exceed "
            f"{confidence_ceiling:.1%}. Current evidence remains controlling."
''',
)
replace_once(
    "cio/historical_learning.py",
    '''            confidence_ceiling=confidence_ceiling,
            summary=summary,
''',
    '''            confidence_ceiling=confidence_ceiling,
            growth_calibration_multiplier=round(growth_calibration, 8),
            ensemble_calibration_authorized=calibration_authorized,
            summary=summary,
''',
)
print("bounded symmetric historical calibration patched")
