"""Dependency-free Prometheus-compatible process metrics."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class MetricRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}

    @staticmethod
    def _key(name: str, labels: dict[str, str] | None) -> tuple[str, tuple[tuple[str, str], ...]]:
        if not name or not name.replace("_", "").isalnum():
            raise ValueError("metric name must be alphanumeric with underscores")
        return name, tuple(sorted((labels or {}).items()))

    def increment(
        self,
        name: str,
        value: float = 1.0,
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        if value < 0:
            raise ValueError("counter increments cannot be negative")
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] += float(value)

    def set_gauge(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._gauges[key] = float(value)

    def observe_request(self, method: str, route: str, status: int, duration_seconds: float) -> None:
        labels = {
            "method": method.upper(),
            "route": route or "unknown",
            "status": str(status),
        }
        self.increment("capital_intelligence_http_requests_total", labels=labels)
        self.increment(
            "capital_intelligence_http_request_duration_seconds_sum",
            max(0.0, duration_seconds),
            labels={"method": method.upper(), "route": route or "unknown"},
        )

    def render(self) -> str:
        with self._lock:
            values = [*self._counters.items(), *self._gauges.items()]
        lines: list[str] = []
        for (name, labels), value in sorted(values):
            suffix = ""
            if labels:
                rendered = ",".join(f'{key}="{_escape(value)}"' for key, value in labels)
                suffix = "{" + rendered + "}"
            lines.append(f"{name}{suffix} {value:g}")
        return "\n".join(lines) + ("\n" if lines else "")


__all__ = ["MetricRegistry"]
