from __future__ import annotations

from datetime import datetime, timedelta, timezone

from provider_preselection_checkpoint_bootstrap import (
    _DurableSignalStore,
    _MAX_CHECKPOINT_AGE_SECONDS,
    _checkpoint_path,
    _install_publication_patch,
    _is_epoch_provider_child,
)


def _epoch() -> datetime:
    return datetime(2026, 9, 1, 17, 43, 15, tzinfo=timezone.utc)


def test_bootstrap_activates_only_for_epoch_provider_child() -> None:
    prefix = ("/usr/local/bin/python", "-m", "operations.epoch_scoped_provider_acquisition")

    assert _is_epoch_provider_child(prefix + ("--request", "request.json", "--asset-class", "international_equity", "--index", "4")) is True
    assert _is_epoch_provider_child(prefix + ("--prepare-structure", "--request", "request.json", "--asset-class", "international_equity", "--index", "4")) is False
    assert _is_epoch_provider_child(("/usr/local/bin/python", "-m", "operations.transactional_comprehensive_discovery_lane")) is False
    assert _is_epoch_provider_child(("/usr/local/bin/python", "-c", "print('x')")) is False


def test_checkpoint_path_is_sibling_of_exact_staging_publication(tmp_path) -> None:
    staging = tmp_path / "provider-preselection-004-international_equity.json.fanout"
    assert _checkpoint_path(staging) == tmp_path / (
        "provider-preselection-004-international_equity.json.fanout."
        "exchange-checkpoint.sqlite3"
    )


def test_durable_store_resumes_committed_exchange_with_same_fingerprint(tmp_path) -> None:
    from operations import bounded_provider_preselection_publication as publication

    path = tmp_path / "signals.sqlite3"
    first = _DurableSignalStore(
        path,
        catalog_fingerprint="fingerprint-a",
        as_of=_epoch(),
        publication_error=publication.ProviderPreselectionPublicationError,
    )
    first.put("ABC", {"score": 1.0, "available_at": _epoch().isoformat()})
    first.add_source("provider:exchange:X")
    first.mark_exchange_completed("X")
    first.commit()
    first.close()

    resumed = _DurableSignalStore(
        path,
        catalog_fingerprint="fingerprint-a",
        as_of=_epoch() + timedelta(minutes=7),
        publication_error=publication.ProviderPreselectionPublicationError,
    )
    assert resumed.contains("ABC") is True
    assert resumed.signal_count == 1
    assert tuple(resumed.iter_sources()) == ("provider:exchange:X",)
    assert resumed.exchange_completed("X") is True
    resumed.close()


def test_durable_store_resets_on_catalog_change_or_freshness_expiry(tmp_path) -> None:
    from operations import bounded_provider_preselection_publication as publication

    path = tmp_path / "signals.sqlite3"
    first = _DurableSignalStore(
        path,
        catalog_fingerprint="fingerprint-a",
        as_of=_epoch(),
        publication_error=publication.ProviderPreselectionPublicationError,
    )
    first.put("ABC", {"score": 1.0})
    first.mark_exchange_completed("X")
    first.commit()
    first.close()

    changed = _DurableSignalStore(
        path,
        catalog_fingerprint="fingerprint-b",
        as_of=_epoch() + timedelta(minutes=1),
        publication_error=publication.ProviderPreselectionPublicationError,
    )
    assert changed.signal_count == 0
    assert changed.exchange_completed("X") is False
    changed.put("XYZ", {"score": 2.0})
    changed.mark_exchange_completed("Y")
    changed.commit()
    changed.close()

    expired = _DurableSignalStore(
        path,
        catalog_fingerprint="fingerprint-b",
        as_of=_epoch() + timedelta(seconds=_MAX_CHECKPOINT_AGE_SECONDS + 61),
        publication_error=publication.ProviderPreselectionPublicationError,
    )
    assert expired.signal_count == 0
    assert expired.exchange_completed("Y") is False
    expired.close()
    assert _MAX_CHECKPOINT_AGE_SECONDS == 900.0


def test_installed_exchange_wrapper_durably_skips_completed_snapshot(monkeypatch, tmp_path) -> None:
    from operations import bounded_provider_preselection_publication as publication

    original_store = publication._SignalStore
    original_insert = publication._insert_exchange_signals
    original_ensure = publication.ensure_provider_preselection_publication
    had_installed = hasattr(publication, "_resumable_exchange_checkpoint_installed")
    original_installed = getattr(publication, "_resumable_exchange_checkpoint_installed", False)
    calls: list[str] = []

    def fake_insert(store, *, exchange, members, as_of, api_token, http_get):
        calls.append(str(exchange))
        store.put("ABC", {"score": 1.0})
        store.add_source(f"provider:exchange:{exchange}")
        return None

    monkeypatch.setattr(publication, "_insert_exchange_signals", fake_insert)
    publication._resumable_exchange_checkpoint_installed = False
    _install_publication_patch()
    wrapped_insert = publication._insert_exchange_signals

    path = tmp_path / "signals.sqlite3"
    store = _DurableSignalStore(
        path,
        catalog_fingerprint="fingerprint-a",
        as_of=_epoch(),
        publication_error=publication.ProviderPreselectionPublicationError,
    )
    assert wrapped_insert(
        store,
        exchange="X",
        members=(),
        as_of=_epoch(),
        api_token="token",
        http_get=object(),
    ) is None
    assert calls == ["X"]
    assert store.exchange_completed("X") is True
    store.close()

    resumed = _DurableSignalStore(
        path,
        catalog_fingerprint="fingerprint-a",
        as_of=_epoch() + timedelta(minutes=2),
        publication_error=publication.ProviderPreselectionPublicationError,
    )
    assert wrapped_insert(
        resumed,
        exchange="X",
        members=(),
        as_of=_epoch() + timedelta(minutes=2),
        api_token="token",
        http_get=object(),
    ) is None
    assert calls == ["X"]
    assert resumed.contains("ABC") is True
    resumed.close()

    publication._SignalStore = original_store
    publication._insert_exchange_signals = original_insert
    publication.ensure_provider_preselection_publication = original_ensure
    if had_installed:
        publication._resumable_exchange_checkpoint_installed = original_installed
    else:
        delattr(publication, "_resumable_exchange_checkpoint_installed")
