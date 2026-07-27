"""Compatibility exports for the certified eligible-universe authority.

The authority lives in :mod:`governance.eligible_universe` so portfolio execution
can enforce it without importing the application orchestration package.
"""

from governance.eligible_universe import (
    CertifiedEligibleUniversePublication,
    EligibleUniverseCertificationState,
    EligibleUniverseError,
    SQLiteCertifiedEligibleUniverseStore,
)

__all__ = [
    "CertifiedEligibleUniversePublication",
    "EligibleUniverseCertificationState",
    "EligibleUniverseError",
    "SQLiteCertifiedEligibleUniverseStore",
]
