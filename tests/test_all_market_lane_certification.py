from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from cio import CandidateAssetClass
from operations.all_market_lane_certification import (
    AllMarketLaneCertificationError,
    checkpointed_market_probe,
    evaluate_lane_artifacts,
    publish_compositional_certification,
)


EPOCH = datetime(2026, 8, 13, 16, 30, tzinfo=timezone.utc)


def _values(tmp_path: Path, *, release: str = "release-a") -> dict[str, str]:
    return {
        "CAPITAL_INTELLIGENCE_DATA_DIR": str(tmp_path),
        "CAPITAL_INTELLIGENCE_RELEASE": release,
        "CAPITAL_INTELLIGENCE_COMPOSITIONAL_CERTIFICATION_ENABLED": "true",
    }


def _selected(symbol: str, *, observed_at: datetime = EPOCH):
    return SimpleNamespace(
        catalog=SimpleNamespace(symbol=symbol),
        features=SimpleNamespace(
            observed_at=observed_at,
            evidence_identifiers=(f"evidence:{symbol}",),
        ),
    )


def _lane(
    asset_class: CandidateAssetClass,
    *,
    catalog_count: int,
    selected=(),
    exclusions=(),
):
    return SimpleNamespace(
        asset_class=asset_class,
        scheduled=True,
        schedule_reason=None,
        catalog_count=catalog_count,
        deep_analyzed_count=len(selected),
        selected=tuple(selected),
        exclusions=tuple(exclusions),
        source_identifiers=(f"source:{asset_class.value}",),
        preselection_evidence=(
            (f"{asset_class.value}:screened", ("provider-factor:test",)),
        ),
    )


def _result(*lanes):
    return SimpleNamespace(
        as_of=EPOCH,
        policy_version="policy.v1",
        manifest_fingerprint="f" * 64,
        lanes=tuple(lanes),
    )


def test_common_epoch_lane_artifacts_certify_complete_universe(tmp_path: Path) -> None:
    result = _result(
        _lane(
            CandidateAssetClass.INTERNATIONAL_EQUITY,
            catalog_count=3,
            selected=(_selected("AAA"),),
            exclusions=(("BBB", "screening_rejection"), ("CCC", "screening_rejection")),
        ),
        _lane(
            CandidateAssetClass.FX,
            catalog_count=2,
            selected=(_selected("EURUSD"),),
            exclusions=(("USDJPY", "screening_rejection"),),
        ),
    )

    aggregate = publish_compositional_certification(
        result,
        values=_values(tmp_path),
    )

    assert aggregate is not None
    assert aggregate["all_market_runtime_certified"] is True
    assert aggregate["decision_epoch"] == EPOCH.isoformat()
    assert aggregate["candidate_count_limit_applied"] is False
    assert aggregate["required_lanes"] == ["international_equity", "fx"]
    assert aggregate["paper_only"] is True
    assert aggregate["investment_authority"] is False
    assert aggregate["real_money_authorized"] is False

    latest = json.loads(
        (tmp_path / "all-market-certification" / "latest.json").read_text(
            encoding="utf-8"
        )
    )
    assert latest["all_market_runtime_certified"] is True
    assert latest["decision_epoch"] == EPOCH.isoformat()

    certification_dir = (
        tmp_path
        / "all-market-certification"
        / "certifications"
        / aggregate["certification_id"]
    )
    artifact_path = next(
        path
        for path in (
            certification_dir / "lanes" / "international_equity"
        ).glob("*.json")
        if path.name != "current.json"
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["catalog_count"] == 3
    assert artifact["terminal_count"] == 3
    assert artifact["candidate_count_limit_applied"] is False
    assert artifact["evidence_effective_at"] == EPOCH.isoformat()
    assert artifact["completed_at"] != artifact["evidence_effective_at"]


def test_incomplete_terminal_accounting_fails_closed(tmp_path: Path) -> None:
    result = _result(
        _lane(
            CandidateAssetClass.FX,
            catalog_count=2,
            selected=(_selected("EURUSD"),),
            exclusions=(),
        )
    )

    with pytest.raises(
        AllMarketLaneCertificationError,
        match="terminal_accounting_mismatch",
    ):
        publish_compositional_certification(result, values=_values(tmp_path))

    latest = json.loads(
        (tmp_path / "all-market-certification" / "latest.json").read_text(
            encoding="utf-8"
        )
    )
    assert latest["all_market_runtime_certified"] is False


def test_future_observation_cannot_be_backdated_into_epoch(tmp_path: Path) -> None:
    result = _result(
        _lane(
            CandidateAssetClass.CRYPTO,
            catalog_count=1,
            selected=(
                _selected("BTCUSD", observed_at=EPOCH + timedelta(seconds=1)),
            ),
        )
    )

    with pytest.raises(
        AllMarketLaneCertificationError,
        match="point_in_time_invalid",
    ):
        publish_compositional_certification(result, values=_values(tmp_path))


def test_coordinator_rejects_mixed_epochs_and_release_artifacts() -> None:
    manifest = {
        "certification_id": "cert-1",
        "release_sha": "release-a",
        "decision_epoch": EPOCH.isoformat(),
        "required_lanes": ["fx"],
        "discovery_manifest_fingerprint": "f" * 64,
    }
    body = {
        "schema_version": "all-market-lane-certification.v1",
        "certification_id": "cert-1",
        "release_sha": "release-a",
        "lane": "fx",
        "decision_epoch": (EPOCH + timedelta(minutes=1)).isoformat(),
        "evidence_effective_at": (EPOCH + timedelta(minutes=1)).isoformat(),
        "completed_at": EPOCH.isoformat(),
        "policy_version": "policy.v1",
        "catalog_count": 1,
        "deep_analyzed_count": 1,
        "selected_count": 1,
        "excluded_count": 0,
        "terminal_count": 1,
        "terminal_accounting_complete": True,
        "point_in_time_valid": True,
        "freshness_valid": True,
        "universe_fingerprint": "u",
        "provider_evidence_fingerprint": "p",
        "discovery_manifest_fingerprint": "f" * 64,
        "candidate_count_limit_applied": False,
        "completion_status": "complete",
        "paper_only": True,
        "investment_authority": False,
        "real_money_authorized": False,
    }
    import hashlib
    encoded = json.dumps(
        body, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    artifact = {
        **body,
        "artifact_sha256": hashlib.sha256(encoded).hexdigest(),
    }

    result = evaluate_lane_artifacts(manifest, {"fx": artifact})

    assert result["all_market_runtime_certified"] is False
    assert "fx:decision_epoch_mismatch" in result["blocking_reasons"]
    assert "fx:evidence_effective_at_mismatch" in result["blocking_reasons"]


@dataclass(frozen=True)
class _Feature:
    observed_at: datetime
    price: float
    evidence_identifiers: tuple[str, ...]


def _record(symbol: str):
    return SimpleNamespace(
        symbol=symbol,
        provider_symbol=symbol,
        source_identifier=f"source:{symbol}",
        instrument_identifier=f"instrument:{symbol}",
        asset_class=CandidateAssetClass.FX,
        venue="TEST",
        expiration_at=None,
    )


def test_evidence_checkpoint_reuses_only_exact_release_epoch_and_record_set(
    tmp_path: Path,
) -> None:
    calls: list[datetime] = []

    def delegate(records, epoch, policy):
        del policy
        calls.append(epoch)
        return {
            record.symbol: _Feature(
                observed_at=epoch,
                price=1.0,
                evidence_identifiers=(f"evidence:{record.symbol}:{epoch.isoformat()}",),
            )
            for record in records
        }

    records = (_record("EURUSD"), _record("USDJPY"))
    values = _values(tmp_path)

    first = checkpointed_market_probe(
        delegate,
        _Feature,
        records,
        EPOCH,
        SimpleNamespace(version="policy.v1"),
        values=values,
    )
    second = checkpointed_market_probe(
        delegate,
        _Feature,
        records,
        EPOCH,
        SimpleNamespace(version="policy.v1"),
        values=values,
    )
    advanced = checkpointed_market_probe(
        delegate,
        _Feature,
        records,
        EPOCH + timedelta(minutes=5),
        SimpleNamespace(version="policy.v1"),
        values=values,
    )

    assert len(calls) == 2
    assert first == second
    assert advanced["EURUSD"].observed_at == EPOCH + timedelta(minutes=5)

    checkpoint = next(
        (
            tmp_path
            / "all-market-certification"
            / "evidence-checkpoints"
            / "fx"
        ).glob("*.json")
    )
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert payload["body"]["decision_epoch"] in {
        EPOCH.isoformat(),
        (EPOCH + timedelta(minutes=5)).isoformat(),
    }


def test_evidence_checkpoint_is_release_scoped(tmp_path: Path) -> None:
    calls = 0

    def delegate(records, epoch, policy):
        nonlocal calls
        del policy
        calls += 1
        return {
            record.symbol: _Feature(
                observed_at=epoch,
                price=1.0,
                evidence_identifiers=("evidence:test",),
            )
            for record in records
        }

    records = (_record("EURUSD"),)
    checkpointed_market_probe(
        delegate,
        _Feature,
        records,
        EPOCH,
        SimpleNamespace(version="policy.v1"),
        values=_values(tmp_path, release="release-a"),
    )
    checkpointed_market_probe(
        delegate,
        _Feature,
        records,
        EPOCH,
        SimpleNamespace(version="policy.v1"),
        values=_values(tmp_path, release="release-b"),
    )
    assert calls == 2


def test_checkpoint_tampering_fails_closed_instead_of_silently_refreshing(
    tmp_path: Path,
) -> None:
    def delegate(records, epoch, policy):
        del policy
        return {
            record.symbol: _Feature(
                observed_at=epoch,
                price=1.0,
                evidence_identifiers=("evidence:test",),
            )
            for record in records
        }

    records = (_record("EURUSD"),)
    values = _values(tmp_path)
    checkpointed_market_probe(
        delegate,
        _Feature,
        records,
        EPOCH,
        SimpleNamespace(version="policy.v1"),
        values=values,
    )
    checkpoint = next(
        (
            tmp_path
            / "all-market-certification"
            / "evidence-checkpoints"
            / "fx"
        ).glob("*.json")
    )
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    payload["body"]["features"]["EURUSD"]["price"] = 999.0
    checkpoint.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AllMarketLaneCertificationError, match="integrity failed"):
        checkpointed_market_probe(
            delegate,
            _Feature,
            records,
            EPOCH,
            SimpleNamespace(version="policy.v1"),
            values=values,
        )
