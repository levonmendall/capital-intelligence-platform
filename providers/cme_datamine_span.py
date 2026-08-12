"""Bounded CME DataMine client for entitled SPAN risk-parameter files.

The client authenticates with a CME DataMine API ID/password, discovers entitled
files for recent period dates, matches only file IDs in the governed SPAN catalog,
and downloads one bounded representative risk-parameter artifact for access and
lineage validation. It does not calculate portfolio margin or grant investment or
execution authority.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import requests


TOKEN_URL = "https://auth.cmegroup.com/as/token.oauth2"
LIST_URL = "https://datamine.new.cmegroup.com/api/list_entitlements_files"
DOWNLOAD_URL = "https://datamine.new.cmegroup.com/cme/api/v2/download"
DEFAULT_CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "cme_span_datamine_file_ids.json"
)


class CmeDataMineSpanError(RuntimeError):
    """Raised when CME DataMine SPAN discovery or download fails safely."""


@dataclass(frozen=True, slots=True)
class CmeDataMineSpanFile:
    period_date: str
    file_id: str
    file_name: str
    api_download_link: str
    size: int | None


@dataclass(frozen=True, slots=True)
class CmeDataMineSpanDownload:
    file: CmeDataMineSpanFile
    content: bytes
    entitled_match_count: int
    catalog_pattern_count: int
    selection_policy: str = "final-eod-pa2-preferred.v1"


class CmeDataMineSpanClient:
    """Discover and retrieve a bounded entitled SPAN file from CME DataMine."""

    def __init__(
        self,
        api_id: str,
        api_password: str,
        *,
        catalog_path: str | Path | None = None,
        timeout: int = 20,
        maximum_bytes: int = 64 * 1024 * 1024,
        maximum_lookback_days: int = 7,
        maximum_pages_per_date: int = 4,
        http_get: Callable[..., Any] | None = None,
        http_post: Callable[..., Any] | None = None,
    ) -> None:
        self.api_id = str(api_id or "").strip()
        self.api_password = str(api_password or "").strip()
        if not self.api_id or not self.api_password:
            raise ValueError("CME DataMine API ID and API password are both required")
        self.catalog_path = Path(catalog_path or DEFAULT_CATALOG_PATH)
        self.timeout = int(timeout)
        self.maximum_bytes = int(maximum_bytes)
        self.maximum_lookback_days = int(maximum_lookback_days)
        self.maximum_pages_per_date = int(maximum_pages_per_date)
        if (
            self.timeout < 1
            or self.maximum_bytes < 1
            or self.maximum_lookback_days < 1
            or self.maximum_pages_per_date < 1
        ):
            raise ValueError("CME DataMine bounds must be positive")
        self._http_get = http_get or requests.get
        self._http_post = http_post or requests.post

    def fetch_latest(self, *, as_of: datetime) -> CmeDataMineSpanDownload:
        timestamp = self._aware(as_of)
        patterns = self._load_patterns()
        token = self._access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "Capital-Intelligence-Platform/CME-DataMine-SPAN",
        }
        for day_offset in range(self.maximum_lookback_days):
            period_date = (timestamp.date() - timedelta(days=day_offset)).strftime("%Y%m%d")
            candidates = {
                pattern.replace("{YYYYMMDD}", period_date) for pattern in patterns
            }
            matches = self._list_matches(
                headers=headers,
                period_date=period_date,
                candidates=candidates,
            )
            if not matches:
                continue
            selected = min(matches, key=self._selection_key)
            content = self._download(headers=headers, file=selected)
            return CmeDataMineSpanDownload(
                file=selected,
                content=content,
                entitled_match_count=len(matches),
                catalog_pattern_count=len(patterns),
            )
        raise CmeDataMineSpanError(
            "CME DataMine returned no entitled SPAN file matching the governed catalog "
            f"within {self.maximum_lookback_days} day(s)"
        )

    def _access_token(self) -> str:
        try:
            response = self._http_post(
                TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(self.api_id, self.api_password),
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise CmeDataMineSpanError("CME DataMine OAuth request failed") from error
        status = int(getattr(response, "status_code", 0))
        if status < 200 or status >= 300:
            raise CmeDataMineSpanError(
                f"CME DataMine OAuth returned HTTP {status or 'unknown'}"
            )
        try:
            payload = response.json()
        except (TypeError, ValueError) as error:
            raise CmeDataMineSpanError("CME DataMine OAuth returned invalid JSON") from error
        token = str(payload.get("access_token") or "").strip() if isinstance(payload, Mapping) else ""
        if not token:
            raise CmeDataMineSpanError("CME DataMine OAuth response omitted access_token")
        return token

    def _list_matches(
        self,
        *,
        headers: Mapping[str, str],
        period_date: str,
        candidates: set[str],
    ) -> tuple[CmeDataMineSpanFile, ...]:
        url = LIST_URL
        params: dict[str, object] | None = {
            "period_date": period_date,
            "limit": 1000,
            "offset": 0,
        }
        matches: dict[str, CmeDataMineSpanFile] = {}
        for _page in range(self.maximum_pages_per_date):
            try:
                response = self._http_get(
                    url,
                    headers=dict(headers),
                    params=params,
                    timeout=self.timeout,
                )
            except requests.RequestException as error:
                raise CmeDataMineSpanError("CME DataMine List API request failed") from error
            status = int(getattr(response, "status_code", 0))
            if status < 200 or status >= 300:
                raise CmeDataMineSpanError(
                    f"CME DataMine List API returned HTTP {status or 'unknown'}"
                )
            try:
                payload = response.json()
            except (TypeError, ValueError) as error:
                raise CmeDataMineSpanError("CME DataMine List API returned invalid JSON") from error
            if not isinstance(payload, Mapping):
                raise CmeDataMineSpanError("CME DataMine List API response must be an object")
            data = payload.get("data")
            if isinstance(data, Sequence) and not isinstance(data, (str, bytes, bytearray)):
                for dataset in data:
                    if not isinstance(dataset, Mapping):
                        continue
                    dataset_period = str(dataset.get("period_date") or period_date).strip()
                    files = dataset.get("files")
                    if not isinstance(files, Sequence) or isinstance(files, (str, bytes, bytearray)):
                        continue
                    for raw in files:
                        if not isinstance(raw, Mapping):
                            continue
                        file_id = str(raw.get("file_id") or "").strip()
                        if file_id not in candidates:
                            continue
                        raw_size = raw.get("size")
                        size = int(raw_size) if isinstance(raw_size, (int, float)) and not isinstance(raw_size, bool) else None
                        if size is not None and size > self.maximum_bytes:
                            continue
                        matches[file_id] = CmeDataMineSpanFile(
                            period_date=dataset_period,
                            file_id=file_id,
                            file_name=str(raw.get("file_name") or "").strip(),
                            api_download_link=str(raw.get("api_download_link") or "").strip(),
                            size=size,
                        )
            paging = payload.get("paging")
            next_url = str(paging.get("next") or "").strip() if isinstance(paging, Mapping) else ""
            if not next_url:
                break
            if not next_url.startswith("https://datamine.new.cmegroup.com/"):
                raise CmeDataMineSpanError("CME DataMine pagination returned a non-CME URL")
            url = next_url
            params = None
        return tuple(matches.values())

    def _download(
        self,
        *,
        headers: Mapping[str, str],
        file: CmeDataMineSpanFile,
    ) -> bytes:
        url = file.api_download_link or DOWNLOAD_URL
        if not url.startswith("https://datamine.new.cmegroup.com/"):
            raise CmeDataMineSpanError("CME DataMine file download URL is not an official host")
        params = None if file.api_download_link else {"fid": file.file_id}
        try:
            response = self._http_get(
                url,
                headers=dict(headers),
                params=params,
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise CmeDataMineSpanError("CME DataMine SPAN download failed") from error
        status = int(getattr(response, "status_code", 0))
        if status < 200 or status >= 300:
            raise CmeDataMineSpanError(
                f"CME DataMine SPAN download returned HTTP {status or 'unknown'}"
            )
        content = bytes(getattr(response, "content", b""))
        if len(content) > self.maximum_bytes:
            raise CmeDataMineSpanError("CME DataMine SPAN artifact exceeds bounded size")
        if len(content) < 32:
            raise CmeDataMineSpanError("CME DataMine SPAN artifact is empty or implausibly small")
        return content

    def _load_patterns(self) -> tuple[str, ...]:
        try:
            payload = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CmeDataMineSpanError("CME SPAN file-ID catalog is unavailable or invalid") from error
        if not isinstance(payload, Mapping) or payload.get("schema_version") != "cme-span-datamine-file-ids.v1":
            raise CmeDataMineSpanError("CME SPAN file-ID catalog schema is unsupported")
        raw_patterns = payload.get("file_id_patterns")
        if not isinstance(raw_patterns, Sequence) or isinstance(raw_patterns, (str, bytes, bytearray)):
            raise CmeDataMineSpanError("CME SPAN file-ID catalog has no patterns")
        patterns = tuple(
            str(item).strip()
            for item in raw_patterns
            if isinstance(item, str) and "{YYYYMMDD}" in item and item.strip()
        )
        if not patterns:
            raise CmeDataMineSpanError("CME SPAN file-ID catalog has no valid patterns")
        return patterns

    @staticmethod
    def _selection_key(file: CmeDataMineSpanFile) -> tuple[int, str]:
        identifier = file.file_id.upper()
        # The conventional CME production final end-of-day SPAN file has historically
        # used the "S" cycle and PA2 format. This preference is only for bounded access
        # validation; the platform does not infer portfolio margin from the selected file.
        if "SPAN_CUSTPA2TCC_S_CME_0" in identifier:
            return (0, identifier)
        if identifier.endswith("_S_CME_0"):
            return (1, identifier)
        if identifier.endswith("_X_CME_0"):
            return (2, identifier)
        if identifier.endswith("_I_CME_0"):
            return (3, identifier)
        return (4, identifier)

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        return value.astimezone(timezone.utc)


__all__ = [
    "CmeDataMineSpanClient",
    "CmeDataMineSpanDownload",
    "CmeDataMineSpanError",
    "CmeDataMineSpanFile",
    "DEFAULT_CATALOG_PATH",
    "DOWNLOAD_URL",
    "LIST_URL",
    "TOKEN_URL",
]
