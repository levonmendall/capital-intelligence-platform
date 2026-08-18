"""Rate-limit-resilient, root-checkpointed Massive futures reference acquisition.

Massive's free/reference cadence is slower than a full 13-root acquisition can complete
inside one futures-component execution budget. Successful roots are therefore persisted
independently and reused across later attempts. Retries remain bounded, HTTP 429
``Retry-After`` is honored up to a short per-attempt ceiling, and a failed root does not
discard other roots that qualified in the same pass.

The adapter is reference-data-only. It has no investment, CIO, construction, execution,
or real-money authority. Complete configured-root coverage remains mandatory before a
combined result is returned.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from providers.massive_futures_reference_bounded import (
    MassiveFuturesReferenceProvider as _BoundedMassiveFuturesReferenceProvider,
)
from providers.massive_multi_asset import MassiveFuturesContract, MassiveMultiAssetError


_MAX_REFERENCE_RETRY_AFTER_SECONDS = 20.0
_DEFAULT_REFERENCE_MAX_ATTEMPTS = 2
_DEFAULT_RATE_LIMIT_RETRY_SECONDS = 15.0
_ROOT_CACHE_SCHEMA = "massive-futures-reference-root-cache.v1"
_ROOT_CACHE_MAX_AGE = timedelta(hours=24)


class _ReferenceRequestError(MassiveMultiAssetError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(
            message,
            status_code=status_code,
            retryable=retryable,
        )
        self.retry_after_seconds = retry_after_seconds


def _cache_id(material: Mapping[str, object]) -> str:
    encoded = json.dumps(
        dict(material),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class MassiveFuturesReferenceProvider(_BoundedMassiveFuturesReferenceProvider):
    """Bounded futures reference provider with durable per-root convergence."""

    def __init__(
        self,
        *args: object,
        reference_max_attempts: int = _DEFAULT_REFERENCE_MAX_ATTEMPTS,
        rate_limit_retry_seconds: float = _DEFAULT_RATE_LIMIT_RETRY_SECONDS,
        root_cache_max_age_hours: float = 24.0,
        **kwargs: object,
    ) -> None:
        super().__init__(
            *args,
            reference_max_attempts=reference_max_attempts,
            rate_limit_retry_seconds=rate_limit_retry_seconds,
            **kwargs,
        )
        cache_age = timedelta(hours=float(root_cache_max_age_hours))
        if cache_age <= timedelta(0) or cache_age > _ROOT_CACHE_MAX_AGE:
            raise ValueError("root_cache_max_age_hours must be positive and no more than 24")
        self.root_cache_max_age = cache_age

    @staticmethod
    def _reference_retry_after_seconds(response: Any) -> float | None:
        headers = getattr(response, "headers", None)
        if not isinstance(headers, Mapping):
            return None
        raw = headers.get("Retry-After") or headers.get("retry-after")
        if raw in (None, ""):
            return None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        return max(0.0, min(value, _MAX_REFERENCE_RETRY_AFTER_SECONDS))

    def _single_reference_request(
        self,
        url: str,
        *,
        params: dict[str, object],
    ) -> Mapping[str, Any]:
        response = None
        try:
            self._reserve_request()
            response = self._http_get(url, params=params, timeout=self.timeout)
        except requests.RequestException as error:
            raise _ReferenceRequestError(
                "Massive request failed",
                retryable=True,
            ) from error

        status = int(getattr(response, "status_code", 0))
        if not 200 <= status < 300:
            retryable = status in {408, 425, 429} or 500 <= status <= 599
            raise _ReferenceRequestError(
                f"Massive returned HTTP {status or 'unknown'}",
                status_code=status or None,
                retryable=retryable,
                retry_after_seconds=(
                    self._reference_retry_after_seconds(response)
                    if status == 429
                    else None
                ),
            )

        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise _ReferenceRequestError("Massive returned invalid JSON") from error
        if not isinstance(payload, Mapping):
            raise _ReferenceRequestError("Massive response must be an object")
        status_text = str(payload.get("status") or "OK").upper()
        if status_text not in {"OK", "SUCCESS"}:
            raise _ReferenceRequestError("Massive rejected the request")
        return payload

    def _reference_get(
        self,
        url: str,
        *,
        params: dict[str, object],
        root_telemetry: dict[str, object],
    ) -> Mapping[str, Any]:
        last_error: MassiveMultiAssetError | None = None
        for attempt in range(1, self.reference_max_attempts + 1):
            root_telemetry["request_attempts"] = int(
                root_telemetry.get("request_attempts", 0)
            ) + 1
            try:
                payload = self._single_reference_request(url, params=params)
            except MassiveMultiAssetError as error:
                last_error = error
                if error.status_code is not None:
                    root_telemetry["http_status"] = int(error.status_code)
                root_telemetry["last_error"] = type(error).__name__
                if error.status_code == 429:
                    root_telemetry["rate_limited"] = True
                    retry_after = getattr(error, "retry_after_seconds", None)
                    if retry_after is not None:
                        root_telemetry["retry_after_seconds"] = float(retry_after)
                if not error.retryable or attempt >= self.reference_max_attempts:
                    if error.status_code in {401, 403}:
                        root_telemetry["failure_reason"] = "provider_auth_or_entitlement"
                    elif error.status_code == 429:
                        root_telemetry["failure_reason"] = "provider_rate_limited"
                    elif error.status_code is not None:
                        root_telemetry["failure_reason"] = "provider_http_error"
                    else:
                        root_telemetry["failure_reason"] = "provider_transport_error"
                    raise

                if error.status_code == 429:
                    retry_after = getattr(error, "retry_after_seconds", None)
                    if retry_after is None:
                        delay = self.rate_limit_retry_seconds
                        root_telemetry["rate_limit_retry_source"] = "configured_fallback"
                    else:
                        delay = float(retry_after)
                        root_telemetry["rate_limit_retry_source"] = "provider_retry_after"
                else:
                    delay = min(30.0, 2.0 ** (attempt - 1))

                root_telemetry["failure_reason"] = "pending"
                root_telemetry["retry_count"] = int(
                    root_telemetry.get("retry_count", 0)
                ) + 1
                root_telemetry["last_retry_delay_seconds"] = float(delay)
                if delay > 0.0:
                    self._sleeper(delay)
            else:
                root_telemetry["http_status"] = 200
                return payload

        assert last_error is not None
        raise last_error

    @staticmethod
    def _serialize_contract(contract: MassiveFuturesContract) -> dict[str, object]:
        return {
            "ticker": contract.ticker,
            "product_code": contract.product_code,
            "trading_venue": contract.trading_venue,
            "first_trade_date": contract.first_trade_date,
            "last_trade_date": contract.last_trade_date,
            "settlement_date": contract.settlement_date,
            "active": bool(contract.active),
            "source_identifier": contract.source_identifier,
        }

    @staticmethod
    def _deserialize_contract(payload: Mapping[str, object]) -> MassiveFuturesContract:
        return MassiveFuturesContract(
            ticker=str(payload["ticker"]),
            product_code=str(payload["product_code"]),
            trading_venue=str(payload["trading_venue"]),
            first_trade_date=str(payload["first_trade_date"]),
            last_trade_date=str(payload["last_trade_date"]),
            settlement_date=(
                None
                if payload.get("settlement_date") in (None, "")
                else str(payload.get("settlement_date"))
            ),
            active=bool(payload.get("active", True)),
            source_identifier=str(payload["source_identifier"]),
        )

    @staticmethod
    def _cache_root() -> Path:
        return Path(os.getenv("CAPITAL_INTELLIGENCE_DATA_DIR", "database")).expanduser() / "reference_readiness" / "massive_futures_roots"

    def _root_cache_path(self, root: str) -> Path:
        safe_root = "".join(character for character in root.upper() if character.isalnum())
        return self._cache_root() / f"{safe_root}.json"

    def _write_root_cache(
        self,
        *,
        root: str,
        as_of: datetime,
        contracts: Sequence[MassiveFuturesContract],
    ) -> None:
        records = [self._serialize_contract(item) for item in contracts]
        material: dict[str, object] = {
            "schema_version": _ROOT_CACHE_SCHEMA,
            "root": root,
            "qualified_as_of": as_of.astimezone(timezone.utc).isoformat(),
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "records": records,
            "paper_only": True,
            "real_money_authorized": False,
        }
        payload = {**material, "cache_id": _cache_id(material)}
        path = self._root_cache_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
        temporary.write_text(
            json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def _load_root_cache(
        self,
        *,
        root: str,
        as_of: datetime,
    ) -> tuple[MassiveFuturesContract, ...] | None:
        path = self._root_cache_path(root)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, Mapping) or payload.get("schema_version") != _ROOT_CACHE_SCHEMA:
            return None
        expected_id = str(payload.get("cache_id") or "")
        material = {key: value for key, value in payload.items() if key != "cache_id"}
        if not expected_id or _cache_id(material) != expected_id:
            return None
        if str(payload.get("root") or "").strip().upper() != root:
            return None
        try:
            captured_at = datetime.fromisoformat(
                str(payload.get("captured_at") or "").replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            qualified_as_of = datetime.fromisoformat(
                str(payload.get("qualified_as_of") or "").replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except (TypeError, ValueError):
            return None
        now = datetime.now(timezone.utc)
        if captured_at > now or now - captured_at > self.root_cache_max_age:
            return None
        # Root checkpoints are only reused for the same UTC reference date. Contract
        # definitions are slow-moving, but point-in-time qualification must not be
        # silently rebound across a date boundary.
        if qualified_as_of.date() != as_of.astimezone(timezone.utc).date():
            return None
        raw_records = payload.get("records")
        if not isinstance(raw_records, Sequence) or isinstance(raw_records, (str, bytes)):
            return None
        try:
            contracts = tuple(
                self._deserialize_contract(item)
                for item in raw_records
                if isinstance(item, Mapping)
            )
        except (KeyError, TypeError, ValueError):
            return None
        if not contracts:
            return None
        reference_date = as_of.astimezone(timezone.utc).date()
        for contract in contracts:
            if contract.product_code.strip().upper() != root or not contract.active:
                return None
            first = self._parse_date(contract.first_trade_date)
            last = self._parse_date(contract.last_trade_date)
            if first is None or last is None or not first <= reference_date <= last:
                return None
        return tuple(sorted(contracts, key=lambda item: item.ticker))

    def futures_contracts(
        self,
        *,
        as_of: datetime,
        product_codes: Sequence[str] = (),
        maximum_pages: int = 20,
    ) -> tuple[MassiveFuturesContract, ...]:
        roots = tuple(
            sorted(
                {
                    str(item).strip().upper()
                    for item in product_codes
                    if str(item).strip()
                }
            )
        )
        if len(roots) <= 1:
            result = tuple(
                super().futures_contracts(
                    as_of=as_of,
                    product_codes=product_codes,
                    maximum_pages=maximum_pages,
                )
            )
            if roots and result:
                self._write_root_cache(root=roots[0], as_of=as_of, contracts=result)
            return result

        contracts_by_ticker: dict[str, MassiveFuturesContract] = {}
        telemetry_by_root: dict[str, dict[str, object]] = {}
        missing: list[str] = []
        for root in roots:
            cached = self._load_root_cache(root=root, as_of=as_of)
            if cached is None:
                missing.append(root)
                continue
            for contract in cached:
                contracts_by_ticker[contract.ticker] = contract
            telemetry_by_root[root] = {
                "root": root,
                "http_status": 200,
                "request_attempts": 0,
                "retry_count": 0,
                "rate_limited": False,
                "pages": 0,
                "raw_result_count": len(cached),
                "parsed_contract_count": len(cached),
                "root_matched_count": len(cached),
                "point_in_time_valid_count": len(cached),
                "usable_count": len(cached),
                "pagination_complete": True,
                "query_mode": "persistent_root_cache",
                "failure_reason": "ok",
            }

        failures: list[tuple[str, MassiveMultiAssetError]] = []
        for index, root in enumerate(missing):
            if index and self.minimum_call_interval_seconds > 0.0:
                self._sleeper(self.minimum_call_interval_seconds)
            try:
                root_contracts = tuple(
                    super().futures_contracts(
                        as_of=as_of,
                        product_codes=(root,),
                        maximum_pages=maximum_pages,
                    )
                )
            except MassiveMultiAssetError as error:
                for row in self.reference_telemetry:
                    row_root = str(row.get("root") or "").strip().upper()
                    if row_root:
                        telemetry_by_root[row_root] = dict(row)
                failures.append((root, error))
                continue
            for row in self.reference_telemetry:
                row_root = str(row.get("root") or "").strip().upper()
                if row_root:
                    telemetry_by_root[row_root] = dict(row)
            if not root_contracts:
                failures.append((root, MassiveMultiAssetError("Massive returned no contracts")))
                continue
            self._write_root_cache(root=root, as_of=as_of, contracts=root_contracts)
            for contract in root_contracts:
                contracts_by_ticker[contract.ticker] = contract

        self._reference_telemetry = telemetry_by_root
        covered = {
            contract.product_code.strip().upper()
            for contract in contracts_by_ticker.values()
            if contract.active
        }
        unresolved = tuple(root for root in roots if root not in covered)
        if unresolved:
            telemetry_detail = self._compact_failure_telemetry(self.reference_telemetry)
            first_error = failures[0][1] if failures else None
            raise MassiveMultiAssetError(
                "Massive root-checkpointed futures reference remains incomplete: "
                + ", ".join(unresolved)
                + f"; massive_futures_telemetry={telemetry_detail}",
                status_code=None if first_error is None else first_error.status_code,
                retryable=False if first_error is None else first_error.retryable,
            ) from first_error

        return tuple(
            contracts_by_ticker[ticker] for ticker in sorted(contracts_by_ticker)
        )


__all__ = ["MassiveFuturesReferenceProvider"]
