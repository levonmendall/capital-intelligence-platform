"""Single versioned authority for governed decision thresholds.

The authority owns one DecisionPolicyMatrix instance and a deterministic fingerprint
of every base asset/horizon profile. Opportunity screening, robustness, CIO
qualification, persistence, sizing, replay, and evaluation must reference this same
authority instead of constructing independent matrices that may drift.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

from cio.models import CandidateAssetClass, CandidateDecisionRecord
from cio.policy_matrix import DecisionPolicyMatrix, DecisionPolicyProfile


@dataclass(frozen=True, slots=True)
class CanonicalDecisionPolicyAuthority:
    matrix: DecisionPolicyMatrix = DecisionPolicyMatrix()
    version: str = "canonical-decision-policy-authority.v1"

    def __post_init__(self) -> None:
        if not isinstance(self.matrix, DecisionPolicyMatrix):
            raise TypeError("matrix must be DecisionPolicyMatrix")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("version cannot be empty")

    def resolve(self, candidate: CandidateDecisionRecord) -> DecisionPolicyProfile:
        return self.matrix.resolve(candidate)

    @property
    def matrix_version(self) -> str:
        return self.matrix.version

    @property
    def fingerprint(self) -> str:
        payload = {
            "authority_version": self.version,
            "matrix_version": self.matrix.version,
            "profiles": self._profile_catalog(),
            "wrapper_exposures": {
                symbol: asset_class.value
                for symbol, asset_class in sorted(
                    self.matrix._CURRENT_WRAPPER_EXPOSURES.items()
                )
            },
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def identifier(self) -> str:
        return f"{self.version}:{self.matrix.version}:{self.fingerprint[:16]}"

    def assert_same_authority(
        self,
        other: "CanonicalDecisionPolicyAuthority",
    ) -> None:
        if not isinstance(other, CanonicalDecisionPolicyAuthority):
            raise TypeError("other must be CanonicalDecisionPolicyAuthority")
        if self.fingerprint != other.fingerprint:
            raise ValueError(
                "decision components reference different canonical policy authorities"
            )

    def _profile_catalog(self) -> dict[str, dict[str, object]]:
        values: dict[str, dict[str, object]] = {}
        for asset_class in CandidateAssetClass:
            base = self.matrix._profile_for(asset_class)
            for horizon in (30, 365, 366):
                profile = self.matrix._apply_horizon(base, horizon)
                values[f"{asset_class.value}:{horizon}"] = asdict(profile)
        exploratory = self.matrix._exploratory_equity_profile()
        for horizon in (30, 365, 366):
            values[f"exploratory_equity:{horizon}"] = asdict(
                self.matrix._apply_horizon(exploratory, horizon)
            )
        return values


__all__ = ["CanonicalDecisionPolicyAuthority"]
