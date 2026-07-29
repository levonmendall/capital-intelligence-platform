"""Append-only compressed historical evidence store with deduplication and checkpoints."""

from __future__ import annotations

import gzip
import json
import os
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from .models import HistoricalRecord, canonical_json, parse_timestamp


class HistoricalStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.records_root = self.root / "records"
        self.checkpoint_root = self.root / "checkpoints"
        self.manifest_root = self.root / "manifests"
        for path in (self.records_root, self.checkpoint_root, self.manifest_root):
            path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe(value: str) -> str:
        return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value)

    def partition_path(self, record: HistoricalRecord) -> Path:
        year = parse_timestamp(record.observed_at).year
        return (
            self.records_root
            / self._safe(record.source)
            / self._safe(record.dataset)
            / f"year={year}"
            / "records.jsonl.gz"
        )

    def _known_ids(self, path: Path) -> set[str]:
        if not path.exists():
            return set()
        ids: set[str] = set()
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    ids.add(str(json.loads(line)["record_id"]))
                except (KeyError, TypeError, json.JSONDecodeError) as exc:
                    raise RuntimeError(f"corrupt historical partition: {path}") from exc
        return ids

    def append(self, records: Iterable[HistoricalRecord]) -> tuple[int, int]:
        grouped: dict[Path, list[HistoricalRecord]] = {}
        for record in records:
            grouped.setdefault(self.partition_path(record), []).append(record)
        written = duplicates = 0
        for path, partition_records in grouped.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            known = self._known_ids(path)
            with gzip.open(path, "at", encoding="utf-8") as stream:
                for record in sorted(partition_records, key=lambda item: (item.observed_at, item.record_id)):
                    if record.record_id in known:
                        duplicates += 1
                        continue
                    stream.write(canonical_json(record.as_dict()) + "\n")
                    known.add(record.record_id)
                    written += 1
        return written, duplicates

    def iter_records(
        self,
        *,
        source: str | None = None,
        dataset: str | None = None,
        available_before: str | None = None,
        strict_only: bool = False,
    ) -> Iterator[HistoricalRecord]:
        cutoff = parse_timestamp(available_before) if available_before else None
        for path in sorted(self.records_root.glob("**/records.jsonl.gz")):
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    payload = json.loads(line)
                    record = HistoricalRecord(**payload)
                    if source and record.source != source.lower():
                        continue
                    if dataset and record.dataset != dataset.lower():
                        continue
                    if strict_only and not record.strict_replay_eligible:
                        continue
                    if cutoff and record.available_datetime > cutoff:
                        continue
                    yield record

    def checkpoint_path(self, source: str) -> Path:
        return self.checkpoint_root / f"{self._safe(source.lower())}.json"

    def read_checkpoint(self, source: str) -> dict[str, Any]:
        path = self.checkpoint_path(source)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def write_checkpoint(self, source: str, payload: dict[str, Any]) -> Path:
        path = self.checkpoint_path(source)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
        return path

    def write_manifest(self, name: str, payload: dict[str, Any]) -> Path:
        path = self.manifest_root / f"{self._safe(name)}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
        return path
