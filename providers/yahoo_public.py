"""Cookie-backed public Yahoo market-data session.

Yahoo's chart endpoint is generally anonymous, while option-chain requests may require
an HTTP session cookie plus a short-lived crumb.  This adapter centralizes that protocol,
retries one authorization failure with a fresh cookie/crumb pair, and never persists
cookies or crumb material outside process memory.
"""

from __future__ import annotations

from typing import Any, Mapping

import requests


class YahooPublicProviderError(RuntimeError):
    """Raised when public Yahoo evidence cannot be retrieved safely."""


class YahooPublicSession:
    """Bounded in-memory Yahoo session supporting crumb-protected JSON endpoints."""

    COOKIE_URL = "https://fc.yahoo.com"
    CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: int = 20,
        user_agent: str = "capital-intelligence-paper-research/1.0",
    ) -> None:
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
            raise TypeError("timeout_seconds must be an integer")
        if timeout_seconds < 1 or timeout_seconds > 120:
            raise ValueError("timeout_seconds must be between 1 and 120")
        normalized_agent = str(user_agent).strip()
        if not normalized_agent:
            raise ValueError("user_agent cannot be empty")
        self._session = session or requests.Session()
        self._timeout_seconds = timeout_seconds
        self._headers = {"User-Agent": normalized_agent}
        self._crumb: str | None = None

    def _get(self, url: str, **kwargs: Any):
        return self._session.get(
            url,
            headers=self._headers,
            timeout=self._timeout_seconds,
            **kwargs,
        )

    def _refresh_crumb(self) -> str:
        self._crumb = None
        try:
            # The response itself may be 404; its purpose is establishing Yahoo's
            # short-lived session cookie for the subsequent crumb request.
            self._get(self.COOKIE_URL, allow_redirects=True)
            response = self._get(self.CRUMB_URL, allow_redirects=True)
        except requests.RequestException as error:
            raise YahooPublicProviderError(
                f"Yahoo cookie/crumb session failed: {type(error).__name__}"
            ) from error
        status = int(getattr(response, "status_code", 0))
        if status < 200 or status >= 300:
            raise YahooPublicProviderError(f"Yahoo crumb HTTP {status}")
        crumb = str(getattr(response, "text", "")).strip()
        if (
            not crumb
            or len(crumb) > 256
            or crumb.startswith("<")
            or "too many requests" in crumb.lower()
        ):
            raise YahooPublicProviderError("Yahoo returned an invalid crumb")
        self._crumb = crumb
        return crumb

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, object] | None = None,
        require_crumb: bool = False,
    ) -> Mapping[str, Any]:
        """Retrieve one JSON object, refreshing crumb once after HTTP 401/403."""

        base_params = dict(params or {})
        attempts = 2 if require_crumb else 1
        for attempt in range(attempts):
            request_params = dict(base_params)
            if require_crumb:
                request_params["crumb"] = self._crumb or self._refresh_crumb()
            try:
                response = self._get(
                    url,
                    params=request_params,
                    allow_redirects=True,
                )
            except requests.RequestException as error:
                raise YahooPublicProviderError(
                    f"Yahoo request failed: {type(error).__name__}"
                ) from error
            status = int(getattr(response, "status_code", 0))
            if require_crumb and status in {401, 403} and attempt == 0:
                self._refresh_crumb()
                continue
            if status < 200 or status >= 300:
                raise YahooPublicProviderError(f"Yahoo HTTP {status}")
            try:
                payload = response.json()
            except (TypeError, ValueError) as error:
                raise YahooPublicProviderError(
                    "Yahoo returned invalid JSON"
                ) from error
            if not isinstance(payload, Mapping):
                raise YahooPublicProviderError(
                    "Yahoo returned a non-object JSON payload"
                )
            return payload
        raise YahooPublicProviderError("Yahoo authorization retry was exhausted")


__all__ = ["YahooPublicProviderError", "YahooPublicSession"]
