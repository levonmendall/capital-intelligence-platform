from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    path = "cio/service.py"
    replace_once(
        path,
        """                progressive_lane=progressive_lane,
                evidence_independence_ratio=(
                    specialists.evidence_independence_ratio
                ),
                emergency=(
""",
        """                progressive_lane=progressive_lane,
                emergency=(
""",
    )
    replace_once(
        path,
        """        progressive_lane: bool,
        evidence_independence_ratio: float,
        emergency: bool,
""",
        """        progressive_lane: bool,
        emergency: bool,
""",
    )
    replace_once(
        path,
        """        if (
            action in {CIOAction.BUY, CIOAction.INCREASE}
            and evidence_independence_ratio < 0.75
        ):
            required += 1

        cooldown_active = False
""",
        """        cooldown_active = False
""",
    )
    replace_once(
        path,
        """        target = robust_cap * max(0.20, min(1.0, ensemble.target_multiplier))
        if progressive_lane and ensemble.stage is not GrowthStage.OBSERVE:
""",
        """        if not progressive_lane:
            return round(max(0.0, robust_cap), 8)
        target = robust_cap * max(0.20, min(1.0, ensemble.target_multiplier))
        if ensemble.stage is not GrowthStage.OBSERVE:
""",
    )


if __name__ == "__main__":
    main()
