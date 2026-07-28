"""Governed connectivity verification for free public data services.

Connectivity proves only that a configured endpoint returned structurally valid
supporting evidence.  It does not grant provider certification, data-rights
approval, paper-test readiness, execution authority, or real-money authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from data import MarketDataQuery, MarketDataType
from data.provider import ProviderError
from providers.crypto_venues import (
    CoinbaseExchangeProvider,
    KrakenSpotProvider,
    load_crypto_venue_bindings,
)
from providers.fred import FREDProvider
from providers.gleif import GleifProvider
from providers.openfigi import OpenFigiMappingJob, OpenFigiProvider
from providers.sec_edgar import SECEdgarProvider


class FreeProviderConnectionError(RuntimeError):
    """Raised when free-provider configuration or history is invalid."""


class FreeProviderConnectionIntegrityError(FreeProviderConnectionError):
    """Raised when append-only connection history has been altered."""


class FreeProviderConnectionState(str, Enum):
    CONNECTED = "connected"
    CREDENTIAL_REQUIRED = "credential_required"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


def _text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    result = value.strip()
    if not result:
        raise ValueError(f"{field_name} cannot be empty")
    return result


def _texts(value: object, *, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple")
    result = tuple(_text(item, field_name=field_name) for item in value)
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} cannot contain duplicates")
    return result


def _aware(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True, slots=True)
class FreeProviderDefinition:
    identifier: str
    enabled: bool
    required_environment_variables: tuple[str, ...]
    optional_environment_variables: tuple[str, ...]
    health_probe: Mapping[str, Any]
    readiness_authority: bool
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "identifier",
            _text(self.identifier, field_name="identifier").lower(),
        )
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a bool")
        object.__setattr__(
            self,
            "required_environment_variables",
            _texts(
                self.required_environment_variables,
                field_name="required_environment_variables",
            ),
        )
        object.__setattr__(
            self,
            "optional_environment_variables",
            _texts(
                self.optional_environment_variables,
                field_name="optional_environment_variables",
            ),
        )
        overlap = set(self.required_environment_variables) & set(
            self.optional_environment_variables
        )
        if overlap:
            raise ValueError("required and optional environment variables cannot overlap")
        if not isinstance(self.health_probe, Mapping):
            raise TypeError("health_probe must be a mapping")
        object.__setattr__(self, "health_probe", dict(self.health_probe))
        if self.readiness_authority is not False:
            raise ValueError("free-provider connectivity cannot be readiness authority")
        object.__setattr__(
            self,
            "limitations",
            _texts(self.limitations, field_name="limitations"),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FreeProviderDefinition":
        return cls(
            identifier=str(value["identifier"]),
            enabled=bool(value.get("enabled", False)),
            required_environment_variables=tuple(
                str(item)
                for item in value.get("required_environment_variables", ())
            ),
            optional_environment_variables=tuple(
                str(item)
                for item in value.get("optional_environment_variables", ())
            ),
            health_probe=dict(value.get("health_probe", {})),
            readiness_authority=bool(value.get("readiness_authority", False)),
            limitations=tuple(str(item) for item in value.get("limitations", ())),
        )


@dataclass(frozen=True, slots=True)
class FreeProviderConnectionCatalog:
    providers: tuple[FreeProviderDefinition, ...]
    schema_version: str = "free-provider-connections.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "free-provider-connections.v1":
            raise ValueError("unsupported free-provider connection schema")
        if not isinstance(self.providers, tuple) or not self.providers:
            raise ValueError("providers must be a non-empty tuple")
        if not all(isinstance(item, FreeProviderDefinition) for item in self.providers):
            raise TypeError("providers must contain FreeProviderDefinition values")
        identifiers = tuple(item.identifier for item in self.providers)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("provider identifiers cannot contain duplicates")
        expected = {
            "fred",
            "sec_edgar",
            "coinbase_exchange",
            "kraken_spot",
            "openfigi",
            "gleif",
        }
        if set(identifiers) != expected:
            raise ValueError(
                "free-provider catalog must contain exactly FRED, SEC EDGAR, "
                "Coinbase, Kraken, OpenFIGI, and GLEIF"
            )


@dataclass(frozen=True, slots=True)
class FreeProviderProbeResult:
    provider_identifier: str
    checked_at: datetime
    state: FreeProviderConnectionState
    configured: bool
    reachable: bool
    credential_names: tuple[str, ...]
    evidence_identifiers: tuple[str, ...]
    limitations: tuple[str, ...]
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider_identifier",
            _text(self.provider_identifier, field_name="provider_identifier").lower(),
        )
        object.__setattr__(self, "checked_at", _aware(self.checked_at, field_name="checked_at"))
        if not isinstance(self.state, FreeProviderConnectionState):
            raise TypeError("state must be FreeProviderConnectionState")
        if not isinstance(self.configured, bool) or not isinstance(self.reachable, bool):
            raise TypeError("configured and reachable must be bool values")
        object.__setattr__(
            self,
            "credential_names",
            _texts(self.credential_names, field_name="credential_names"),
        )
        object.__setattr__(
            self,
            "evidence_identifiers",
            _texts(self.evidence_identifiers, field_name="evidence_identifiers"),
        )
        object.__setattr__(
            self,
            "limitations",
            _texts(self.limitations, field_name="limitations"),
        )
        if self.error is not None:
            object.__setattr__(self, "error", _text(self.error, field_name="error"))
        if self.state is FreeProviderConnectionState.CONNECTED:
            if not self.configured or not self.reachable or not self.evidence_identifiers:
                raise ValueError("connected result requires configuration, reachability, and evidence")
            if self.error is not None:
                raise ValueError("connected result cannot contain an error")
        elif self.reachable:
            raise ValueError("only connected providers may be reachable")

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_identifier": self.provider_identifier,
            "checked_at": self.checked_at.isoformat(),
            "state": self.state.value,
            "configured": self.configured,
            "reachable": self.reachable,
            "credential_names": list(self.credential_names),
            "evidence_identifiers": list(self.evidence_identifiers),
            "limitations": list(self.limitations),
            "error": self.error,
            "supporting_evidence_connected": (
                self.state is FreeProviderConnectionState.CONNECTED
            ),
            "readiness_authority": False,
            "execution_authority": False,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FreeProviderProbeResult":
        return cls(
            provider_identifier=str(value["provider_identifier"]),
            checked_at=datetime.fromisoformat(str(value["checked_at"])),
            state=FreeProviderConnectionState(str(value["state"])),
            configured=bool(value["configured"]),
            reachable=bool(value["reachable"]),
            credential_names=tuple(str(item) for item in value.get("credential_names", ())),
            evidence_identifiers=tuple(
                str(item) for item in value.get("evidence_identifiers", ())
            ),
            limitations=tuple(str(item) for item in value.get("limitations", ())),
            error=None if value.get("error") is None else str(value["error"]),
        )


@dataclass(frozen=True, slots=True)
class FreeProviderConnectionReport:
    identifier: str
    checked_at: datetime
    results: tuple[FreeProviderProbeResult, ...]
    schema_version: str = "free-provider-connection-report.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "identifier", _text(self.identifier, field_name="identifier"))
        object.__setattr__(self, "checked_at", _aware(self.checked_at, field_name="checked_at"))
        if not isinstance(self.results, tuple) or not self.results:
            raise ValueError("results must be a non-empty tuple")
        if not all(isinstance(item, FreeProviderProbeResult) for item in self.results):
            raise TypeError("results must contain FreeProviderProbeResult values")
        identifiers = tuple(item.provider_identifier for item in self.results)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("results cannot contain duplicate providers")
        if self.schema_version != "free-provider-connection-report.v1":
            raise ValueError("unsupported free-provider report schema")

    @property
    def all_enabled_connected(self) -> bool:
        return all(
            item.state in {
                FreeProviderConnectionState.CONNECTED,
                FreeProviderConnectionState.DISABLED,
            }
            for item in self.results
        )

    @property
    def keyless_services_connected(self) -> bool:
        keyless = tuple(item for item in self.results if not item.credential_names)
        return bool(keyless) and all(
            item.state is FreeProviderConnectionState.CONNECTED for item in keyless
        )

    @property
    def credential_actions(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                credential
                for result in self.results
                if result.state is FreeProviderConnectionState.CREDENTIAL_REQUIRED
                for credential in result.credential_names
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "checked_at": self.checked_at.isoformat(),
            "results": [item.to_dict() for item in self.results],
            "all_enabled_connected": self.all_enabled_connected,
            "keyless_services_connected": self.keyless_services_connected,
            "credential_actions": list(self.credential_actions),
            "provider_certification_granted": False,
            "paper_test_readiness_granted": False,
            "execution_authority_granted": False,
            "real_money_authorized": False,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FreeProviderConnectionReport":
        for prohibited in (
            "provider_certification_granted",
            "paper_test_readiness_granted",
            "execution_authority_granted",
            "real_money_authorized",
        ):
            if bool(value.get(prohibited, False)):
                raise ValueError(f"free-provider report cannot set {prohibited}")
        return cls(
            identifier=str(value["identifier"]),
            checked_at=datetime.fromisoformat(str(value["checked_at"])),
            results=tuple(
                FreeProviderProbeResult.from_dict(item)
                for item in value.get("results", ())
                if isinstance(item, Mapping)
            ),
            schema_version=str(
                value.get("schema_version", "free-provider-connection-report.v1")
            ),
        )


def load_free_provider_catalog(path: str | Path) -> FreeProviderConnectionCatalog:
    source = Path(path).expanduser()
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FreeProviderConnectionError(
            f"cannot load free-provider catalog from {str(source)!r}"
        ) from error
    if not isinstance(value, Mapping):
        raise FreeProviderConnectionError("free-provider catalog must encode an object")
    raw = value.get("providers")
    if not isinstance(raw, list):
        raise FreeProviderConnectionError("free-provider catalog providers must be an array")
    return FreeProviderConnectionCatalog(
        providers=tuple(
            FreeProviderDefinition.from_dict(item)
            for item in raw
            if isinstance(item, Mapping)
        ),
        schema_version=str(value.get("schema_version", "")),
    )


class FreeProviderConnectionVerifier:
    """Probe every enabled free service without upgrading its authority."""

    def __init__(
        self,
        catalog: FreeProviderConnectionCatalog,
        *,
        environ: Mapping[str, str] | None = None,
        repository_root: str | Path = ".",
        clock: Callable[[], datetime] | None = None,
        fred_factory: Callable[..., FREDProvider] = FREDProvider,
        sec_factory: Callable[..., SECEdgarProvider] = SECEdgarProvider,
        coinbase_factory: Callable[..., CoinbaseExchangeProvider] = CoinbaseExchangeProvider,
        kraken_factory: Callable[..., KrakenSpotProvider] = KrakenSpotProvider,
        openfigi_factory: Callable[..., OpenFigiProvider] = OpenFigiProvider,
        gleif_factory: Callable[..., GleifProvider] = GleifProvider,
    ) -> None:
        if not isinstance(catalog, FreeProviderConnectionCatalog):
            raise TypeError("catalog must be FreeProviderConnectionCatalog")
        self.catalog = catalog
        self.environ = dict(os.environ if environ is None else environ)
        self.repository_root = Path(repository_root).expanduser()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._fred_factory = fred_factory
        self._sec_factory = sec_factory
        self._coinbase_factory = coinbase_factory
        self._kraken_factory = kraken_factory
        self._openfigi_factory = openfigi_factory
        self._gleif_factory = gleif_factory

    def verify(self) -> FreeProviderConnectionReport:
        checked_at = self._now()
        results = tuple(self._probe(item, checked_at=checked_at) for item in self.catalog.providers)
        return FreeProviderConnectionReport(
            identifier=f"free-provider-connections:{checked_at.isoformat()}",
            checked_at=checked_at,
            results=results,
        )

    def _probe(
        self,
        definition: FreeProviderDefinition,
        *,
        checked_at: datetime,
    ) -> FreeProviderProbeResult:
        if not definition.enabled:
            return FreeProviderProbeResult(
                provider_identifier=definition.identifier,
                checked_at=checked_at,
                state=FreeProviderConnectionState.DISABLED,
                configured=False,
                reachable=False,
                credential_names=definition.required_environment_variables,
                evidence_identifiers=(),
                limitations=definition.limitations,
            )
        missing = tuple(
            name
            for name in definition.required_environment_variables
            if not self.environ.get(name, "").strip()
        )
        if missing:
            return FreeProviderProbeResult(
                provider_identifier=definition.identifier,
                checked_at=checked_at,
                state=FreeProviderConnectionState.CREDENTIAL_REQUIRED,
                configured=False,
                reachable=False,
                credential_names=definition.required_environment_variables,
                evidence_identifiers=(),
                limitations=definition.limitations,
                error="missing required free-service configuration: " + ", ".join(missing),
            )
        try:
            evidence = self._execute(definition, checked_at=checked_at)
            return FreeProviderProbeResult(
                provider_identifier=definition.identifier,
                checked_at=checked_at,
                state=FreeProviderConnectionState.CONNECTED,
                configured=True,
                reachable=True,
                credential_names=definition.required_environment_variables,
                evidence_identifiers=evidence,
                limitations=definition.limitations,
            )
        except (ProviderError, OSError, TypeError, ValueError) as error:
            return FreeProviderProbeResult(
                provider_identifier=definition.identifier,
                checked_at=checked_at,
                state=FreeProviderConnectionState.UNAVAILABLE,
                configured=True,
                reachable=False,
                credential_names=definition.required_environment_variables,
                evidence_identifiers=(),
                limitations=definition.limitations,
                error=self._redact(str(error)),
            )

    def _execute(
        self,
        definition: FreeProviderDefinition,
        *,
        checked_at: datetime,
    ) -> tuple[str, ...]:
        probe = definition.health_probe
        if definition.identifier == "fred":
            series_id = _text(probe.get("series_id"), field_name="series_id").upper()
            observation = self._fred_factory(
                api_key=self.environ.get("FRED_API_KEY")
            ).get_latest_value(series_id)
            return (f"FRED:{series_id}:{observation.date}:{observation.value}",)
        if definition.identifier == "sec_edgar":
            snapshot = self._sec_factory(
                user_agent=self.environ.get("SEC_USER_AGENT")
            ).fetch_security_master()
            return (
                f"SEC_EDGAR:{snapshot.retrieved_at.isoformat()}:"
                f"{len(snapshot.instruments)}",
            )
        if definition.identifier in {"coinbase_exchange", "kraken_spot"}:
            bindings_path = Path(
                self.environ.get(
                    "CAPITAL_INTELLIGENCE_CRYPTO_VENUE_BINDINGS",
                    str(self.repository_root / "config" / "crypto_venue_bindings.free.json"),
                )
            ).expanduser()
            registry = load_crypto_venue_bindings(bindings_path)
            instrument_id = _text(
                probe.get("instrument_id"), field_name="instrument_id"
            )
            venue = _text(probe.get("venue"), field_name="venue").upper()
            provider = (
                self._coinbase_factory(bindings=registry)
                if definition.identifier == "coinbase_exchange"
                else self._kraken_factory(bindings=registry)
            )
            batch = provider.fetch(
                MarketDataQuery(
                    instrument_id=instrument_id,
                    data_type=MarketDataType.QUOTE,
                    as_of=checked_at,
                    venue=venue,
                    limit=1,
                )
            )
            quote = batch.records[0]
            return (
                f"{quote.provenance.provider}:{quote.provenance.venue}:"
                f"{quote.instrument_id}:{quote.provenance.observed_at.isoformat()}:"
                f"{quote.bid}:{quote.ask}",
            )
        if definition.identifier == "openfigi":
            provider = self._openfigi_factory(
                api_key=self.environ.get("OPENFIGI_API_KEY")
            )
            result = provider.map_identifiers(
                (
                    OpenFigiMappingJob(
                        id_type=_text(probe.get("id_type"), field_name="id_type"),
                        id_value=_text(probe.get("id_value"), field_name="id_value"),
                    ),
                )
            )[0]
            if not result.matches:
                raise FreeProviderConnectionError(
                    "OpenFIGI health mapping returned no instrument"
                )
            return tuple(
                f"OPENFIGI:{item.figi}:{item.ticker or 'NO_TICKER'}"
                for item in result.matches[:5]
            )
        if definition.identifier == "gleif":
            record = self._gleif_factory().fetch_lei(
                _text(probe.get("lei"), field_name="lei")
            )
            return (
                f"GLEIF:{record.lei}:{record.content_hash}",
                f"GLEIF_ENTITY:{record.issuer.issuer_id}",
            )
        raise FreeProviderConnectionError(
            f"unsupported free provider {definition.identifier!r}"
        )

    def _redact(self, value: str) -> str:
        result = value
        for name in {
            item
            for definition in self.catalog.providers
            for item in (
                *definition.required_environment_variables,
                *definition.optional_environment_variables,
            )
        }:
            secret = self.environ.get(name)
            if secret:
                result = result.replace(secret, "[REDACTED]")
        return result

    def _now(self) -> datetime:
        return _aware(self._clock(), field_name="clock")


class SQLiteFreeProviderConnectionStore:
    """Append-only SHA-256 history of live connection reports."""

    _TABLE = "free_provider_connection_reports"
    _GENESIS = "0" * 64

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    identifier TEXT NOT NULL UNIQUE,
                    checked_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE
                );
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_update
                BEFORE UPDATE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'free-provider reports are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS {self._TABLE}_no_delete
                BEFORE DELETE ON {self._TABLE}
                BEGIN SELECT RAISE(ABORT, 'free-provider reports are append-only'); END;
                """
            )

    @staticmethod
    def _hash(
        sequence: int,
        identifier: str,
        checked_at: str,
        payload_json: str,
        previous_hash: str,
    ) -> str:
        return hashlib.sha256(
            "|".join(
                (
                    str(sequence),
                    identifier,
                    checked_at,
                    payload_json,
                    previous_hash,
                )
            ).encode("utf-8")
        ).hexdigest()

    def append(self, report: FreeProviderConnectionReport) -> int:
        if not isinstance(report, FreeProviderConnectionReport):
            raise TypeError("report must be FreeProviderConnectionReport")
        self.verify_integrity()
        payload = _canonical_json(report.to_dict())
        checked_at = report.checked_at.isoformat()
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT sequence,payload_json FROM {self._TABLE} WHERE identifier=?",
                (report.identifier,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload:
                    raise FreeProviderConnectionError(
                        "connection report identifier has conflicting content"
                    )
                return int(existing["sequence"])
            tail = connection.execute(
                f"SELECT sequence,content_hash FROM {self._TABLE} "
                "ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            sequence = 1 if tail is None else int(tail["sequence"]) + 1
            previous = self._GENESIS if tail is None else str(tail["content_hash"])
            content_hash = self._hash(
                sequence,
                report.identifier,
                checked_at,
                payload,
                previous,
            )
            connection.execute(
                f"INSERT INTO {self._TABLE} VALUES (?,?,?,?,?,?)",
                (
                    sequence,
                    report.identifier,
                    checked_at,
                    payload,
                    previous,
                    content_hash,
                ),
            )
        return sequence

    def latest(self) -> FreeProviderConnectionReport | None:
        self.verify_integrity()
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                f"SELECT payload_json FROM {self._TABLE} ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
        return (
            None
            if row is None
            else FreeProviderConnectionReport.from_dict(json.loads(str(row[0])))
        )

    def verify_integrity(self) -> bool:
        previous = self._GENESIS
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                f"SELECT * FROM {self._TABLE} ORDER BY sequence"
            ).fetchall()
        for expected, row in enumerate(rows, start=1):
            if int(row[0]) != expected or str(row[4]) != previous:
                raise FreeProviderConnectionIntegrityError(
                    "free-provider report chain is not contiguous"
                )
            actual = self._hash(
                expected,
                str(row[1]),
                str(row[2]),
                str(row[3]),
                previous,
            )
            if str(row[5]) != actual:
                raise FreeProviderConnectionIntegrityError(
                    "free-provider report content hash is invalid"
                )
            previous = actual
        return True


__all__ = [
    "FreeProviderConnectionCatalog",
    "FreeProviderConnectionError",
    "FreeProviderConnectionIntegrityError",
    "FreeProviderConnectionReport",
    "FreeProviderConnectionState",
    "FreeProviderConnectionVerifier",
    "FreeProviderDefinition",
    "FreeProviderProbeResult",
    "SQLiteFreeProviderConnectionStore",
    "load_free_provider_catalog",
]
