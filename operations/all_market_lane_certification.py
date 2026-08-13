"""Durable, fail-closed all-market lane certification and retry checkpoints.

This module adds operational composition around the existing comprehensive discovery
engine. It does not change catalog membership, screening, ranking, thresholds, CIO
authority, portfolio construction, execution, or paper-only controls.

A certification is bound to one exact release and one governed decision epoch. Lane
artifacts are immutable/content-addressed; a global aggregate is emitted only when
every scheduled lane is complete, terminally accounted, point-in-time valid, and bound
to the same release/epoch. Cached market evidence may be reused only for the exact
same epoch and exact record fingerprint.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence

from cio import CandidateAssetClass


_SCHEMA_VERSION = "all-market-lane-certification.v1"
_CACHE_SCHEMA_VERSION = "all-market-lane-checkpoint.v1"


class AllMarketLaneCertificationError(RuntimeError):
    """Raised when compositional all-market proof cannot be established."""


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("decision epoch must be timezone-aware")
    return value.astimezone(timezone.utc)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _release(values: Mapping[str, str]) -> str:
    return (
        values.get("CAPITAL_INTELLIGENCE_RELEASE")
        or values.get("RENDER_GIT_COMMIT")
        or values.get("GITHUB_SHA")
        or "unknown"
    ).strip()


def _enabled(values: Mapping[str, str]) -> bool:
    raw = values.get("CAPITAL_INTELLIGENCE_COMPOSITIONAL_CERTIFICATION_ENABLED")
    if raw is not None:
        normalized = raw.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(
            "CAPITAL_INTELLIGENCE_COMPOSITIONAL_CERTIFICATION_ENABLED is invalid"
        )
    comprehensive = (
        values.get("CAPITAL_INTELLIGENCE_REQUIRE_COMPREHENSIVE_DISCOVERY", "")
        .strip()
        .lower()
        in {"1", "true", "yes", "on"}
    )
    return (
        comprehensive
        and bool(values.get("CAPITAL_INTELLIGENCE_DATA_DIR"))
        and _release(values) != "unknown"
    )


def _root(values: Mapping[str, str]) -> Path:
    base = Path(
        values.get("CAPITAL_INTELLIGENCE_DATA_DIR")
        or "database"
    ).expanduser()
    return base / "all-market-certification"


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        payload,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(encoded, encoding="utf-8")
    os.replace(temporary, path)


def _immutable_json(path: Path, payload: Mapping[str, object]) -> None:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise AllMarketLaneCertificationError(
                f"immutable certification artifact collision at {path}"
            )
        return
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(encoded, encoding="utf-8")
    try:
        os.link(temporary, path)
    except FileExistsError:
        if path.read_text(encoding="utf-8") != encoded:
            raise AllMarketLaneCertificationError(
                f"immutable certification artifact collision at {path}"
            )
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _serialize(value: object) -> object:
    if isinstance(value, datetime):
        return _aware(value).isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: _serialize(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_serialize(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported checkpoint value: {type(value).__name__}")


def _record_fingerprint(records: Sequence[object]) -> str:
    material = []
    for record in records:
        material.append(
            {
                "symbol": str(getattr(record, "symbol", "")).strip().upper(),
                "provider_symbol": str(
                    getattr(record, "provider_symbol", "")
                ).strip().upper(),
                "source_identifier": str(
                    getattr(record, "source_identifier", "")
                ).strip(),
                "instrument_identifier": getattr(record, "instrument_identifier", None),
                "asset_class": getattr(
                    getattr(record, "asset_class", None), "value", None
                ),
                "venue": str(getattr(record, "venue", "")).strip().upper(),
                "expiration_at": _serialize(getattr(record, "expiration_at", None)),
            }
        )
    return _digest(material)


def _checkpoint_path(
    values: Mapping[str, str],
    *,
    release_sha: str,
    epoch: datetime,
    lane: str,
    record_fingerprint: str,
) -> Path:
    key = _digest(
        {
            "schema_version": _CACHE_SCHEMA_VERSION,
            "release_sha": release_sha,
            "decision_epoch": _aware(epoch).isoformat(),
            "lane": lane,
            "record_fingerprint": record_fingerprint,
        }
    )
    return _root(values) / "evidence-checkpoints" / lane / f"{key}.json"


def _feature_payload(feature: object) -> dict[str, object]:
    payload = _serialize(feature)
    if not isinstance(payload, dict):
        raise TypeError("market feature checkpoint must serialize to an object")
    return payload


def _restore_feature(feature_type, payload: Mapping[str, object]):
    restored = dict(payload)
    observed_at = restored.get("observed_at")
    if not isinstance(observed_at, str):
        raise AllMarketLaneCertificationError(
            "checkpoint market feature observed_at is invalid"
        )
    parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    restored["observed_at"] = _aware(parsed)
    identifiers = restored.get("evidence_identifiers", ())
    if not isinstance(identifiers, list):
        raise AllMarketLaneCertificationError(
            "checkpoint evidence_identifiers are invalid"
        )
    restored["evidence_identifiers"] = tuple(str(item) for item in identifiers)
    return feature_type(**restored)


def checkpointed_market_probe(
    delegate,
    feature_type,
    records: Sequence[object],
    epoch: datetime,
    policy: object,
    *,
    values: Mapping[str, str] | None = None,
):
    """Reuse provider evidence only for the exact release, epoch, lane, and record set."""

    resolved = os.environ if values is None else values
    if not _enabled(resolved) or not records:
        return delegate(records, epoch, policy)

    timestamp = _aware(epoch)
    release_sha = _release(resolved)
    lanes = {
        str(getattr(getattr(record, "asset_class", None), "value", "other"))
        for record in records
    }
    if len(lanes) != 1:
        raise AllMarketLaneCertificationError(
            "market-evidence checkpoint batch must contain exactly one lane"
        )
    lane = next(iter(lanes))
    fingerprint = _record_fingerprint(records)
    path = _checkpoint_path(
        resolved,
        release_sha=release_sha,
        epoch=timestamp,
        lane=lane,
        record_fingerprint=fingerprint,
    )

    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise AllMarketLaneCertificationError(
                f"cannot read evidence checkpoint for {lane}"
            ) from error
        body = payload.get("body")
        if not isinstance(body, Mapping) or payload.get("sha256") != _digest(body):
            raise AllMarketLaneCertificationError(
                f"evidence checkpoint integrity failed for {lane}"
            )
        expected = {
            "schema_version": _CACHE_SCHEMA_VERSION,
            "release_sha": release_sha,
            "decision_epoch": timestamp.isoformat(),
            "lane": lane,
            "record_fingerprint": fingerprint,
        }
        for key, expected_value in expected.items():
            if body.get(key) != expected_value:
                raise AllMarketLaneCertificationError(
                    f"evidence checkpoint {key} mismatch for {lane}"
                )
        raw_features = body.get("features")
        if not isinstance(raw_features, Mapping):
            raise AllMarketLaneCertificationError(
                f"evidence checkpoint features are invalid for {lane}"
            )
        expected_symbols = {
            str(getattr(record, "symbol", "")).strip().upper() for record in records
        }
        if not set(raw_features).issubset(expected_symbols):
            raise AllMarketLaneCertificationError(
                f"evidence checkpoint contains unexpected symbols for {lane}"
            )
        restored = {
            str(symbol): _restore_feature(feature_type, item)
            for symbol, item in raw_features.items()
            if isinstance(item, Mapping)
        }
        if len(restored) != len(raw_features):
            raise AllMarketLaneCertificationError(
                f"evidence checkpoint contains invalid feature rows for {lane}"
            )
        if any(_aware(item.observed_at) > timestamp for item in restored.values()):
            raise AllMarketLaneCertificationError(
                f"evidence checkpoint backdates future observations for {lane}"
            )
        return restored

    features = delegate(records, timestamp, policy)
    if not isinstance(features, Mapping):
        raise AllMarketLaneCertificationError(
            f"market probe returned a non-mapping for {lane}"
        )
    if any(_aware(item.observed_at) > timestamp for item in features.values()):
        raise AllMarketLaneCertificationError(
            f"market probe returned future observations for {lane}"
        )
    body = {
        "schema_version": _CACHE_SCHEMA_VERSION,
        "release_sha": release_sha,
        "decision_epoch": timestamp.isoformat(),
        "lane": lane,
        "record_fingerprint": fingerprint,
        "policy_version": str(getattr(policy, "version", "")),
        "features": {
            str(symbol): _feature_payload(item)
            for symbol, item in sorted(features.items())
        },
        "paper_only": True,
        "real_money_authorized": False,
    }
    _immutable_json(path, {"body": body, "sha256": _digest(body)})
    return features


def install_checkpointed_market_probe(core_module) -> None:
    """Install an exact-epoch evidence checkpoint without changing the probe seam."""

    if getattr(core_module, "_compositional_probe_installed", False):
        return
    delegate = core_module.default_redundant_market_probe
    feature_type = core_module._base._legacy.DiscoveryMarketFeatures

    def cached(records, epoch, policy):
        return checkpointed_market_probe(
            delegate,
            feature_type,
            records,
            epoch,
            policy,
        )

    core_module.default_redundant_market_probe = cached
    core_module._compositional_probe_installed = True


def _lane_evidence_fingerprint(lane: object) -> str:
    selected_evidence = []
    for item in getattr(lane, "selected", ()):
        selected_evidence.append(
            {
                "symbol": item.catalog.symbol,
                "observed_at": _aware(item.features.observed_at).isoformat(),
                "evidence_identifiers": list(item.features.evidence_identifiers),
            }
        )
    return _digest(
        {
            "preselection_evidence": _serialize(
                getattr(lane, "preselection_evidence", ())
            ),
            "selected_evidence": selected_evidence,
            "source_identifiers": list(getattr(lane, "source_identifiers", ())),
        }
    )


def _artifact_body(artifact: Mapping[str, object]) -> dict[str, object]:
    return {
        str(key): value
        for key, value in artifact.items()
        if key != "artifact_sha256"
    }


def _artifact_integrity_valid(artifact: Mapping[str, object]) -> bool:
    expected = artifact.get("artifact_sha256")
    return isinstance(expected, str) and expected == _digest(_artifact_body(artifact))


def evaluate_lane_artifacts(
    manifest: Mapping[str, object],
    artifacts: Mapping[str, Mapping[str, object]],
) -> Mapping[str, object]:
    """Validate the common release/epoch barrier without trusting producer ordering."""

    required_raw = manifest.get("required_lanes")
    if not isinstance(required_raw, list) or not required_raw:
        raise AllMarketLaneCertificationError(
            "required lane manifest must be unique and non-empty"
        )
    required_lanes = tuple(str(item) for item in required_raw)
    if len(set(required_lanes)) != len(required_lanes):
        raise AllMarketLaneCertificationError(
            "required lane manifest must be unique and non-empty"
        )
    certification_id = str(manifest.get("certification_id", ""))
    release_sha = str(manifest.get("release_sha", ""))
    decision_epoch = str(manifest.get("decision_epoch", ""))
    blocking: list[str] = []
    hashes: dict[str, str] = {}

    for lane in required_lanes:
        artifact = artifacts.get(lane)
        if not isinstance(artifact, Mapping):
            blocking.append(f"{lane}:missing")
            continue
        if not _artifact_integrity_valid(artifact):
            blocking.append(f"{lane}:integrity_invalid")
            continue
        hashes[lane] = str(artifact["artifact_sha256"])
        checks = {
            "certification_id": certification_id,
            "release_sha": release_sha,
            "decision_epoch": decision_epoch,
            "evidence_effective_at": decision_epoch,
            "lane": lane,
            "completion_status": "complete",
        }
        for key, expected in checks.items():
            if artifact.get(key) != expected:
                blocking.append(f"{lane}:{key}_mismatch")
        if artifact.get("candidate_count_limit_applied") is not False:
            blocking.append(f"{lane}:candidate_limit_applied")
        if artifact.get("terminal_accounting_complete") is not True:
            blocking.append(f"{lane}:terminal_accounting_incomplete")
        if artifact.get("point_in_time_valid") is not True:
            blocking.append(f"{lane}:point_in_time_invalid")
        if artifact.get("freshness_valid") is not True:
            blocking.append(f"{lane}:freshness_invalid")
        if (
            artifact.get("terminal_count") != artifact.get("catalog_count")
            or not isinstance(artifact.get("catalog_count"), int)
        ):
            blocking.append(f"{lane}:terminal_accounting_mismatch")

    unexpected = sorted(set(artifacts).difference(required_lanes))
    if unexpected:
        blocking.extend(f"{lane}:unexpected" for lane in unexpected)

    certified = not blocking and set(hashes) == set(required_lanes)
    return {
        "schema_version": _SCHEMA_VERSION,
        "certification_id": certification_id,
        "release_sha": release_sha,
        "decision_epoch": decision_epoch,
        "required_lanes": list(required_lanes),
        "lane_artifact_sha256": dict(sorted(hashes.items())),
        "discovery_manifest_fingerprint": manifest.get(
            "discovery_manifest_fingerprint"
        ),
        "all_market_runtime_certified": certified,
        "blocking_reasons": sorted(set(blocking)),
        "candidate_count_limit_applied": False,
        "paper_only": True,
        "investment_authority": False,
        "real_money_authorized": False,
    }


def _reuse_existing_artifact(
    current_path: Path,
    *,
    stable_fields: Mapping[str, object],
) -> Mapping[str, object] | None:
    if not current_path.exists():
        return None
    try:
        pointer = json.loads(current_path.read_text(encoding="utf-8"))
        artifact_name = pointer["artifact_path"]
        if not isinstance(artifact_name, str) or "/" in artifact_name:
            return None
        artifact_path = current_path.parent / artifact_name
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(artifact, Mapping) or not _artifact_integrity_valid(artifact):
        return None
    body = _artifact_body(artifact)
    for key, value in stable_fields.items():
        if body.get(key) != value:
            return None
    return artifact


def publish_compositional_certification(
    result: object,
    *,
    values: Mapping[str, str] | None = None,
) -> Mapping[str, object] | None:
    """Persist immutable lane proofs and a fail-closed common-epoch aggregate."""

    resolved = os.environ if values is None else values
    if not _enabled(resolved):
        return None

    release_sha = _release(resolved)
    epoch = _aware(getattr(result, "as_of"))
    policy_version = str(getattr(result, "policy_version"))
    result_fingerprint = str(getattr(result, "manifest_fingerprint"))
    lanes = tuple(getattr(result, "lanes"))
    required_lanes = tuple(
        lane.asset_class.value for lane in lanes if bool(lane.scheduled)
    )
    if not required_lanes or len(set(required_lanes)) != len(required_lanes):
        raise AllMarketLaneCertificationError(
            "required lane manifest must be unique and non-empty"
        )

    manifest_body = {
        "schema_version": _SCHEMA_VERSION,
        "release_sha": release_sha,
        "decision_epoch": epoch.isoformat(),
        "policy_version": policy_version,
        "required_lanes": list(required_lanes),
        "discovery_manifest_fingerprint": result_fingerprint,
        "candidate_count_limit_applied": False,
        "paper_only": True,
        "investment_authority": False,
        "real_money_authorized": False,
    }
    certification_id = _digest(manifest_body)
    certification_dir = _root(resolved) / "certifications" / certification_id
    manifest = {
        **manifest_body,
        "certification_id": certification_id,
        "sha256": _digest(manifest_body),
    }
    _immutable_json(certification_dir / "manifest.json", manifest)

    artifacts: dict[str, Mapping[str, object]] = {}
    for lane in lanes:
        if not lane.scheduled:
            continue
        lane_name = lane.asset_class.value
        selected_count = len(lane.selected)
        excluded_count = len(lane.exclusions)
        terminal_count = selected_count + excluded_count
        observations = tuple(
            _aware(item.features.observed_at) for item in lane.selected
        )
        point_in_time_valid = all(item <= epoch for item in observations)
        stable_fields = {
            "schema_version": _SCHEMA_VERSION,
            "certification_id": certification_id,
            "release_sha": release_sha,
            "lane": lane_name,
            "decision_epoch": epoch.isoformat(),
            "evidence_effective_at": epoch.isoformat(),
            "policy_version": policy_version,
            "catalog_count": int(lane.catalog_count),
            "deep_analyzed_count": int(lane.deep_analyzed_count),
            "selected_count": selected_count,
            "excluded_count": excluded_count,
            "terminal_count": terminal_count,
            "terminal_accounting_complete": terminal_count == lane.catalog_count,
            "point_in_time_valid": point_in_time_valid,
            "freshness_valid": point_in_time_valid,
            "universe_fingerprint": _digest(
                {
                    "asset_class": lane_name,
                    "catalog_count": lane.catalog_count,
                    "selected_symbols": [
                        item.catalog.symbol for item in lane.selected
                    ],
                    "exclusions": _serialize(lane.exclusions),
                    "source_identifiers": list(lane.source_identifiers),
                }
            ),
            "provider_evidence_fingerprint": _lane_evidence_fingerprint(lane),
            "discovery_manifest_fingerprint": result_fingerprint,
            "candidate_count_limit_applied": False,
            "completion_status": "complete",
            "paper_only": True,
            "investment_authority": False,
            "real_money_authorized": False,
        }
        current_path = certification_dir / "lanes" / lane_name / "current.json"
        existing = _reuse_existing_artifact(
            current_path,
            stable_fields=stable_fields,
        )
        if existing is not None:
            artifacts[lane_name] = existing
            continue

        body = {
            **stable_fields,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        artifact_hash = _digest(body)
        artifact = {**body, "artifact_sha256": artifact_hash}
        artifact_path = (
            certification_dir / "lanes" / lane_name / f"{artifact_hash}.json"
        )
        _immutable_json(artifact_path, artifact)
        _atomic_json(
            current_path,
            {
                "artifact_sha256": artifact_hash,
                "artifact_path": artifact_path.name,
                "decision_epoch": epoch.isoformat(),
                "release_sha": release_sha,
            },
        )
        artifacts[lane_name] = artifact

    aggregate_body = evaluate_lane_artifacts(manifest, artifacts)
    aggregate = {**aggregate_body, "sha256": _digest(aggregate_body)}
    _atomic_json(certification_dir / "aggregate.json", aggregate)
    _atomic_json(
        _root(resolved) / "latest.json",
        {
            "certification_id": certification_id,
            "release_sha": release_sha,
            "decision_epoch": epoch.isoformat(),
            "all_market_runtime_certified": aggregate[
                "all_market_runtime_certified"
            ],
            "aggregate_sha256": aggregate["sha256"],
        },
    )
    if not aggregate["all_market_runtime_certified"]:
        raise AllMarketLaneCertificationError(
            "all-market lane barrier failed closed: "
            + ", ".join(aggregate["blocking_reasons"])
        )
    return aggregate


__all__ = (
    "AllMarketLaneCertificationError",
    "checkpointed_market_probe",
    "evaluate_lane_artifacts",
    "install_checkpointed_market_probe",
    "publish_compositional_certification",
)
