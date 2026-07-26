"""Validate that runtime requirements are represented by exact hashed lock pins."""

from __future__ import annotations

import re
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

SOURCE = Path("requirements.txt")
LOCK = Path("requirements.lock")
PIN_PATTERN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)\s*\\$")
HASH_PATTERN = re.compile(r"^\s+--hash=sha256:[0-9a-f]{64}(?:\s*\\)?$")


def _source_requirements() -> dict[str, Requirement]:
    requirements: dict[str, Requirement] = {}
    for line_number, raw_line in enumerate(
        SOURCE.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        requirement = Requirement(line)
        name = canonicalize_name(requirement.name)
        if name in requirements:
            raise ValueError(f"duplicate runtime requirement on line {line_number}: {name}")
        requirements[name] = requirement
    if not requirements:
        raise ValueError("requirements.txt contains no runtime requirements")
    return requirements


def _locked_requirements() -> dict[str, tuple[Version, int]]:
    locked: dict[str, tuple[Version, int]] = {}
    current_name: str | None = None
    current_hashes = 0

    def finish_current() -> None:
        nonlocal current_name, current_hashes
        if current_name is not None:
            if current_hashes < 1:
                raise ValueError(f"locked requirement has no SHA-256 hash: {current_name}")
            version, _ = locked[current_name]
            locked[current_name] = (version, current_hashes)
        current_name = None
        current_hashes = 0

    for line_number, raw_line in enumerate(
        LOCK.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        pin_match = PIN_PATTERN.match(raw_line)
        if pin_match:
            finish_current()
            name = canonicalize_name(pin_match.group(1))
            if name in locked:
                raise ValueError(f"duplicate lock pin on line {line_number}: {name}")
            locked[name] = (Version(pin_match.group(2)), 0)
            current_name = name
            continue
        if HASH_PATTERN.match(raw_line):
            if current_name is None:
                raise ValueError(f"orphan lock hash on line {line_number}")
            current_hashes += 1
            continue
        stripped = raw_line.strip()
        if stripped and not stripped.startswith("#") and not raw_line.startswith(" "):
            raise ValueError(f"unrecognized lock entry on line {line_number}: {stripped}")
    finish_current()
    if not locked:
        raise ValueError("requirements.lock contains no pinned requirements")
    return locked


def main() -> int:
    source = _source_requirements()
    locked = _locked_requirements()
    missing = sorted(set(source) - set(locked))
    if missing:
        raise ValueError(f"runtime requirements missing from lock: {', '.join(missing)}")
    incompatible = [
        f"{name}=={locked[name][0]} not in {source[name].specifier}"
        for name in sorted(source)
        if locked[name][0] not in source[name].specifier
    ]
    if incompatible:
        raise ValueError("lock pins do not satisfy source ranges: " + "; ".join(incompatible))
    print(
        f"requirements.lock verified: {len(source)} direct requirements, "
        f"{len(locked)} total hashed pins"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
