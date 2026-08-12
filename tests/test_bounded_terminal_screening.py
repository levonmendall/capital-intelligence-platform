from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import operations.bounded_terminal_screening as bounded
from operations.market_discovery_preselection import (
    CatalogScreeningSignal,
    build_cutoff_observations,
    build_preselection_plan,
)
from operations.provider_enriched_preselection import PROVIDER_PRESELECTION_SCHEMA


NOW = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class _Policy:
    provider_preselection_path: str
    required_provider_preselection_factors: tuple[str, ...] = (
        "value",
        "momentum",
        "carry",
        "improving_conditions",
    )
    preselection_shadow_candidates_per_lane: int = 3
    preselection_freshness_days: int = 3
    preselection_minimum_liquidity_score: float = 0.20


def _record(index: int):
    symbol = f"SYM{index:04d}"
    return SimpleNamespace(
        symbol=symbol,
        provider_symbol=symbol,
        economic_exposure=f"sector-{index % 5}",
        venue=f"venue-{index % 3}",
        country_code=f"C{index % 4}",
        currency="USD",
    )


def _signal(index: int, symbol: str) -> CatalogScreeningSignal:
    return CatalogScreeningSignal(
        symbol=symbol,
        observed_at=NOW,
        eligible=index % 11 != 0,
        liquidity_score=0.10 if index % 13 == 0 else 0.80,
        quality_score=round(0.35 + (index % 10) / 20.0, 10),
        value_score=round(0.20 + (index % 7) / 10.0, 10),
        momentum_score=round(0.15 + (index % 8) / 10.0, 10),
        carry_score=None if index % 3 else 0.55,
        improving_conditions_score=round(0.25 + (index % 6) / 10.0, 10),
        indicative_price=100.0 + index,
        evidence_identifiers=(
            f"provider-factor:value:test:v1:{symbol}",
            f"evidence:{symbol}",
        ),
        exclusion_reasons=("fixture_ineligible",) if index % 11 == 0 else (),
    )


def _publication(path, records):
    path.write_text(
        json.dumps(
            {
                "schema_version": PROVIDER_PRESELECTION_SCHEMA,
                "methodology_version": "test.v1",
                "available_at": NOW.isoformat(),
                "catalog_fingerprint": "fixture",
                "catalog_count": len(records),
                "signal_count": len(records),
                "source_identifiers": ["publication:test"],
                "limitations": [],
                "signals": {record.symbol: {} for record in records},
                "decision_authority": False,
                "candidate_authority": False,
                "sizing_authority": False,
                "execution_authority": False,
                "paper_only": True,
                "real_money_authorized": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _install_fixture_signals(monkeypatch, full_signals, observed_chunk_sizes=None):
    def chunk_probe(chunk, _as_of, _policy):
        if observed_chunk_sizes is not None:
            observed_chunk_sizes.append(len(chunk))
        return {record.symbol: full_signals[record.symbol] for record in chunk}

    monkeypatch.setattr(
        bounded,
        "provider_enriched_catalog_screening_signals",
        chunk_probe,
    )
    monkeypatch.setattr(
        bounded,
        "validate_provider_enriched_signals",
        lambda _records, signals, required_factors: signals,
    )
    monkeypatch.setattr(
        bounded,
        "record_manual_cio_diagnostic_progress",
        lambda *_args, **_kwargs: None,
    )


def test_bounded_screening_reproduces_existing_plan_and_cutoff_semantics(
    tmp_path, monkeypatch
):
    records = tuple(_record(index) for index in range(37))
    publication = tmp_path / "provider-enriched-preselection.json"
    _publication(publication, records)
    policy = _Policy(str(publication))
    full_signals = {
        record.symbol: _signal(index, record.symbol)
        for index, record in enumerate(records)
    }
    observed_chunk_sizes: list[int] = []
    _install_fixture_signals(monkeypatch, full_signals, observed_chunk_sizes)

    result = bounded.build_bounded_terminal_preselection(
        records,
        as_of=NOW,
        policy=policy,
        progress_label="international_equity",
        chunk_size=7,
    )
    expected = build_preselection_plan(
        records,
        full_signals,
        as_of=NOW,
        capacity=len(records),
        shadow_limit=policy.preselection_shadow_candidates_per_lane,
        freshness_days=policy.preselection_freshness_days,
        minimum_liquidity_score=policy.preselection_minimum_liquidity_score,
    )

    assert result.plan == expected
    assert max(observed_chunk_sizes) == 7
    assert len(observed_chunk_sizes) > 1
    assert result.screened_signal_count == len(records)
    assert result.provider_factor_authority_established is True
    assert result.nominated == tuple(
        next(record for record in records if record.symbol == symbol)
        for symbol in expected.selected_symbols
    )
    assert result.signal_prices == {
        symbol: signal.indicative_price
        for symbol, signal in full_signals.items()
        if signal.indicative_price is not None
    }
    assert result.signal_observed_at == {
        symbol: full_signals[symbol].observed_at
        for symbol in expected.selected_symbols
    }
    expected_evidence = tuple(
        (symbol, full_signals[symbol].evidence_identifiers)
        for symbol in expected.selected_symbols
    )
    assert result.preselection_evidence == expected_evidence
    assert not isinstance(result.preselection_evidence, tuple)

    selected_prices = {
        symbol: 1000.0 + index
        for index, symbol in enumerate(expected.selected_symbols)
    }
    actual_observations = bounded.build_bounded_cutoff_observations(
        result,
        asset_class="international_equity",
        selected_prices=selected_prices,
    )
    expected_observations = build_cutoff_observations(
        expected,
        asset_class="international_equity",
        signals=full_signals,
        selected_prices={**result.signal_prices, **selected_prices},
    )
    assert actual_observations == expected_observations


def test_streamed_screening_is_chunk_size_invariant(tmp_path, monkeypatch):
    records = tuple(_record(index) for index in range(97))
    publication = tmp_path / "provider-enriched-preselection.json"
    _publication(publication, records)
    policy = _Policy(str(publication))
    full_signals = {
        record.symbol: _signal(index, record.symbol)
        for index, record in enumerate(records)
    }
    _install_fixture_signals(monkeypatch, full_signals)

    single_record_chunks = bounded.build_bounded_terminal_preselection(
        records,
        as_of=NOW,
        policy=policy,
        progress_label="international_equity",
        chunk_size=1,
    )
    wider_chunks = bounded.build_bounded_terminal_preselection(
        records,
        as_of=NOW,
        policy=policy,
        progress_label="international_equity",
        chunk_size=31,
    )

    assert single_record_chunks == wider_chunks


def test_finalization_phases_are_durably_observable(tmp_path, monkeypatch):
    records = tuple(_record(index) for index in range(21))
    publication = tmp_path / "provider-enriched-preselection.json"
    _publication(publication, records)
    policy = _Policy(str(publication))
    full_signals = {
        record.symbol: _signal(index, record.symbol)
        for index, record in enumerate(records)
    }
    _install_fixture_signals(monkeypatch, full_signals)
    stages: list[str] = []
    monkeypatch.setattr(
        bounded,
        "record_manual_cio_diagnostic_progress",
        lambda stage, **_kwargs: stages.append(stage),
    )

    bounded.build_bounded_terminal_preselection(
        records,
        as_of=NOW,
        policy=policy,
        progress_label="international_equity",
        chunk_size=5,
    )

    assert stages[-5:] == [
        "terminal_screening_finalize_release:international_equity",
        "terminal_screening_finalize_diversification:international_equity",
        "terminal_screening_finalize_rankings:international_equity",
        "terminal_screening_finalize_selection:international_equity",
        "terminal_screening_finalize_plan:international_equity",
    ]


def test_terminal_screening_state_spool_keeps_record_state_out_of_python_heap():
    with bounded._TerminalScreeningStateSpool() as spool:
        assert not hasattr(spool, "__dict__")
        assert spool.connection.execute("PRAGMA temp_store").fetchone()[0] == 1
        assert spool.connection.execute("PRAGMA cache_size").fetchone()[0] == -2048
        tables = {
            row[0]
            for row in spool.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"screened", "exclusions"}.issubset(tables)


def test_publication_signal_spool_indexes_canonical_json_without_full_signal_mapping(
    tmp_path,
):
    records = tuple(_record(index) for index in range(41))
    publication = tmp_path / "provider-enriched-preselection.json"
    _publication(publication, records)

    with bounded._PublicationSignalSpool(publication) as spool:
        assert spool.signal_count == len(records)
        assert spool.metadata["schema_version"] == PROVIDER_PRESELECTION_SCHEMA
        selected = spool.signals_for((records[0], records[17], records[-1]))
        assert tuple(selected) == (
            records[0].symbol,
            records[17].symbol,
            records[-1].symbol,
        )
        row_count = spool.connection.execute(
            "SELECT COUNT(*) FROM signals"
        ).fetchone()[0]
        assert row_count == len(records)
