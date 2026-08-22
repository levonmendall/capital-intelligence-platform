"""Durable, integrity-protected inputs for memory-isolated comprehensive discovery.

The all-market discovery owner must not keep the complete catalog, provider-preselection
publication, and every lane's deep records resident while a provider-facing lane runs.
This module freezes those inputs to local durable storage, then lets the coordinator load
only compact node descriptors.  Each lane child verifies and deserializes only its own
record blob; the provider-free finalizer loads the frozen catalog/publication only after
all required lanes have qualified.

The spool is operational evidence transport only.  It has no decision, candidate, sizing,
construction, execution, or real-money authority and cannot relax market membership,
evidence completeness/freshness, screening, or CIO governance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Mapping, Sequence

_SCHEMA = "comprehensive-discovery-input-spool.v1"
_REQUEST_SCHEMA = "comprehensive-discovery-input-spool-request.v1"
_FAILURE_SCHEMA = "comprehensive-discovery-input-spool-failure.v1"
_SAFE_RELEASE = re.compile(r"[^A-Za-z0-9_.-]+")
_SENSITIVE_MARKERS = (
    "API_KEY",
    "API_TOKEN",
    "ACCESS_TOKEN",
    "SECRET",
    "PASSWORD",
    "CREDENTIAL",
    "PRIVATE_KEY",
)


class ComprehensiveDiscoverySpoolError(RuntimeError):
    """Raised when a frozen comprehensive-discovery input is missing or invalid."""


@dataclass(frozen=True, slots=True)
class BlobDescriptor:
    relative_path: str
    sha256: str
    byte_count: int


@dataclass(frozen=True, slots=True)
class SpoolRequest:
    request_id: str
    path: Path
    release: str
    decision_epoch: datetime


@dataclass(frozen=True, slots=True)
class SpoolReference:
    """Lightweight finalizer reference retained by the coordinator instead of payloads."""

    manifest_path: str
    field: str


class _HashingWriter:
    def __init__(self, handle: BinaryIO) -> None:
        self.handle = handle
        self.digest = hashlib.sha256()
        self.byte_count = 0

    def write(self, payload: bytes) -> int:
        written = self.handle.write(payload)
        if written:
            chunk = payload[:written]
            self.digest.update(chunk)
            self.byte_count += written
        return written

    def flush(self) -> None:
        self.handle.flush()


def _drop_clean_file_cache(handle: BinaryIO) -> bool:
    """Best-effort eviction of clean scratch-file pages from the process cgroup.

    Render's cgroup raw-memory accounting includes reclaimable page cache.  The spool
    files are immutable scratch evidence after they are written or read, so retaining
    clean pages provides little reuse value while it can exhaust the raw hard ceiling.
    POSIX_FADV_DONTNEED is only an advisory optimization: unsupported platforms or file
    systems fall back to the prior behavior without changing discovery semantics.
    """

    fadvise = getattr(os, "posix_fadvise", None)
    dontneed = getattr(os, "POSIX_FADV_DONTNEED", None)
    if not callable(fadvise) or dontneed is None:
        return False
    try:
        fadvise(handle.fileno(), 0, 0, dontneed)
    except (OSError, ValueError):
        return False
    return True


def _flush_durable_and_drop_cache(handle: BinaryIO) -> None:
    """Commit scratch bytes before asking Linux to release their clean cache pages."""

    handle.flush()
    os.fsync(handle.fileno())
    _drop_clean_file_cache(handle)


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


def _safe_release(value: str) -> str:
    normalized = _SAFE_RELEASE.sub("-", str(value or "").strip()).strip("-.")
    return normalized or "unknown"


def _root(values: Mapping[str, str]) -> Path:
    data_dir = str(values.get("CAPITAL_INTELLIGENCE_DATA_DIR") or "").strip()
    if not data_dir:
        raise ComprehensiveDiscoverySpoolError(
            "CAPITAL_INTELLIGENCE_DATA_DIR is required for comprehensive discovery spool"
        )
    release = _release(values)
    if not release or release == "unknown":
        raise ComprehensiveDiscoverySpoolError(
            "exact release identity is required for comprehensive discovery spool"
        )
    return Path(data_dir).expanduser() / "comprehensive-discovery-spool" / _safe_release(release)


def _aware(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_timestamp(value: object, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise ComprehensiveDiscoverySpoolError(
            f"{field_name} is not a valid timestamp"
        ) from error
    return _aware(parsed, field_name=field_name)


def _atomic_json(path: Path, body: Mapping[str, object]) -> None:
    payload = {"body": dict(body), "sha256": _digest(body)}
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n"
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(encoded, encoding="utf-8")
    os.replace(temporary, path)


def _load_json(path: Path, *, schema: str) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ComprehensiveDiscoverySpoolError(
            f"comprehensive discovery spool artifact is unreadable: {path.name}"
        ) from error
    body = payload.get("body") if isinstance(payload, Mapping) else None
    if not isinstance(body, Mapping) or payload.get("sha256") != _digest(body):
        raise ComprehensiveDiscoverySpoolError(
            f"comprehensive discovery spool artifact integrity mismatch: {path.name}"
        )
    if body.get("schema_version") != schema:
        raise ComprehensiveDiscoverySpoolError(
            f"comprehensive discovery spool artifact schema mismatch: {path.name}"
        )
    if body.get("paper_only") is not True or body.get("real_money_authorized") is not False:
        raise ComprehensiveDiscoverySpoolError(
            "comprehensive discovery spool authority boundary is invalid"
        )
    for authority in (
        "decision_authority",
        "candidate_authority",
        "sizing_authority",
        "construction_authority",
        "execution_authority",
    ):
        if body.get(authority) is not False:
            raise ComprehensiveDiscoverySpoolError(
                "comprehensive discovery spool contains forbidden authority"
            )
    return body


def _authority_fields() -> dict[str, object]:
    return {
        "decision_authority": False,
        "candidate_authority": False,
        "sizing_authority": False,
        "construction_authority": False,
        "execution_authority": False,
        "paper_only": True,
        "real_money_authorized": False,
    }


def _descriptor_dict(descriptor: BlobDescriptor) -> dict[str, object]:
    return {
        "relative_path": descriptor.relative_path,
        "sha256": descriptor.sha256,
        "byte_count": descriptor.byte_count,
    }


def _descriptor(value: object) -> BlobDescriptor:
    if not isinstance(value, Mapping):
        raise ComprehensiveDiscoverySpoolError("spool blob descriptor is malformed")
    relative = str(value.get("relative_path") or "").strip()
    sha256 = str(value.get("sha256") or "").strip().lower()
    try:
        byte_count = int(value.get("byte_count", -1))
    except (TypeError, ValueError) as error:
        raise ComprehensiveDiscoverySpoolError("spool blob size is malformed") from error
    if (
        not relative
        or Path(relative).is_absolute()
        or ".." in Path(relative).parts
        or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
        or byte_count < 0
    ):
        raise ComprehensiveDiscoverySpoolError("spool blob descriptor is invalid")
    return BlobDescriptor(relative_path=relative, sha256=sha256, byte_count=byte_count)


def _write_bytes_blob(directory: Path, name: str, payload: bytes) -> BlobDescriptor:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    digest = hashlib.sha256(payload).hexdigest()
    if path.exists():
        descriptor = BlobDescriptor(name, digest, len(payload))
        _verify_blob(directory, descriptor)
        return descriptor
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("wb") as handle:
        handle.write(payload)
        _flush_durable_and_drop_cache(handle)
    os.replace(temporary, path)
    return BlobDescriptor(name, digest, len(payload))


def _write_pickle_blob(directory: Path, name: str, value: object) -> BlobDescriptor:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    if path.exists():
        path.unlink()
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("wb") as handle:
        writer = _HashingWriter(handle)
        pickle.dump(value, writer, protocol=pickle.HIGHEST_PROTOCOL)
        writer.flush()
        descriptor = BlobDescriptor(
            relative_path=name,
            sha256=writer.digest.hexdigest(),
            byte_count=writer.byte_count,
        )
        os.fsync(handle.fileno())
        _drop_clean_file_cache(handle)
    os.replace(temporary, path)
    return descriptor


def _verify_blob(directory: Path, descriptor: BlobDescriptor) -> Path:
    path = directory / descriptor.relative_path
    try:
        stat = path.stat()
    except OSError as error:
        raise ComprehensiveDiscoverySpoolError(
            f"spool blob is unavailable: {descriptor.relative_path}"
        ) from error
    if stat.st_size != descriptor.byte_count:
        raise ComprehensiveDiscoverySpoolError(
            f"spool blob size mismatch: {descriptor.relative_path}"
        )
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
            _drop_clean_file_cache(handle)
    except OSError as error:
        raise ComprehensiveDiscoverySpoolError(
            f"spool blob cannot be verified: {descriptor.relative_path}"
        ) from error
    if digest.hexdigest() != descriptor.sha256:
        raise ComprehensiveDiscoverySpoolError(
            f"spool blob integrity mismatch: {descriptor.relative_path}"
        )
    return path


def _load_pickle_blob(directory: Path, descriptor: BlobDescriptor) -> object:
    # Security/correctness invariant: verify the complete immutable byte stream before
    # pickle is allowed to instantiate anything from it.
    path = _verify_blob(directory, descriptor)
    try:
        with path.open("rb") as handle:
            try:
                return pickle.load(handle)
            finally:
                _drop_clean_file_cache(handle)
    except (OSError, pickle.PickleError, EOFError, AttributeError, ImportError, IndexError) as error:
        raise ComprehensiveDiscoverySpoolError(
            f"verified spool blob cannot be deserialized: {descriptor.relative_path}"
        ) from error


def prepare_request(
    *,
    values: Mapping[str, str],
    decision_epoch: datetime,
    held_symbols: Sequence[str],
    tracked_symbols: Sequence[str],
    excluded_symbols: Sequence[str],
    policy: object,
) -> SpoolRequest:
    epoch = _aware(decision_epoch, field_name="decision_epoch")
    release = _release(values)
    if not release or release == "unknown":
        raise ComprehensiveDiscoverySpoolError("exact release identity is required")
    policy_bytes = pickle.dumps(policy, protocol=pickle.HIGHEST_PROTOCOL)
    policy_sha = hashlib.sha256(policy_bytes).hexdigest()
    identity = {
        "schema_version": _REQUEST_SCHEMA,
        "release": release,
        "decision_epoch": epoch.isoformat(),
        "held_symbols": list(held_symbols),
        "tracked_symbols": list(tracked_symbols),
        "excluded_symbols": list(excluded_symbols),
        "policy_sha256": policy_sha,
    }
    request_id = _digest(identity)
    directory = _root(values) / epoch.strftime("%Y%m%dT%H%M%S%fZ") / request_id
    policy_descriptor = _write_bytes_blob(directory, "policy.pkl", policy_bytes)
    body: dict[str, object] = {
        **identity,
        "request_id": request_id,
        "policy_blob": _descriptor_dict(policy_descriptor),
        **_authority_fields(),
    }
    path = directory / "request.json"
    _atomic_json(path, body)
    return SpoolRequest(request_id=request_id, path=path, release=release, decision_epoch=epoch)


def load_request(path: str | Path) -> tuple[Mapping[str, object], object]:
    request_path = Path(path).expanduser()
    body = _load_json(request_path, schema=_REQUEST_SCHEMA)
    expected = _digest(
        {
            "schema_version": _REQUEST_SCHEMA,
            "release": body.get("release"),
            "decision_epoch": body.get("decision_epoch"),
            "held_symbols": body.get("held_symbols"),
            "tracked_symbols": body.get("tracked_symbols"),
            "excluded_symbols": body.get("excluded_symbols"),
            "policy_sha256": body.get("policy_sha256"),
        }
    )
    if str(body.get("request_id") or "") != expected:
        raise ComprehensiveDiscoverySpoolError("spool request identifier mismatch")
    policy_descriptor = _descriptor(body.get("policy_blob"))
    if policy_descriptor.sha256 != str(body.get("policy_sha256") or ""):
        raise ComprehensiveDiscoverySpoolError("spool request policy fingerprint mismatch")
    policy = _load_pickle_blob(request_path.parent, policy_descriptor)
    return body, policy


def _node_body(node: object, lane: BlobDescriptor) -> dict[str, object]:
    deadline = getattr(node, "deadline")
    return {
        "node_id": str(getattr(node, "node_id")),
        "asset_class": str(getattr(node, "asset_class")),
        "provider_groups": list(getattr(node, "provider_groups")),
        "input_fingerprint": str(getattr(node, "input_fingerprint")),
        "deadline": _aware(deadline, field_name="node_deadline").isoformat(),
        "decision_eligible_count": int(getattr(node, "decision_eligible_count")),
        "priority": int(getattr(node, "priority", 0)),
        "dependencies": list(getattr(node, "dependencies", ())),
        "lane_blob": _descriptor_dict(lane),
    }


def _safe_detail(error: BaseException, values: Mapping[str, str]) -> str:
    text = str(error).strip() or type(error).__name__
    secrets = {
        str(secret).strip()
        for name, secret in values.items()
        if any(marker in str(name).upper() for marker in _SENSITIVE_MARKERS)
        and len(str(secret).strip()) >= 4
    }
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return text[:1600]


def _write_failure(request_path: Path, *, stage: str, error: BaseException, values: Mapping[str, str]) -> None:
    body: dict[str, object] = {
        "schema_version": _FAILURE_SCHEMA,
        "request_id": request_path.parent.name,
        "failure_stage": stage,
        "error_type": type(error).__name__,
        "error_detail": _safe_detail(error, values),
        **_authority_fields(),
    }
    _atomic_json(request_path.parent / "failure.json", body)


def load_failure(request_path: str | Path) -> Mapping[str, object] | None:
    path = Path(request_path).expanduser().parent / "failure.json"
    if not path.exists():
        return None
    return _load_json(path, schema=_FAILURE_SCHEMA)


def _manifest_path(request_path: str | Path) -> Path:
    return Path(request_path).expanduser().parent / "manifest.json"


def load_manifest(path: str | Path) -> Mapping[str, object]:
    manifest_path = Path(path).expanduser()
    body = _load_json(manifest_path, schema=_SCHEMA)
    manifest_id = str(body.get("manifest_id") or "")
    material = dict(body)
    material.pop("manifest_id", None)
    if not manifest_id or manifest_id != _digest(material):
        raise ComprehensiveDiscoverySpoolError("comprehensive discovery spool manifest id mismatch")
    return body


def load_manifest_for_request(request_path: str | Path) -> tuple[Path, Mapping[str, object]]:
    request_body, _policy = load_request(request_path)
    manifest_path = _manifest_path(request_path)
    body = load_manifest(manifest_path)
    if body.get("request_id") != request_body.get("request_id"):
        raise ComprehensiveDiscoverySpoolError("spool manifest does not match request")
    if body.get("release") != request_body.get("release"):
        raise ComprehensiveDiscoverySpoolError("spool manifest release mismatch")
    if body.get("decision_epoch") != request_body.get("decision_epoch"):
        raise ComprehensiveDiscoverySpoolError("spool manifest epoch mismatch")
    return manifest_path, body


def manifest_available(request_path: str | Path) -> bool:
    try:
        load_manifest_for_request(request_path)
    except ComprehensiveDiscoverySpoolError:
        return False
    return True


def nodes_from_manifest(body: Mapping[str, object]):
    from operations import persistent_certification_scheduler as scheduler

    raw_nodes = body.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ComprehensiveDiscoverySpoolError("spool manifest has no certification nodes")
    nodes = []
    for raw in raw_nodes:
        if not isinstance(raw, Mapping):
            raise ComprehensiveDiscoverySpoolError("spool certification node is malformed")
        nodes.append(
            scheduler.CertificationNode(
                node_id=str(raw.get("node_id") or ""),
                asset_class=str(raw.get("asset_class") or ""),
                provider_groups=tuple(str(item) for item in raw.get("provider_groups", ())),
                input_fingerprint=str(raw.get("input_fingerprint") or ""),
                deadline=_parse_timestamp(raw.get("deadline"), field_name="node_deadline"),
                decision_eligible_count=int(raw.get("decision_eligible_count", 0)),
                priority=int(raw.get("priority", 0)),
                dependencies=tuple(str(item) for item in raw.get("dependencies", ())),
            )
        )
    if any(not node.node_id or not node.asset_class or not node.input_fingerprint for node in nodes):
        raise ComprehensiveDiscoverySpoolError("spool certification node identity is incomplete")
    return tuple(nodes)


def _manifest_directory(manifest_path: str | Path) -> Path:
    return Path(manifest_path).expanduser().parent


def load_lane_inputs(
    manifest_path: str | Path,
    *,
    node_id: str,
) -> tuple[Sequence[object], object, Mapping[str, object]]:
    body = load_manifest(manifest_path)
    raw_nodes = body.get("nodes")
    if not isinstance(raw_nodes, list):
        raise ComprehensiveDiscoverySpoolError("spool manifest node collection is malformed")
    selected = next(
        (
            item
            for item in raw_nodes
            if isinstance(item, Mapping) and str(item.get("node_id") or "") == node_id
        ),
        None,
    )
    if selected is None:
        raise ComprehensiveDiscoverySpoolError(f"spool has no lane inputs for {node_id}")
    directory = _manifest_directory(manifest_path)
    policy = _load_pickle_blob(directory, _descriptor(body.get("policy_blob")))
    records = _load_pickle_blob(directory, _descriptor(selected.get("lane_blob")))
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
        raise ComprehensiveDiscoverySpoolError(f"spool lane records are malformed for {node_id}")
    return records, policy, selected


def load_finalizer_inputs(manifest_path: str | Path) -> tuple[Mapping[object, object], object]:
    body = load_manifest(manifest_path)
    directory = _manifest_directory(manifest_path)
    raw_catalogs = _load_pickle_blob(directory, _descriptor(body.get("raw_catalogs_blob")))
    publication = _load_pickle_blob(directory, _descriptor(body.get("publication_blob")))
    if not isinstance(raw_catalogs, Mapping):
        raise ComprehensiveDiscoverySpoolError("spooled raw catalog is not a mapping")
    return raw_catalogs, publication


def build_spool(request_path: str | Path, *, values: Mapping[str, str] | None = None) -> Path:
    resolved_values = dict(os.environ if values is None else values)
    path = Path(request_path).expanduser()
    stage = "request_validation"
    try:
        request, policy = load_request(path)
        if request.get("release") != _release(resolved_values):
            raise ComprehensiveDiscoverySpoolError("spool builder release does not match runtime")
        if manifest_available(path):
            return _manifest_path(path)

        timestamp = _parse_timestamp(request.get("decision_epoch"), field_name="decision_epoch")
        held = tuple(str(item) for item in request.get("held_symbols", ()))
        tracked = tuple(str(item) for item in request.get("tracked_symbols", ()))
        excluded = tuple(str(item) for item in request.get("excluded_symbols", ()))

        # Import the canonical public facade only inside this disposable builder process so
        # every persistence/runtime hook used by production discovery is installed exactly
        # as it is for the evidence owner.
        stage = "catalog_assembly"
        from operations import comprehensive_market_discovery as facade
        from operations import authoritative_comprehensive_discovery as authoritative
        from operations import persistent_certification_scheduler as scheduler

        core = facade._core
        release_sha = scheduler._release(resolved_values)
        core.record_manual_cio_diagnostic_progress("certification_dag_catalog_dependency")
        raw_catalogs = core._base.default_catalog_probe(timestamp, policy=policy)
        catalogs = core._base._merge_certified_catalog(raw_catalogs, as_of=timestamp)
        if not isinstance(raw_catalogs, Mapping) or not isinstance(catalogs, Mapping):
            raise ComprehensiveDiscoverySpoolError("certification DAG catalog dependency is not a mapping")
        core.record_manual_cio_diagnostic_progress(
            "certification_dag_catalog_dependency_complete",
            metrics={
                "catalog_records": sum(
                    len(items) for items in catalogs.values() if isinstance(items, Sequence)
                )
            },
        )

        stage = "provider_preselection"
        core.record_manual_cio_diagnostic_progress("certification_dag_provider_factor_dependency")
        try:
            publication = core.ensure_provider_preselection_publication(
                catalogs,
                as_of=timestamp,
                policy=policy,
                market_probe=core.default_provider_preselection_market_probe,
            )
        except core.ProviderPreselectionPublicationError as error:
            raise ComprehensiveDiscoverySpoolError(str(error)) from error
        core.record_manual_cio_diagnostic_progress(
            "certification_dag_provider_factor_dependency_complete"
        )

        stage = "lane_descriptor_assembly"
        nodes, deep_records = scheduler._build_lane_nodes(
            core,
            catalogs=catalogs,
            timestamp=timestamp,
            resolved=policy,
            held_symbols=held,
            tracked_symbols=tracked,
            excluded_symbols=excluded,
            values=resolved_values,
        )
        if not nodes:
            raise ComprehensiveDiscoverySpoolError(
                "certification DAG found no scheduled comprehensive-discovery lanes"
            )
        del catalogs

        directory = path.parent
        raw_catalogs_descriptor = _write_pickle_blob(directory, "finalizer-raw-catalogs.pkl", raw_catalogs)
        del raw_catalogs
        publication_descriptor = _write_pickle_blob(directory, "finalizer-publication.pkl", publication)
        del publication

        policy_version = str(getattr(policy, "version", ""))
        rebound_count = 0
        node_bodies: list[dict[str, object]] = []
        stage = "lane_spooling"
        for index, node in enumerate(nodes):
            try:
                records = deep_records.pop(node.node_id)
            except KeyError as error:
                raise ComprehensiveDiscoverySpoolError(
                    f"certification DAG has no deep records for {node.node_id}"
                ) from error
            if authoritative._rebind_compatible_checkpoint(
                resolved_values,
                release_sha=release_sha,
                node=node,
                records=records,
                epoch=timestamp,
                policy_version=policy_version,
            ):
                rebound_count += 1
            lane_descriptor = _write_pickle_blob(
                directory,
                f"lane-{index:03d}-{_safe_release(node.node_id)}.pkl",
                tuple(records),
            )
            node_bodies.append(_node_body(node, lane_descriptor))
            del records
        deep_records.clear()
        del deep_records

        if rebound_count:
            core.record_manual_cio_diagnostic_progress(
                "certification_dag_compatibility_rebind",
                metrics={"rebound_nodes": rebound_count},
            )

        request_policy = _descriptor(request.get("policy_blob"))
        material: dict[str, object] = {
            "schema_version": _SCHEMA,
            "request_id": str(request.get("request_id") or ""),
            "release": release_sha,
            "decision_epoch": timestamp.isoformat(),
            "policy_version": policy_version,
            "policy_blob": _descriptor_dict(request_policy),
            "raw_catalogs_blob": _descriptor_dict(raw_catalogs_descriptor),
            "publication_blob": _descriptor_dict(publication_descriptor),
            "compatibility_rebound_count": rebound_count,
            "nodes": node_bodies,
            **_authority_fields(),
        }
        body = dict(material)
        body["manifest_id"] = _digest(material)
        manifest_path = _manifest_path(path)
        _atomic_json(manifest_path, body)
        try:
            (directory / "failure.json").unlink()
        except FileNotFoundError:
            pass
        return manifest_path
    except BaseException as error:  # noqa: BLE001 - builder must persist exact safe boundary.
        try:
            _write_failure(path, stage=stage, error=error, values=resolved_values)
        except BaseException:
            pass
        raise


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build",))
    parser.add_argument("--request", required=True)
    args = parser.parse_args(argv)
    try:
        path = build_spool(args.request)
    except BaseException as error:  # noqa: BLE001 - process boundary is intentionally fail-closed.
        print(
            json.dumps(
                {
                    "event": "comprehensive_discovery_input_spool_failed",
                    "error_type": type(error).__name__,
                    "credential_safe": True,
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 2
    print(
        json.dumps(
            {
                "event": "comprehensive_discovery_input_spool_ready",
                "manifest_path": str(path),
                "credential_safe": True,
                "paper_only": True,
                "real_money_authorized": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "BlobDescriptor",
    "ComprehensiveDiscoverySpoolError",
    "SpoolReference",
    "SpoolRequest",
    "build_spool",
    "load_failure",
    "load_finalizer_inputs",
    "load_lane_inputs",
    "load_manifest",
    "load_manifest_for_request",
    "manifest_available",
    "nodes_from_manifest",
    "prepare_request",
]
