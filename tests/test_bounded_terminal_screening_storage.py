from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import operations.bounded_terminal_screening as bounded
from operations.market_discovery_preselection import CatalogScreeningSignal
from operations.provider_enriched_preselection import PROVIDER_PRESELECTION_SCHEMA


NOW = datetime(2026, 8, 12, 21, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class _Policy:
    provider_preselection_path: str
    required_provider_preselection_factors: tuple[str, ...] = (
        "value",
        "momentum",
        "carry",
        "improving_conditions",
    )
    preselection_freshness_days: int = 3
    preselection_minimum_liquidity_score: float = 0.20


def _record(index: int):
    symbol = f"SYM{index:04d}"
    return SimpleNamespace(
        symbol=symbol,
        provider_symbol=symbol,
        economic_exposure=f"sector-{index % 3}",
        venue="test",
        country_code="US",
        currency="USD",
    )


def _write_publication(path, payloads):
    path.write_text(
        json.dumps(
            {
                "schema_version": PROVIDER_PRESELECTION_SCHEMA,
                "available_at": NOW.isoformat(),
                "source_identifiers": ["publication:test"],
                "signals": payloads,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _signal(symbol: str) -> CatalogScreeningSignal:
    return CatalogScreeningSignal(
        symbol=symbol,
        observed_at=NOW,
        eligible=True,
        liquidity_score=0.90,
        quality_score=0.70,
        value_score=0.60,
        momentum_score=0.50,
        carry_score=0.40,
        improving_conditions_score=0.80,
        indicative_price=100.0,
        evidence_identifiers=(
            f"provider-factor:value:test:v1:{symbol}",
            f"evidence:{symbol}",
        ),
        exclusion_reasons=(),
    )


def test_publication_signal_spool_indexes_byte_ranges_without_payload_duplication(tmp_path):
    records = tuple(_record(index) for index in range(8))
    payloads = {
        record.symbol: {
            "evidence": "x" * 50_000,
            "nested": {"symbol": record.symbol, "values": list(range(10))},
        }
        for record in records
    }
    publication = tmp_path / "provider-enriched-preselection.json"
    _write_publication(publication, payloads)

    with bounded._PublicationSignalSpool(publication) as spool:
        columns = tuple(
            row[1] for row in spool.connection.execute("PRAGMA table_info(signals)")
        )
        assert columns == ("symbol", "payload_offset", "payload_length")
        assert spool.connection.execute("PRAGMA journal_mode").fetchone()[0] == "off"
        selected = spool.signals_for((records[0], records[4], records[-1]))
        assert selected == {
            records[0].symbol: payloads[records[0].symbol],
            records[4].symbol: payloads[records[4].symbol],
            records[-1].symbol: payloads[records[-1].symbol],
        }
        assert spool.database_path.stat().st_size < publication.stat().st_size // 4


def test_terminal_screening_chunk_progress_includes_storage_telemetry(
    tmp_path, monkeypatch
):
    records = tuple(_record(index) for index in range(7))
    publication = tmp_path / "provider-enriched-preselection.json"
    _write_publication(publication, {record.symbol: {} for record in records})
    policy = _Policy(str(publication))
    signals = {record.symbol: _signal(record.symbol) for record in records}
    events: list[tuple[str, dict[str, int]]] = []

    monkeypatch.setattr(
        bounded,
        "provider_enriched_catalog_screening_signals",
        lambda chunk, _as_of, _policy: {record.symbol: signals[record.symbol] for record in chunk},
    )
    monkeypatch.setattr(
        bounded,
        "validate_provider_enriched_signals",
        lambda _records, values, required_factors: values,
    )
    monkeypatch.setattr(
        bounded,
        "record_manual_cio_diagnostic_progress",
        lambda stage, **kwargs: events.append((stage, dict(kwargs.get("metrics", {})))),
    )

    result = bounded.build_bounded_terminal_preselection(
        records,
        as_of=NOW,
        policy=policy,
        progress_label="international_equity",
        chunk_size=3,
    )

    assert result.screened_signal_count == len(records)
    chunk_metrics = [
        metrics
        for stage, metrics in events
        if stage == "terminal_screening_chunk:international_equity"
    ]
    assert chunk_metrics
    for metrics in chunk_metrics:
        assert metrics["publication_bytes"] > 0
        assert metrics["publication_index_bytes"] > 0
        assert metrics["screening_spool_bytes"] > 0
        assert metrics["chunk_file_bytes"] == 0
        assert metrics["storage_total_bytes"] > 0
        assert metrics["storage_free_bytes"] >= 0
        assert metrics["storage_reserve_bytes"] == 64 * 1024 * 1024


def test_terminal_screening_fails_closed_before_storage_reserve_is_consumed(
    tmp_path, monkeypatch
):
    records = (_record(0),)
    publication = tmp_path / "provider-enriched-preselection.json"
    _write_publication(publication, {records[0].symbol: {}})
    policy = _Policy(str(publication))

    monkeypatch.setattr(
        bounded.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=1000, used=999, free=1),
    )
    monkeypatch.setenv("MANUAL_CIO_SERVICE_STORAGE_RESERVE_MB", "64")

    with pytest.raises(
        bounded.BoundedTerminalScreeningError,
        match="storage reserve exhausted before filesystem capacity failure",
    ):
        bounded.build_bounded_terminal_preselection(
            records,
            as_of=NOW,
            policy=policy,
            progress_label="international_equity",
            chunk_size=1,
        )
