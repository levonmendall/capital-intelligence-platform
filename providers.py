from __future__ import annotations
from abc import ABC, abstractmethod
import json
from pathlib import Path
from .models import MarketSnapshot

class MarketDataProvider(ABC):
    @abstractmethod
    def fetch_snapshot(self) -> MarketSnapshot: ...

class JSONSnapshotProvider(MarketDataProvider):
    def __init__(self, path: str | Path): self.path = Path(path)
    def fetch_snapshot(self) -> MarketSnapshot:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return MarketSnapshot(
            as_of=raw["as_of"], source=raw.get("source", self.path.name),
            signals={k: float(v) for k,v in raw["signals"].items()},
            opportunity_features={s:{k:float(v) for k,v in f.items()} for s,f in raw.get("opportunity_features",{}).items()},
            metadata=raw.get("metadata",{}),
        )

class CompositeProvider(MarketDataProvider):
    """Merges providers; later providers override duplicate signals/features."""
    def __init__(self, providers: list[MarketDataProvider]):
        if not providers: raise ValueError("At least one provider is required")
        self.providers=providers
    def fetch_snapshot(self) -> MarketSnapshot:
        snapshots=[p.fetch_snapshot() for p in self.providers]
        latest=max(snapshots, key=lambda x:x.as_of)
        signals={}; features={}; metadata={"providers":[]}
        for snap in snapshots:
            signals.update(snap.signals); features.update(snap.opportunity_features)
            metadata["providers"].append(snap.source)
        return MarketSnapshot(latest.as_of, "composite", signals, features, metadata)
