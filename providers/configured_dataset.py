"""Provider-neutral JSON dataset connector for all governed market domains.

The connector is intentionally configuration driven.  It supplies the runtime
HTTP/file transport, bounded query rendering, environment-secret substitution,
JSON extraction, and point-in-time lineage required by ``ProviderDatasetProvider``.
Vendor-specific response semantics remain in an external binding document so a
new licensed provider can be activated without adding investment authority or
hard-coding credentials in source.
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from data.observation import AvailabilityBasis, DataQualityState
from data.provider_dataset import (
    ProviderDatasetError,
    ProviderDatasetQuery,
    ProviderDatasetSnapshot,
    ProviderDatasetType,
)

_ENV_PATTERN = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")


class ConfiguredDatasetProviderError(ProviderDatasetError):
    """Raised when a configured provider cannot be rendered or queried safely."""


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty")
    return normalized


def _mapping(value: object, *, field_name: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    return {
        _text(str(key), field_name=f"{field_name} key"): _text(
            str(item), field_name=f"{field_name} value"
        )
        for key, item in value.items()
    }


def _string_tuple(value: object, *, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field_name} must be an array")
    result = tuple(_text(str(item), field_name=field_name) for item in value)
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return result


def _expand(value: str, environment: Mapping[str, str]) -> str:
    missing: list[str] = []

    def replacement(match: re.Match[str]) -> str:
        name = match.group(1)
        current = str(environment.get(name, "")).strip()
        if not current:
            missing.append(name)
            return ""
        return current

    rendered = _ENV_PATTERN.sub(replacement, value)
    if missing:
        raise ConfiguredDatasetProviderError(
            "missing configured-provider environment variables: "
            + ", ".join(sorted(set(missing)))
        )
    return rendered


def _lookup(payload: object, path: str | None) -> object:
    if path is None or not path.strip():
        return payload
    current: object = payload
    for raw in path.split("."):
        segment = raw.strip()
        if not segment:
            raise ConfiguredDatasetProviderError("JSON path contains an empty segment")
        if isinstance(current, Mapping):
            if segment not in current:
                raise ConfiguredDatasetProviderError(
                    f"JSON path {path!r} is missing segment {segment!r}"
                )
            current = current[segment]
        elif isinstance(current, list) and segment.isdigit():
            index = int(segment)
            try:
                current = current[index]
            except IndexError as error:
                raise ConfiguredDatasetProviderError(
                    f"JSON path {path!r} index {index} is out of range"
                ) from error
        else:
            raise ConfiguredDatasetProviderError(
                f"JSON path {path!r} cannot traverse segment {segment!r}"
            )
    return current


def _timestamp(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ConfiguredDatasetProviderError(f"{field_name} must resolve to text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ConfiguredDatasetProviderError(
            f"{field_name} is not an ISO-8601 timestamp"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ConfiguredDatasetProviderError(
            f"{field_name} must include a UTC offset"
        )
    return parsed


@dataclass(frozen=True, slots=True)
class ConfiguredDatasetBinding:
    dataset_type: ProviderDatasetType
    path: str
    method: str = "GET"
    query_parameters: Mapping[str, str] | None = None
    headers: Mapping[str, str] | None = None
    json_body: Mapping[str, str] | None = None
    payload_path: str | None = None
    observed_at_path: str | None = None
    available_at_path: str | None = None
    provider_record_id_path: str | None = None
    quality_state: DataQualityState = DataQualityState.LIVE
    availability_basis: AvailabilityBasis = AvailabilityBasis.PROVIDER_TIMESTAMP
    limitations: tuple[str, ...] = ()
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not isinstance(self.dataset_type, ProviderDatasetType):
            raise TypeError("dataset_type must be ProviderDatasetType")
        object.__setattr__(self, "path", _text(self.path, field_name="path"))
        method = _text(self.method, field_name="method").upper()
        if method not in {"GET", "POST"}:
            raise ValueError("method must be GET or POST")
        object.__setattr__(self, "method", method)
        object.__setattr__(
            self,
            "query_parameters",
            _mapping(self.query_parameters, field_name="query_parameters"),
        )
        object.__setattr__(
            self,
            "headers",
            _mapping(self.headers, field_name="headers"),
        )
        object.__setattr__(
            self,
            "json_body",
            _mapping(self.json_body, field_name="json_body"),
        )
        for field_name in (
            "payload_path",
            "observed_at_path",
            "available_at_path",
            "provider_record_id_path",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self, field_name, _text(value, field_name=field_name)
                )
        if not isinstance(self.quality_state, DataQualityState):
            raise TypeError("quality_state must be DataQualityState")
        if not isinstance(self.availability_basis, AvailabilityBasis):
            raise TypeError("availability_basis must be AvailabilityBasis")
        object.__setattr__(
            self,
            "limitations",
            _string_tuple(self.limitations, field_name="limitations"),
        )
        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds, (int, float)
        ):
            raise TypeError("timeout_seconds must be numeric")
        timeout = float(self.timeout_seconds)
        if not 0.1 <= timeout <= 300.0:
            raise ValueError("timeout_seconds must be between 0.1 and 300")
        object.__setattr__(self, "timeout_seconds", timeout)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ConfiguredDatasetBinding":
        return cls(
            dataset_type=ProviderDatasetType(str(payload["dataset_type"])),
            path=str(payload["path"]),
            method=str(payload.get("method", "GET")),
            query_parameters=payload.get("query_parameters"),
            headers=payload.get("headers"),
            json_body=payload.get("json_body"),
            payload_path=(
                None if payload.get("payload_path") is None else str(payload["payload_path"])
            ),
            observed_at_path=(
                None
                if payload.get("observed_at_path") is None
                else str(payload["observed_at_path"])
            ),
            available_at_path=(
                None
                if payload.get("available_at_path") is None
                else str(payload["available_at_path"])
            ),
            provider_record_id_path=(
                None
                if payload.get("provider_record_id_path") is None
                else str(payload["provider_record_id_path"])
            ),
            quality_state=DataQualityState(str(payload.get("quality_state", "live"))),
            availability_basis=AvailabilityBasis(
                str(payload.get("availability_basis", "provider_timestamp"))
            ),
            limitations=tuple(str(item) for item in payload.get("limitations", ())),
            timeout_seconds=float(payload.get("timeout_seconds", 30.0)),
        )


@dataclass(frozen=True, slots=True)
class ConfiguredDatasetProviderSettings:
    provider_identifier: str
    source_version: str
    base_url: str
    bindings: tuple[ConfiguredDatasetBinding, ...]
    default_headers: Mapping[str, str] | None = None
    credential_environment_variables: tuple[str, ...] = ()
    allow_insecure_local: bool = False
    schema_version: str = "configured-dataset-provider.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "provider_identifier",
            "source_version",
            "base_url",
            "schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.bindings, tuple) or not self.bindings:
            raise ValueError("bindings must contain at least one binding")
        if not all(isinstance(item, ConfiguredDatasetBinding) for item in self.bindings):
            raise TypeError("bindings must contain ConfiguredDatasetBinding values")
        types = tuple(item.dataset_type for item in self.bindings)
        if len(types) != len(set(types)):
            raise ValueError("bindings cannot duplicate a dataset_type")
        object.__setattr__(
            self,
            "default_headers",
            _mapping(self.default_headers, field_name="default_headers"),
        )
        object.__setattr__(
            self,
            "credential_environment_variables",
            _string_tuple(
                self.credential_environment_variables,
                field_name="credential_environment_variables",
            ),
        )
        if not isinstance(self.allow_insecure_local, bool):
            raise TypeError("allow_insecure_local must be bool")
        parsed = urllib.parse.urlparse(self.base_url)
        local_http = parsed.scheme == "http" and parsed.hostname in {
            "localhost",
            "127.0.0.1",
            "::1",
        }
        if parsed.scheme not in {"https", "file"} and not (
            self.allow_insecure_local and local_http
        ):
            raise ValueError(
                "base_url must use HTTPS or file://; local HTTP requires allow_insecure_local"
            )

    @classmethod
    def from_dict(
        cls, payload: Mapping[str, Any]
    ) -> "ConfiguredDatasetProviderSettings":
        if payload.get("schema_version", "configured-dataset-provider.v1") != (
            "configured-dataset-provider.v1"
        ):
            raise ValueError("unsupported configured dataset provider schema")
        raw_bindings = payload.get("bindings")
        if not isinstance(raw_bindings, list):
            raise TypeError("bindings must be an array")
        return cls(
            provider_identifier=str(payload["provider_identifier"]),
            source_version=str(payload["source_version"]),
            base_url=str(payload["base_url"]),
            bindings=tuple(
                ConfiguredDatasetBinding.from_dict(item)
                for item in raw_bindings
                if isinstance(item, Mapping)
            ),
            default_headers=payload.get("default_headers"),
            credential_environment_variables=tuple(
                str(item)
                for item in payload.get("credential_environment_variables", ())
            ),
            allow_insecure_local=bool(payload.get("allow_insecure_local", False)),
            schema_version=str(
                payload.get("schema_version", "configured-dataset-provider.v1")
            ),
        )


@dataclass(frozen=True, slots=True)
class TransportResponse:
    status: int
    body: bytes
    headers: Mapping[str, str]


Transport = Callable[[urllib.request.Request, float], TransportResponse]


def _default_transport(
    request: urllib.request.Request, timeout_seconds: float
) -> TransportResponse:
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw_status = getattr(response, "status", None)
            return TransportResponse(
                status=200 if raw_status is None else int(raw_status),
                body=response.read(),
                headers=dict(response.headers.items()),
            )
    except Exception as error:  # network boundary normalized below
        raise ConfiguredDatasetProviderError(
            f"configured provider request failed: {error}"
        ) from error


class ConfiguredDatasetProvider:
    """Config-driven implementation of ``ProviderDatasetProvider``."""

    def __init__(
        self,
        settings: ConfiguredDatasetProviderSettings,
        *,
        environment: Mapping[str, str] | None = None,
        transport: Transport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(settings, ConfiguredDatasetProviderSettings):
            raise TypeError("settings must be ConfiguredDatasetProviderSettings")
        self.settings = settings
        self.environment = dict(os.environ if environment is None else environment)
        self.transport = transport or _default_transport
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._bindings = {item.dataset_type: item for item in settings.bindings}
        missing = tuple(
            name
            for name in settings.credential_environment_variables
            if not str(self.environment.get(name, "")).strip()
        )
        if missing:
            raise ConfiguredDatasetProviderError(
                "missing configured-provider credentials: " + ", ".join(missing)
            )

    @property
    def name(self) -> str:
        return self.settings.provider_identifier

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        *,
        environment: Mapping[str, str] | None = None,
        transport: Transport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> "ConfiguredDatasetProvider":
        source = Path(path).expanduser()
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ConfiguredDatasetProviderError(
                f"cannot load configured provider binding {str(source)!r}"
            ) from error
        if not isinstance(payload, Mapping):
            raise ConfiguredDatasetProviderError(
                "configured provider binding must be a JSON object"
            )
        return cls(
            ConfiguredDatasetProviderSettings.from_dict(payload),
            environment=environment,
            transport=transport,
            clock=clock,
        )

    def fetch_dataset(self, query: ProviderDatasetQuery) -> ProviderDatasetSnapshot:
        if not isinstance(query, ProviderDatasetQuery):
            raise TypeError("query must be ProviderDatasetQuery")
        binding = self._bindings.get(query.dataset_type)
        if binding is None:
            raise ConfiguredDatasetProviderError(
                f"provider {self.name} has no binding for {query.dataset_type.value}"
            )
        context = {
            "symbol": query.provider_symbol,
            "as_of": query.as_of.isoformat(),
            "start_at": "" if query.start_at is None else query.start_at.isoformat(),
            "end_at": "" if query.end_at is None else query.end_at.isoformat(),
            "limit": str(query.limit),
        }
        path = _expand(binding.path, self.environment).format_map(context)
        base = self.settings.base_url.rstrip("/") + "/"
        url = urllib.parse.urljoin(base, path.lstrip("/"))
        query_parameters = {
            key: _expand(value, self.environment).format_map(context)
            for key, value in dict(binding.query_parameters or {}).items()
        }
        if query_parameters:
            separator = "&" if urllib.parse.urlparse(url).query else "?"
            url += separator + urllib.parse.urlencode(query_parameters)
        headers = {
            key: _expand(value, self.environment).format_map(context)
            for key, value in {
                **dict(self.settings.default_headers or {}),
                **dict(binding.headers or {}),
            }.items()
        }
        body: bytes | None = None
        if binding.method == "POST":
            rendered_body = {
                key: _expand(value, self.environment).format_map(context)
                for key, value in dict(binding.json_body or {}).items()
            }
            body = json.dumps(
                rendered_body,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(
            url,
            data=body,
            method=binding.method,
            headers=headers,
        )
        response = self.transport(request, binding.timeout_seconds)
        if not isinstance(response, TransportResponse):
            raise TypeError("transport must return TransportResponse")
        if not 200 <= response.status < 300:
            raise ConfiguredDatasetProviderError(
                f"provider {self.name} returned HTTP {response.status}"
            )
        try:
            raw = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ConfiguredDatasetProviderError(
                f"provider {self.name} returned invalid JSON"
            ) from error
        payload = _lookup(raw, binding.payload_path)
        if not isinstance(payload, (dict, list)):
            raise ConfiguredDatasetProviderError(
                "configured payload_path must resolve to an object or array"
            )
        retrieved_at = self.clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ConfiguredDatasetProviderError("configured provider clock must be aware")
        observed_at = (
            query.end_at or query.as_of
            if binding.observed_at_path is None
            else _timestamp(
                _lookup(raw, binding.observed_at_path),
                field_name="observed_at_path",
            )
        )
        available_at = (
            query.as_of
            if binding.available_at_path is None
            else _timestamp(
                _lookup(raw, binding.available_at_path),
                field_name="available_at_path",
            )
        )
        if observed_at > query.as_of or available_at > query.as_of:
            raise ConfiguredDatasetProviderError(
                "provider response contains information unavailable at query as_of"
            )
        provider_record_id = None
        if binding.provider_record_id_path is not None:
            provider_record_id = str(
                _lookup(raw, binding.provider_record_id_path)
            ).strip() or None
        return ProviderDatasetSnapshot(
            query=query,
            provider=self.name,
            source_version=self.settings.source_version,
            observed_at=observed_at,
            available_at=available_at,
            retrieved_at=retrieved_at,
            quality_state=binding.quality_state,
            availability_basis=binding.availability_basis,
            payload=payload,
            provider_record_id=provider_record_id,
            limitations=binding.limitations,
        )


def build_from_environment() -> ConfiguredDatasetProvider:
    """Factory compatible with ``run_provider_backfill.py``."""

    path = str(
        os.getenv("CAPITAL_INTELLIGENCE_CONFIGURED_DATASET_PROVIDER", "")
    ).strip()
    if not path:
        raise ConfiguredDatasetProviderError(
            "CAPITAL_INTELLIGENCE_CONFIGURED_DATASET_PROVIDER is required"
        )
    return ConfiguredDatasetProvider.from_path(path)


__all__ = [
    "ConfiguredDatasetBinding",
    "ConfiguredDatasetProvider",
    "ConfiguredDatasetProviderError",
    "ConfiguredDatasetProviderSettings",
    "TransportResponse",
    "build_from_environment",
]
