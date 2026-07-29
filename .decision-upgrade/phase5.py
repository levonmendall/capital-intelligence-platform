from __future__ import annotations

from pathlib import Path


def replace_one(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one exact match, found {count}")
    file.write_text(text.replace(old, new))


replace_one(
    "application/cio_cycle.py",
    "            try:\n                profile = portfolio.profile(candidate.identifier)\n                profile_sector = profile.sector\n                profile_bucket = profile.correlation_bucket\n            except KeyError:\n                profile_sector = \"unclassified\"\n                profile_bucket = \"unclassified\"\n",
    "            try:\n                profile = portfolio.profile(candidate.identifier)\n                profile_sector = profile.sector\n                profile_bucket = profile.correlation_bucket\n                thesis_conditions = profile.thesis_conditions\n                invalidation_conditions_structured = (\n                    profile.invalidation_conditions_structured\n                )\n            except KeyError:\n                profile_sector = \"unclassified\"\n                profile_bucket = \"unclassified\"\n                thesis_conditions = ()\n                invalidation_conditions_structured = ()\n",
)
replace_one(
    "application/cio_cycle.py",
    "            scorer = StructuredThesisConditionScorer()\n            thesis = scorer.score(profile.thesis_conditions).score\n            invalidation = scorer.score(\n                profile.invalidation_conditions_structured\n            ).score\n",
    "            scorer = StructuredThesisConditionScorer()\n            thesis = scorer.score(thesis_conditions).score\n            invalidation = scorer.score(\n                invalidation_conditions_structured\n            ).score\n",
)
