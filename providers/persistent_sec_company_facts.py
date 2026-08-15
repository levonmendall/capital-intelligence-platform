"""Persistent point-in-time cache for governed SEC Company Facts.

Company facts are periodic evidence and must not be re-downloaded on every market-data
refresh. The cache reuses only a snapshot retrieved at or before the requested cutoff and
only within a bounded freshness window. Stale or future-known cache entries never satisfy
a query; the wrapped resilient SEC provider remains the refresh authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from data import FilingQuery
from operations.paper_evidence_spool import _canonical_bytes, _json_hook
from providers.sec_company_facts_availability import install_company_facts_availability_boundary

_DEFAULT_MAX_AGE_HOURS = 6.0
_SCHEMA = "persistent-sec-company-facts.v1"


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("SEC cache timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _max_age_hours(values: Mapping[str, str]) -> float:
    raw = values.get("CAPITAL_INTELLIGENCE_SEC_COMPANY_FACTS_MAX_AGE_HOURS", "").strip()
    if not raw:
        return _DEFAULT_MAX_AGE_HOURS
    value = float(raw)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("CAPITAL_INTELLIGENCE_SEC_COMPANY_FACTS_MAX_AGE_HOURS must be positive")
    return value


def _root(values: Mapping[str, str]) -> Path | None:
    raw = values.get("CAPITAL_INTELLIGENCE_DATA_DIR", "").strip()
    if not raw:
        return None
    return Path(raw).expanduser() / "sec_company_facts_cache"


def _key(query: FilingQuery) -> str:
    material = {
        "schema_version": _SCHEMA,
        "cik": query.cik,
        "forms": list(query.forms),
        "limit": query.limit,
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


class PersistentSECCompanyFactsProvider:
    """Wrap the resilient SEC provider with bounded persistent fact reuse."""

    def __init__(self, provider=None, *, values: Mapping[str, str] | None = None) -> None:
        self._values = dict(os.environ if values is None else values)
        provider_type = install_company_facts_availability_boundary()
        self._provider = provider or provider_type()
        self._root = _root(self._values)
        self._max_age = timedelta(hours=_max_age_hours(self._values))

    def __getattr__(self, name: str):
        return getattr(self._provider, name)

    def _load(self, query: FilingQuery):
        if self._root is None:
            return None
        key = _key(query)
        pointer_path = self._root / "latest" / f"{key}.json"
        try:
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            if not isinstance(pointer, dict) or pointer.get("schema_version") != _SCHEMA:
                return None
            retrieved_at = _aware(datetime.fromisoformat(str(pointer["retrieved_at"])))
            query_as_of = _aware(datetime.fromisoformat(str(pointer["query_as_of"])))
            requested = _aware(query.as_of)
            if retrieved_at > requested or query_as_of > requested:
                return None
            age = requested - retrieved_at
            if age < timedelta(0) or age > self._max_age:
                return None
            digest = str(pointer["blob_sha256"])
            compressed = (self._root / "blobs" / f"{digest}.zlib").read_bytes()
            raw = zlib.decompress(compressed)
            if hashlib.sha256(raw).hexdigest() != digest:
                return None
            value = json.loads(raw, object_hook=_json_hook)
            if not isinstance(value, list):
                return None
            return tuple(value)
        except (OSError, ValueError, KeyError, json.JSONDecodeError, zlib.error):
            return None

    def _persist(self, query: FilingQuery, facts) -> None:
        if self._root is None:
            return
        raw = _canonical_bytes(tuple(facts))
        digest = hashlib.sha256(raw).hexdigest()
        blob = self._root / "blobs" / f"{digest}.zlib"
        blob.parent.mkdir(parents=True, exist_ok=True)
        if not blob.exists():
            temporary = blob.with_name(f".{blob.name}.tmp-{os.getpid()}")
            temporary.write_bytes(zlib.compress(raw, level=6))
            try:
                os.link(temporary, blob)
            except FileExistsError:
                pass
            finally:
                temporary.unlink(missing_ok=True)
        retrieved_at = max(
            (getattr(item, "retrieved_at", query.as_of) for item in facts),
            default=query.as_of,
        )
        _atomic_json(
            self._root / "latest" / f"{_key(query)}.json",
            {
                "schema_version": _SCHEMA,
                "cik": query.cik,
                "forms": list(query.forms),
                "limit": query.limit,
                "query_as_of": _aware(query.as_of).isoformat(),
                "retrieved_at": _aware(retrieved_at).isoformat(),
                "blob_sha256": digest,
                "paper_only": True,
                "real_money_authorized": False,
            },
        )

    def fetch_company_facts(self, query: FilingQuery):
        cached = self._load(query)
        if cached is not None:
            return cached
        facts = self._provider.fetch_company_facts(query)
        self._persist(query, facts)
        return facts


__all__ = ["PersistentSECCompanyFactsProvider"]
