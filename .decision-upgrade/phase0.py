from __future__ import annotations

from pathlib import Path


path = Path(".decision-upgrade/phase2.py")
text = path.read_text()
old = '''replace_one(
    "portfolio/construction_models.py",
    "    instrument_identifier: str | None = None\\n\\n    def __post_init__(self) -> None:\\n",
    "    instrument_identifier: str | None = None\\n    uses_derivatives: bool = False\\n    derivative_lifecycle: DerivativeLifecycleProfile | None = None\\n\\n    def __post_init__(self) -> None:\\n",
)
'''
new = '''text = Path("portfolio/construction_models.py").read_text()
field_needle = "    instrument_identifier: str | None = None\\n\\n    def __post_init__(self) -> None:\\n"
field_replacement = "    instrument_identifier: str | None = None\\n    uses_derivatives: bool = False\\n    derivative_lifecycle: DerivativeLifecycleProfile | None = None\\n\\n    def __post_init__(self) -> None:\\n"
if text.count(field_needle) != 2:
    raise RuntimeError("construction_models.py: expected two derivative field insertion points")
Path("portfolio/construction_models.py").write_text(text.replace(field_needle, field_replacement))
'''
if text.count(old) != 1:
    raise RuntimeError("phase2.py: expected one ambiguous derivative-field transformer")
path.write_text(text.replace(old, new))
