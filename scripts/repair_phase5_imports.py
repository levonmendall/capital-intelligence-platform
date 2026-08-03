from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_count(path: str, old: str, new: str, expected: int) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(
            f"{path}: expected {expected} matches, found {count}: {old!r}"
        )
    target.write_text(text.replace(old, new), encoding="utf-8")


def replace_if_present(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count > 1:
        raise SystemExit(f"{path}: expected at most one match, found {count}: {old!r}")
    if count == 1:
        target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "intelligence/forward.py",
    "from cio.models import (\n    ScenarioAdjustment,\n    SpecialistAnalysis,\n    SpecialistPosition,\n    SpecialistRole,\n)\n",
    "from cio.committee import SpecialistAnalysis\nfrom cio.models import (\n    ScenarioAdjustment,\n    SpecialistPosition,\n    SpecialistRole,\n)\n",
)
replace_once(
    "tests/test_forward_intelligence.py",
    "from cio.models import SpecialistAnalysis, SpecialistPosition, SpecialistRole\n",
    "from cio.committee import SpecialistAnalysis\nfrom cio.models import SpecialistPosition, SpecialistRole\n",
)
replace_if_present(
    "tests/test_canonical_cio_cycle.py",
    "    assert journal.count() == 8\n",
    "    assert journal.count() == 9\n",
)
replace_once(
    "tests/test_forward_intelligence_integration.py",
    "def _bundle(candidate):\n",
    "def _bundle(candidate, *, as_of=None):\n    point_in_time = candidate.as_of if as_of is None else as_of\n",
)
replace_count(
    "tests/test_forward_intelligence_integration.py",
    "            as_of=candidate.as_of,\n",
    "            as_of=point_in_time,\n",
    2,
)
replace_once(
    "tests/test_forward_intelligence_integration.py",
    "        as_of=candidate.as_of,\n        business=business,\n",
    "        as_of=point_in_time,\n        business=business,\n",
)
replace_once(
    "tests/test_forward_intelligence_integration.py",
    "    bundle = _bundle(candidate)\n    lineage = replace(\n",
    "    bundle = _bundle(candidate, as_of=base.as_of)\n    lineage = replace(\n",
)
