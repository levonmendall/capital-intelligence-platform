"""Free derivative-risk resources for governed paper-only analysis.

CME SPAN/SPAN 2 and OCC OFRA are consumed as externally bound clearing-risk
artifacts.  This module validates provenance and availability, but deliberately does
not infer instrument margin requirements from opaque clearing files.  The existing
canonical volatility-surface compiler is exposed as a derived-data provider without
self-approving or self-certifying its model.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse, urlunparse

import requests

from data.derivative_market import (
    DerivativeDataError,
    OptionQuoteRecord,
    VolatilitySurfaceSnapshot,
    build_volatility_surface,
)


class FreeDerivativeRiskError(RuntimeError):
    """Raised when a free derivative-risk resource cannot be validated safely."""


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return value.astimezone(timezone.utc)


def _text(value: object) -> str:
    return str(value or "").strip()


def _approved(value: object) -> bool:
    return _text(value).lower() in {"1", "true", "yes", "approved", "allow", "allowed"}


def _safe_source(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        # Never persist signed URL query strings or fragments in evidence identifiers.
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    return value


@dataclass(frozen=True, slots=True)
class ClearingRiskResourceEvidence:
    provider_id: str
    dataset_role: str
    format_hint: str
    retrieved_at: datetime
    content_sha256: str
    byte_count: int
    source_identifier: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "dataset_role": self.dataset_role,
            "format_hint": self.format_hint,
            "retrieved_at": self.retrieved_at.isoformat(),
            "content_sha256": self.content_sha256,
            "byte_count": self.byte_count,
            "source_identifier": self.source_identifier,
            "individual_margin_requirement_inferred": False,
            "decision_authority_granted": False,
            "execution_authority_granted": False,
            "real_money_authorized": False,
        }


@dataclass(frozen=True, slots=True)
class FreeDerivativeRiskPreflight:
    evaluated_at: datetime
    cme: Mapping[str, Any]
    occ: Mapping[str, Any]
    derived_volatility: Mapping[str, Any]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "free-derivative-risk-preflight.v1",
            "evaluated_at": self.evaluated_at.isoformat(),
            "cme_span": dict(self.cme),
            "occ_ofra": dict(self.occ),
            "derived_volatility_surfaces": dict(self.derived_volatility),
            "blockers": list(self.blockers),
            "derivative_margin_role_minimum_sources": 3,
            "free_margin_sources_available": 2,
            "margin_role_complete_from_free_sources_alone": False,
            "provider_activation_granted": False,
            "decision_authority_granted": False,
            "execution_authority_granted": False,
            "real_money_authorized": False,
        }


class _BoundRiskResourceProvider:
    provider_id = ""
    binding_environment = ""
    dataset_role = "margin_collateral"
    allowed_host_suffixes: tuple[str, ...] = ()

    def __init__(
        self,
        binding: str | None = None,
        *,
        timeout: int = 20,
        maximum_bytes: int = 64 * 1024 * 1024,
        http_get=None,
    ) -> None:
        self.binding = _text(binding) or _text(os.getenv(self.binding_environment))
        self.timeout = int(timeout)
        self.maximum_bytes = int(maximum_bytes)
        if self.timeout < 1 or self.maximum_bytes < 1:
            raise ValueError("timeout and maximum_bytes must be positive")
        self._http_get = http_get or requests.get

    @property
    def configured(self) -> bool:
        return bool(self.binding)

    def fetch(self, *, as_of: datetime) -> ClearingRiskResourceEvidence:
        timestamp = _aware(as_of)
        if not self.binding:
            raise FreeDerivativeRiskError(
                f"{self.binding_environment} is not configured"
            )
        location, format_hint, expected_hash = self._resolve_binding(self.binding)
        content = self._read(location)
        if len(content) < 32:
            raise FreeDerivativeRiskError(
                f"{self.provider_id} clearing-risk artifact is empty or implausibly small"
            )
        digest = hashlib.sha256(content).hexdigest()
        if expected_hash and digest.lower() != expected_hash.lower():
            raise FreeDerivativeRiskError(
                f"{self.provider_id} clearing-risk artifact checksum mismatch"
            )
        return ClearingRiskResourceEvidence(
            provider_id=self.provider_id,
            dataset_role=self.dataset_role,
            format_hint=format_hint or self._format_hint(location, content),
            retrieved_at=timestamp,
            content_sha256=digest,
            byte_count=len(content),
            source_identifier=(
                f"{self.provider_id}:{self.dataset_role}:{_safe_source(location)}:{digest[:16]}"
            ),
        )

    def _resolve_binding(self, binding: str) -> tuple[str, str, str]:
        path = Path(binding).expanduser()
        if path.is_file() and path.suffix.lower() == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise FreeDerivativeRiskError(
                    f"{self.provider_id} binding JSON is invalid"
                ) from error
            if not isinstance(payload, Mapping):
                raise FreeDerivativeRiskError(
                    f"{self.provider_id} binding JSON must be an object"
                )
            location = _text(payload.get("location"))
            if not location:
                raise FreeDerivativeRiskError(
                    f"{self.provider_id} binding JSON requires location"
                )
            return (
                location,
                _text(payload.get("format")),
                _text(payload.get("sha256")),
            )
        return binding, "", ""

    def _read(self, location: str) -> bytes:
        parsed = urlparse(location)
        if parsed.scheme in {"http", "https"}:
            if parsed.scheme != "https":
                raise FreeDerivativeRiskError("clearing-risk remote bindings require HTTPS")
            hostname = (parsed.hostname or "").lower()
            if not hostname or not any(
                hostname == suffix or hostname.endswith("." + suffix)
                for suffix in self.allowed_host_suffixes
            ):
                raise FreeDerivativeRiskError(
                    f"{self.provider_id} binding must use an official provider host"
                )
            try:
                response = self._http_get(location, timeout=self.timeout)
            except requests.RequestException as error:
                raise FreeDerivativeRiskError(
                    f"{self.provider_id} clearing-risk download failed"
                ) from error
            status = int(getattr(response, "status_code", 0))
            if not 200 <= status < 300:
                raise FreeDerivativeRiskError(
                    f"{self.provider_id} clearing-risk download returned HTTP {status or 'unknown'}"
                )
            content = bytes(getattr(response, "content", b""))
        elif parsed.scheme == "file":
            content = self._read_file(Path(parsed.path))
        elif parsed.scheme:
            raise FreeDerivativeRiskError(
                f"unsupported {self.provider_id} binding scheme: {parsed.scheme}"
            )
        else:
            content = self._read_file(Path(location).expanduser())
        if len(content) > self.maximum_bytes:
            raise FreeDerivativeRiskError(
                f"{self.provider_id} clearing-risk artifact exceeds bounded size"
            )
        return content

    def _read_file(self, path: Path) -> bytes:
        try:
            size = path.stat().st_size
        except OSError as error:
            raise FreeDerivativeRiskError(
                f"{self.provider_id} clearing-risk file is unavailable"
            ) from error
        if size > self.maximum_bytes:
            raise FreeDerivativeRiskError(
                f"{self.provider_id} clearing-risk artifact exceeds bounded size"
            )
        try:
            return path.read_bytes()
        except OSError as error:
            raise FreeDerivativeRiskError(
                f"{self.provider_id} clearing-risk file could not be read"
            ) from error

    @staticmethod
    def _format_hint(location: str, content: bytes) -> str:
        suffix = Path(urlparse(location).path).suffix.lower().lstrip(".")
        if suffix:
            return suffix
        sample = content[:64].lstrip()
        if sample.startswith(b"<"):
            return "xml"
        if sample.startswith((b"{", b"[")):
            return "json"
        return "clearing-risk-file"


class CmeSpanRiskProvider(_BoundRiskResourceProvider):
    """Bound CME DataMine-delivered SPAN/SPAN 2 risk parameter evidence."""

    provider_id = "cme-margin-data"
    binding_environment = "CAPITAL_INTELLIGENCE_CME_MARGIN_BINDING"
    allowed_host_suffixes = ("cmegroup.com",)


class OccOfraRiskProvider(_BoundRiskResourceProvider):
    """Bound OCC Options & Futures Risk Array evidence."""

    provider_id = "occ-margin-data"
    binding_environment = "CAPITAL_INTELLIGENCE_OCC_MARGIN_BINDING"
    allowed_host_suffixes = ("theocc.com",)


class DerivedVolatilitySurfaceProvider:
    """Governed wrapper around the canonical internal volatility-surface compiler."""

    binding_environment = "CAPITAL_INTELLIGENCE_VOLATILITY_SURFACE_BINDING"
    approval_environment = "CAPITAL_INTELLIGENCE_VOLATILITY_SURFACE_MODEL_APPROVAL"
    certification_environment = "CAPITAL_INTELLIGENCE_VOLATILITY_SURFACE_CERTIFICATION_ID"

    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = dict(os.environ if environment is None else environment)

    @property
    def configured(self) -> bool:
        return bool(_text(self.environment.get(self.binding_environment)))

    @property
    def model_approved(self) -> bool:
        return _approved(self.environment.get(self.approval_environment))

    @property
    def certification_present(self) -> bool:
        return bool(_text(self.environment.get(self.certification_environment)))

    @property
    def governance_ready(self) -> bool:
        return self.configured and self.model_approved and self.certification_present

    def build(
        self,
        quotes: Sequence[OptionQuoteRecord],
        *,
        as_of: datetime,
        minimum_expirations: int = 2,
        minimum_strikes_per_expiration: int = 5,
    ) -> VolatilitySurfaceSnapshot:
        # Mathematical compilation is intentionally separate from governance approval.
        # Successful compilation cannot manufacture an approval/certification record.
        try:
            return build_volatility_surface(
                quotes,
                as_of=_aware(as_of),
                minimum_expirations=minimum_expirations,
                minimum_strikes_per_expiration=minimum_strikes_per_expiration,
            )
        except DerivativeDataError:
            raise

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "model_approved": self.model_approved,
            "certification_present": self.certification_present,
            "governance_ready": self.governance_ready,
            "method": "black-scholes-bisection.v1",
            "self_certification_allowed": False,
            "decision_authority_granted": False,
            "execution_authority_granted": False,
            "real_money_authorized": False,
        }


def preflight_free_derivative_risk_resources(
    *,
    as_of: datetime,
    environment: Mapping[str, str] | None = None,
    http_get=None,
) -> FreeDerivativeRiskPreflight:
    """Validate configured free derivative-risk resources without activating them."""

    timestamp = _aware(as_of)
    env = dict(os.environ if environment is None else environment)
    blockers: list[str] = []
    statuses: dict[str, dict[str, Any]] = {}
    specs = (
        ("cme", CmeSpanRiskProvider(env.get("CAPITAL_INTELLIGENCE_CME_MARGIN_BINDING"), http_get=http_get)),
        ("occ", OccOfraRiskProvider(env.get("CAPITAL_INTELLIGENCE_OCC_MARGIN_BINDING"), http_get=http_get)),
    )
    for name, provider in specs:
        if not provider.configured:
            statuses[name] = {"configured": False, "resource_valid": False}
            continue
        try:
            evidence = provider.fetch(as_of=timestamp)
        except FreeDerivativeRiskError as error:
            statuses[name] = {
                "configured": True,
                "resource_valid": False,
                "error": str(error),
            }
            blockers.append(f"{provider.provider_id}: {error}")
        else:
            statuses[name] = {
                "configured": True,
                "resource_valid": True,
                "evidence": evidence.to_dict(),
            }
    derived = DerivedVolatilitySurfaceProvider(env).status()
    return FreeDerivativeRiskPreflight(
        evaluated_at=timestamp,
        cme=statuses["cme"],
        occ=statuses["occ"],
        derived_volatility=derived,
        blockers=tuple(blockers),
    )


__all__ = [
    "ClearingRiskResourceEvidence",
    "CmeSpanRiskProvider",
    "DerivedVolatilitySurfaceProvider",
    "FreeDerivativeRiskError",
    "FreeDerivativeRiskPreflight",
    "OccOfraRiskProvider",
    "preflight_free_derivative_risk_resources",
]
