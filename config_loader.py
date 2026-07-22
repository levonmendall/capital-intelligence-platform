from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

@lru_cache(maxsize=None)
def load_json(relative_path: str) -> dict:
    path = ROOT / relative_path
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)

def mandates() -> dict:
    return load_json("config/mandates.json")

def settings() -> dict:
    return load_json("config/settings.json")

def asset_universe() -> dict:
    return load_json("config/asset_universe.json")
