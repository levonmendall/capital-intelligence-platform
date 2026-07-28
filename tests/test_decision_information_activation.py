"""Append-only decision-information source activation tests."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from governance.decision_information_activation import (
    DecisionInformationActivationAuthority,
    DecisionInformationActivationError,
    DecisionInformationSourceActivation,
    SQLiteDecisionInformationActivationStore,
)
from governance.decision_information_readiness import (
    DecisionInformationDomain,
    load_maximum_decision_information_manifest,
)
from run_decision_information_activation import main

UTC = timezone.utc
EVALUATED_AT = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def _activation(source_identifier: str, domains) -> DecisionInformationSourceActivation:
    return DecisionInformationSourceActivation(
        identifier=f"activation:{source_identifier}:v1",
        source_identifier=source_identifier,
        source_name="Licensed governed source",
        enabled=True,
        approved_domains=tuple(domains),
        authoritative_domains=(),
        usage_rights_approved=True,
        storage_and_backup_approved=True,
        derived_analytics_approved=True,
        internal_display_approved=True,
        paper_simulation_approved=True,
        event_time_supported=True,
        publication_time_supported=True,
        availability_time_supported=True,
        correction_history_supported=True,
        historical_coverage_supported=True,
        provenance_complete=True,
        entity_mapping_supported=True,
        geographic_mapping_supported=True,
        reliability_policy_defined=True,
        manipulation_controls_defined=True,
        deduplication_supported=True,
        service_level_defined=True,
        certification_identifier=f"certification:{source_identifier}:v1",
        approved_by="authority:information-governance",
        rationale="Licensed, validated, reconciled, and certified for paper analysis.",
        approved_at=EVALUATED_AT - timedelta(days=1),
        effective_at=EVALUATED_AT - timedelta(hours=1),
        expires_at=EVALUATED_AT + timedelta(days=30),
        evidence_identifiers=(f"coverage:{source_identifier}:v1",),
    )


def test_activation_overlay_enables_declared_source_without_expanding_policy(
    tmp_path,
) -> None:
    manifest = load_maximum_decision_information_manifest(
        "config/maximum_decision_information_scope.json"
    )
    template = manifest.sources[0]
    activation = _activation(template.identifier, template.domains)
    store = SQLiteDecisionInformationActivationStore(tmp_path / "activation.db")
    assert store.append(activation) == 1
    assert store.append(activation) == 1

    overlay = DecisionInformationActivationAuthority(store).overlay(
        manifest, evaluated_at=EVALUATED_AT
    )
    source = next(
        item for item in overlay.manifest.sources
        if item.identifier == template.identifier
    )

    assert source.enabled is True
    assert source.certification_identifier == activation.certification_identifier
    assert overlay.activation_identifiers == (activation.identifier,)
    assert store.verify_integrity() is None

    unsupported = replace(
        activation,
        identifier="activation:unsupported:v1",
        approved_domains=(DecisionInformationDomain.ONCHAIN_CRYPTO_NETWORK,),
    )
    other = SQLiteDecisionInformationActivationStore(tmp_path / "unsupported.db")
    other.append(unsupported)
    with pytest.raises(DecisionInformationActivationError, match="undeclared"):
        DecisionInformationActivationAuthority(other).overlay(
            manifest, evaluated_at=EVALUATED_AT
        )


def test_activation_store_is_append_only_and_cli_operable(
    tmp_path, capsys
) -> None:
    manifest = load_maximum_decision_information_manifest(
        "config/maximum_decision_information_scope.json"
    )
    template = manifest.sources[0]
    activation = _activation(template.identifier, template.domains)
    path = tmp_path / "activation.json"
    path.write_text(json.dumps(activation.to_dict()), encoding="utf-8")
    database = tmp_path / "activation.db"

    assert main(
        ["--activation", str(path), "--database", str(database)]
    ) == 0
    appended = json.loads(capsys.readouterr().out)
    assert appended["registry_sequence"] == 1

    assert main(
        [
            "--status",
            "--database",
            str(database),
            "--evaluated-at",
            EVALUATED_AT.isoformat(),
        ]
    ) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["activation_count"] == 1
    assert status["activations"][0]["active"] is True

    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE decision_information_source_activations SET identifier = 'x'"
            )
