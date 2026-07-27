from __future__ import annotations

from datetime import datetime, timedelta, timezone

from operations import (
    ResilienceExerciseOutcome,
    ResilienceExerciseStatus,
)


class PassingProvider:
    def execute(self, scenario):
        started = datetime(2026, 7, 27, 12, tzinfo=timezone.utc)
        injected = started + timedelta(seconds=1)
        return ResilienceExerciseOutcome(
            identifier=f"outcome:{scenario.identifier}",
            scenario_identifier=scenario.identifier,
            kind=scenario.kind,
            status=ResilienceExerciseStatus.PASSED,
            started_at=started,
            injected_at=injected,
            detected_at=injected + timedelta(seconds=10),
            recovered_at=injected + timedelta(seconds=20),
            reconciled_at=injected + timedelta(seconds=30),
            isolated_environment=True,
            production_mutation_count=0,
            before_fingerprint=f"fingerprint:{scenario.identifier}",
            after_fingerprint=f"fingerprint:{scenario.identifier}",
            verified_invariants=scenario.expected_invariants,
            detection_evidence_identifiers=(f"detect:{scenario.identifier}",),
            recovery_evidence_identifiers=(f"recover:{scenario.identifier}",),
            reconciliation_evidence_identifiers=(f"reconcile:{scenario.identifier}",),
        )


def build_passing_provider():
    return PassingProvider()
