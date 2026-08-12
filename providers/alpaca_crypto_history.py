"""Batched authenticated Alpaca crypto history for all-market evidence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence

import requests

from providers.alpaca_paper import AlpacaPaperSettings


class AlpacaCryptoHistoryError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


def _symbol(value: str) -> str:
    normalized = str(value).strip().upper()
    if "/" in normalized:
        return normalized
    if "-" in normalized:
        left, right = normalized.rsplit("-", 1)
        if left and right:
            return f"{left}/{right}"
    return normalized


class AlpacaCryptoHistoryProvider:
    """Retrieve multiple crypto symbols in one paginated Alpaca request stream."""

    def __init__(self, settings: AlpacaPaperSettings | None = None, *, location: str = "us", http_get: Callable[..., Any] = requests.get) -> None:
        if settings is not None:
            candidates = (settings,)
        else:
            try:
                candidates = tuple(candidate for _label, candidate in AlpacaPaperSettings.candidates_from_env())
            except ValueError:
                candidates = ()
        self._settings_candidates = candidates
        self._http_get = http_get
        self.location = str(location).strip().lower() or "us"

    @property
    def configured(self) -> bool:
        return bool(self._settings_candidates)

    def daily_history_many(self, symbols: Sequence[str], *, as_of: datetime, history_days: int) -> Mapping[str, tuple[dict[str, object], ...]]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        normalized = tuple(dict.fromkeys(_symbol(item) for item in symbols if str(item).strip()))
        if not normalized:
            return {}
        if not self.configured:
            raise AlpacaCryptoHistoryError("Alpaca credentials are not configured")
        cutoff = as_of.astimezone(timezone.utc)
        start = cutoff - timedelta(days=history_days)
        last_auth_status: int | None = None
        for settings in self._settings_candidates:
            rows: dict[str, list[dict[str, object]]] = {symbol: [] for symbol in normalized}
            token: str | None = None
            try:
                for _page in range(200):
                    params: dict[str, object] = {
                        "symbols": ",".join(normalized),
                        "timeframe": "1Day",
                        "start": start.isoformat(),
                        "end": cutoff.isoformat(),
                        "limit": 10_000,
                        "sort": "asc",
                    }
                    if token:
                        params["page_token"] = token
                    response = self._http_get(
                        settings.data_base_url.rstrip("/") + f"/v1beta3/crypto/{self.location}/bars",
                        headers={
                            "APCA-API-KEY-ID": settings.api_key_id,
                            "APCA-API-SECRET-KEY": settings.secret_key,
                            "Accept": "application/json",
                        },
                        params=params,
                        timeout=settings.timeout_seconds,
                    )
                    status = int(getattr(response, "status_code", 0))
                    if status in {401, 403}:
                        last_auth_status = status
                        raise PermissionError(status)
                    if not 200 <= status < 300:
                        raise AlpacaCryptoHistoryError(
                            f"Alpaca crypto history returned HTTP {status or 'unknown'}",
                            status_code=status or None,
                            retryable=status in {408, 425, 429} or 500 <= status <= 599,
                        )
                    payload = response.json()
                    if not isinstance(payload, Mapping):
                        raise AlpacaCryptoHistoryError("Alpaca crypto history response must be an object")
                    raw_bars = payload.get("bars")
                    if not isinstance(raw_bars, Mapping):
                        raise AlpacaCryptoHistoryError("Alpaca crypto history response is missing bars")
                    for symbol in normalized:
                        values = raw_bars.get(symbol, ())
                        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                            continue
                        for item in values:
                            if not isinstance(item, Mapping):
                                continue
                            try:
                                observed = datetime.fromisoformat(str(item.get("t")).replace("Z", "+00:00")).astimezone(timezone.utc)
                                close = float(item.get("c"))
                                volume = max(0.0, float(item.get("v", 0.0)))
                            except (TypeError, ValueError):
                                continue
                            if observed <= cutoff and close > 0.0:
                                rows[symbol].append({"t": observed, "c": close, "v": volume})
                    raw_token = payload.get("next_page_token")
                    token = str(raw_token).strip() if raw_token else None
                    if not token:
                        break
                return {symbol: tuple(sorted(values, key=lambda item: item["t"])) for symbol, values in rows.items()}
            except PermissionError:
                continue
            except requests.RequestException as error:
                raise AlpacaCryptoHistoryError("Alpaca crypto history request failed", retryable=True) from error
        raise AlpacaCryptoHistoryError("Alpaca crypto history authentication is unavailable", status_code=last_auth_status)

    def daily_history(self, symbol: str, *, as_of: datetime, history_days: int) -> tuple[dict[str, object], ...]:
        normalized = _symbol(symbol)
        return tuple(self.daily_history_many((normalized,), as_of=as_of, history_days=history_days).get(normalized, ()))


__all__ = ["AlpacaCryptoHistoryError", "AlpacaCryptoHistoryProvider"]
