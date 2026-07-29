"""Small credential-safe HTTP client built only on the Python standard library."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class HttpResponse:
    url: str
    status: int
    headers: Mapping[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


class HttpClient:
    def __init__(self, *, user_agent: str, timeout_seconds: int = 30, attempts: int = 3) -> None:
        if not user_agent.strip():
            raise ValueError("user_agent is required")
        self.user_agent = user_agent.strip()
        self.timeout_seconds = timeout_seconds
        self.attempts = attempts

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        if params:
            query = urllib.parse.urlencode({key: value for key, value in params.items() if value is not None})
            url = f"{url}{'&' if '?' in url else '?'}{query}"
        request_headers = {"User-Agent": self.user_agent, "Accept": "application/json,text/csv,*/*"}
        request_headers.update(dict(headers or {}))
        request = urllib.request.Request(url, headers=request_headers, method="GET")
        last_error: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    return HttpResponse(
                        url=response.geturl(),
                        status=int(response.status),
                        headers=dict(response.headers.items()),
                        body=response.read(),
                    )
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                status = getattr(exc, "code", None)
                if attempt >= self.attempts or status in {400, 401, 403, 404}:
                    break
                time.sleep(min(2 ** (attempt - 1), 4))
        raise RuntimeError(f"HTTP GET failed for {urllib.parse.urlsplit(url).netloc}") from last_error
