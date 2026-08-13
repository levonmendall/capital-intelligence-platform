from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import operations.bounded_terminal_screening as bounded
from operations.provider_enriched_preselection import PROVIDER_PRESELECTION_SCHEMA


NOW = datetime(2026, 8, 12, 23, 0, tzinfo=timezone.utc)


def _write_publication(path, *, sources):
    path.write_text(
        json.dumps(
            {
                "schema_version": PROVIDER_PRESELECTION_SCHEMA,
                "available_at": NOW.isoformat(),
                "source_identifiers": sources,
                "signals": {
                    "ABC": {
                        "observed_at": NOW.isoformat(),
                        "payload": "test",
                    }
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_large_publication_lineage_is_content_addressed_before_chunk_copy(tmp_path):
    publication = tmp_path / "provider-enriched-preselection.json"
    sources = [f"source:{index:04d}:" + ("x" * 256) for index in range(400)]
    _write_publication(publication, sources=sources)
    record = SimpleNamespace(symbol="ABC", provider_symbol="ABC")
    chunk = tmp_path / "chunk.json"

    with bounded._PublicationSignalSpool(publication) as spool:
        retained = tuple(spool.metadata["source_identifiers"])
        assert len(retained) == 1
        manifest = retained[0]
        assert manifest.startswith("provider-publication-source-manifest:sha256:")
        assert manifest.endswith(":count:400")

        spool.chunk_publication((record,), chunk)
        payload = json.loads(chunk.read_text(encoding="utf-8"))
        assert payload["source_identifiers"] == [manifest]
        assert sources[0] not in chunk.read_text(encoding="utf-8")

    # The immutable canonical publication still retains the exact original lineage.
    canonical = json.loads(publication.read_text(encoding="utf-8"))
    assert canonical["source_identifiers"] == sources


def test_small_publication_lineage_remains_verbatim(tmp_path):
    publication = tmp_path / "provider-enriched-preselection.json"
    sources = ["publication:test", "provider:test"]
    _write_publication(publication, sources=sources)

    with bounded._PublicationSignalSpool(publication) as spool:
        assert tuple(spool.metadata["source_identifiers"]) == tuple(sources)


def test_terminal_scratch_sqlite_disables_rollback_journal():
    with bounded._TerminalScreeningStateSpool() as spool:
        assert spool.connection.execute("PRAGMA journal_mode").fetchone()[0] == "off"


def test_storage_reserve_tracks_largest_observed_chunk_growth(tmp_path, monkeypatch):
    current = {"bytes": 1 * 1024 * 1024}

    def fake_footprint(path):
        if str(path).endswith("screening.sqlite3"):
            return current["bytes"]
        return 0

    monkeypatch.setattr(bounded, "_sqlite_footprint", fake_footprint)
    monkeypatch.setattr(
        bounded.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(
            total=8 * 1024**3,
            used=1 * 1024**3,
            free=7 * 1024**3,
        ),
    )

    screening = tmp_path / "screening.sqlite3"
    publication = tmp_path / "publication.json"
    index = tmp_path / "index.sqlite3"

    initial = bounded._storage_metrics(
        publication_path=publication,
        publication_index_path=index,
        screening_spool_path=screening,
    )
    assert initial["storage_reserve_bytes"] == 64 * 1024 * 1024

    current["bytes"] += 100 * 1024 * 1024
    after_growth = bounded._storage_metrics(
        publication_path=publication,
        publication_index_path=index,
        screening_spool_path=screening,
    )
    assert after_growth["storage_reserve_bytes"] >= 416 * 1024 * 1024

    unchanged = bounded._storage_metrics(
        publication_path=publication,
        publication_index_path=index,
        screening_spool_path=screening,
    )
    assert unchanged["storage_reserve_bytes"] == after_growth["storage_reserve_bytes"]
