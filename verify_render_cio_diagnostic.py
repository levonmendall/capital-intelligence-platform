"""Poll and verify the public, redacted Render CIO diagnostic audit."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any


_FINAL_STATES = frozenset({"completed", "failed"})
_FORBIDDEN_KEYS = frozenset(
    {
        "holdings",
        "positions",
        "target_weights",
        "candidate_symbols",
        "recommendations",
        "provider_payloads",
        "provider_records",
        "api_key",
        "api_token",
        "access_token",
        "secret",
    }
)


class RenderAuditVerificationError(RuntimeError):
    """Raised when the deployed audit is unavailable, stale, or incomplete."""


def _fetch_json(url: str, *, timeout_seconds: float = 20.0) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "capital-intelligence-render-audit-verifier/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise RenderAuditVerificationError("Render audit must encode a JSON object")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _walk_keys(value: object) -> tuple[str, ...]:
    keys: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            keys.append(str(key).strip().lower())
            keys.extend(_walk_keys(item))
    elif isinstance(value, list | tuple):
        for item in value:
            keys.extend(_walk_keys(item))
    return tuple(keys)


def audit_is_current_and_final(
    payload: Mapping[str, Any],
    *,
    expected_release: str,
) -> bool:
    return all(
        (
            str(payload.get("active_release") or "") == expected_release,
            payload.get("release_matches") is True,
            str(payload.get("state") or "") in _FINAL_STATES,
            bool(payload.get("completed_at")),
            payload.get("credential_safe") is True,
            payload.get("paper_only") is True,
            payload.get("real_money_authorized") is False,
        )
    )


def poll_render_audit(
    *,
    url: str,
    expected_release: str,
    output_path: Path,
    maximum_attempts: int = 120,
    interval_seconds: float = 15.0,
    fetcher: Callable[[str], Mapping[str, Any]] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> Mapping[str, Any]:
    if not url.strip():
        raise ValueError("url cannot be empty")
    if not expected_release.strip():
        raise ValueError("expected_release cannot be empty")
    if maximum_attempts < 1:
        raise ValueError("maximum_attempts must be positive")
    if interval_seconds < 0:
        raise ValueError("interval_seconds cannot be negative")
    active_fetcher = fetcher or (lambda target: _fetch_json(target))
    last_detail = "the audit endpoint did not return a current release record"
    for attempt in range(1, maximum_attempts + 1):
        try:
            payload = active_fetcher(url)
            _write_json(output_path, payload)
        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            urllib.error.URLError,
            RenderAuditVerificationError,
        ) as error:
            last_detail = f"{type(error).__name__}: {error}"
        else:
            if audit_is_current_and_final(
                payload,
                expected_release=expected_release,
            ):
                return payload
            last_detail = (
                "audit is not current and final: "
                f"active_release={payload.get('active_release')!r}, "
                f"release_matches={payload.get('release_matches')!r}, "
                f"state={payload.get('state')!r}"
            )
        if attempt < maximum_attempts:
            sleeper(interval_seconds)
    raise RenderAuditVerificationError(
        "Render CIO diagnostic did not publish a current final audit after "
        f"{maximum_attempts} attempts; last_detail={last_detail}"
    )


def verify_complete_all_market_evaluation(
    payload: Mapping[str, Any],
    *,
    expected_release: str,
) -> None:
    if not audit_is_current_and_final(payload, expected_release=expected_release):
        raise RenderAuditVerificationError(
            "audit does not belong to the expected final deployed release"
        )
    forbidden = sorted(_FORBIDDEN_KEYS.intersection(_walk_keys(payload)))
    if forbidden:
        raise RenderAuditVerificationError(
            "public audit contains forbidden fields: " + ", ".join(forbidden)
        )
    required_true = (
        "ready",
        "context_cycle_matches",
        "comprehensive_discovery_required",
        "comprehensive_discovery_complete",
        "scheduled_market_coverage_complete",
        "terminal_screening_complete",
        "all_market_evaluation_complete",
    )
    failed = tuple(name for name in required_true if payload.get(name) is not True)
    lanes = payload.get("market_lanes")
    scheduled_lanes = (
        tuple(
            item
            for item in lanes
            if isinstance(item, Mapping) and item.get("scheduled") is True
        )
        if isinstance(lanes, list)
        else ()
    )
    unrepresented = tuple(
        str(item.get("asset_class") or "unknown")
        for item in scheduled_lanes
        if item.get("represented") is not True
    )
    if not scheduled_lanes:
        failed = (*failed, "scheduled_market_lanes_present")
    if unrepresented:
        failed = (*failed, "unrepresented_market_lanes=" + ",".join(unrepresented))
    if failed:
        detail = str(payload.get("detail") or "no diagnostic detail was published")
        limitations = payload.get("comprehensive_discovery_limitations")
        raise RenderAuditVerificationError(
            "all-market CIO evaluation failed closed; failed="
            + ", ".join(failed)
            + f"; detail={detail}; limitations={limitations!r}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--expected-release", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--maximum-attempts", type=int, default=120)
    parser.add_argument("--interval-seconds", type=float, default=15.0)
    args = parser.parse_args(argv)
    try:
        payload = poll_render_audit(
            url=args.url,
            expected_release=args.expected_release,
            output_path=args.output,
            maximum_attempts=args.maximum_attempts,
            interval_seconds=args.interval_seconds,
        )
        verify_complete_all_market_evaluation(
            payload,
            expected_release=args.expected_release,
        )
    except (OSError, TypeError, ValueError, RenderAuditVerificationError) as error:
        print(
            json.dumps(
                {
                    "event": "render_cio_diagnostic_verification_failed",
                    "error_type": type(error).__name__,
                    "detail": str(error)[:4000],
                    "expected_release": args.expected_release,
                    "paper_only": True,
                    "real_money_authorized": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return 3
    print(
        json.dumps(
            {
                "event": "render_cio_diagnostic_verified",
                "expected_release": args.expected_release,
                "all_market_evaluation_complete": True,
                "paper_only": True,
                "real_money_authorized": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
