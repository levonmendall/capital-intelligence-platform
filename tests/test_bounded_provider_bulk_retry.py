from __future__ import annotations

from datetime import datetime, timezone

from operations import bounded_provider_preselection_publication as publication


EPOCH = datetime(2026, 8, 31, 23, 42, 50, tzinfo=timezone.utc)


class _Store:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def test_transient_bulk_failure_retries_only_failed_exchange(monkeypatch) -> None:
    store = _Store()
    calls: list[str] = []
    progress: list[tuple[str, dict[str, int]]] = []
    sleeps: list[float] = []

    grouped = {
        "LSE": ((object(), "AAA"),),
        "TO": ((object(), "BBB"),),
    }

    def insert(_store, *, exchange, members, as_of, api_token, http_get):
        del _store, members, as_of, api_token, http_get
        calls.append(exchange)
        if exchange == "LSE" and calls.count("LSE") == 1:
            return "EODHD bulk EOD snapshot is unavailable for LSE: HTTP 429"
        return None

    monkeypatch.setattr(publication, "_insert_exchange_signals", insert)
    monkeypatch.setattr(
        publication._runtime,
        "record_manual_cio_diagnostic_progress",
        lambda stage, metrics=None: progress.append((stage, dict(metrics or {}))),
    )
    monkeypatch.setattr(publication.time, "sleep", sleeps.append)

    limitations = publication._collect_exchange_signals_with_retries(
        store,
        grouped=grouped,
        as_of=EPOCH,
        api_token="token",
        http_get=object(),
    )

    assert limitations == ()
    assert calls == ["LSE", "TO", "LSE"]
    assert progress == [
        (
            "provider_preselection_bulk_retry",
            {"retry_round": 1, "failed_exchanges": 1},
        )
    ]
    assert sleeps == [publication._BULK_RETRY_SLEEP_SECONDS]
    assert store.commits == 1


def test_entitlement_failure_is_not_retried(monkeypatch) -> None:
    store = _Store()
    calls: list[str] = []

    def insert(_store, *, exchange, members, as_of, api_token, http_get):
        del _store, members, as_of, api_token, http_get
        calls.append(exchange)
        return "EODHD bulk EOD entitlement is unavailable for LSE (HTTP 403)"

    monkeypatch.setattr(publication, "_insert_exchange_signals", insert)
    monkeypatch.setattr(
        publication._runtime,
        "record_manual_cio_diagnostic_progress",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("entitlement failure must not enter retry loop")
        ),
    )
    monkeypatch.setattr(
        publication.time,
        "sleep",
        lambda _seconds: (_ for _ in ()).throw(
            AssertionError("entitlement failure must not sleep")
        ),
    )

    limitations = publication._collect_exchange_signals_with_retries(
        store,
        grouped={"LSE": ((object(), "AAA"),)},
        as_of=EPOCH,
        api_token="token",
        http_get=object(),
    )

    assert limitations == (
        "EODHD bulk EOD entitlement is unavailable for LSE (HTTP 403)",
    )
    assert calls == ["LSE"]
    assert store.commits == 0


def test_persistent_transient_failure_stays_limited_after_bounded_rounds(monkeypatch) -> None:
    store = _Store()
    calls: list[str] = []
    sleeps: list[float] = []

    def insert(_store, *, exchange, members, as_of, api_token, http_get):
        del _store, members, as_of, api_token, http_get
        calls.append(exchange)
        return "EODHD bulk EOD snapshot is unavailable for LSE: HTTP 500"

    monkeypatch.setattr(publication, "_insert_exchange_signals", insert)
    monkeypatch.setattr(
        publication._runtime,
        "record_manual_cio_diagnostic_progress",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(publication.time, "sleep", sleeps.append)

    limitations = publication._collect_exchange_signals_with_retries(
        store,
        grouped={"LSE": ((object(), "AAA"),)},
        as_of=EPOCH,
        api_token="token",
        http_get=object(),
    )

    assert limitations == (
        "EODHD bulk EOD snapshot is unavailable for LSE: HTTP 500",
    )
    assert len(calls) == publication._BULK_RETRY_ROUNDS + 1
    assert len(sleeps) == publication._BULK_RETRY_ROUNDS
    assert store.commits == publication._BULK_RETRY_ROUNDS
    assert publication._BULK_RETRY_ROUNDS == 2
