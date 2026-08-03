from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old!r}")
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
