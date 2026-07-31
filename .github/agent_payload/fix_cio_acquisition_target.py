from pathlib import Path

root = Path(__file__).resolve().parents[2]
path = root / "cio/service.py"
source = path.read_text(encoding="utf-8")

old = '''        target = self._confidence_aware_target(
            robust_cap=robust_cap,
            robustness=robustness,
            reconciliation=reconciliation,
            profile=profile,
            ensemble=ensemble,
        )
'''
new = '''        target = self._confidence_aware_target(
            robust_cap=robust_cap,
            robustness=robustness,
            reconciliation=reconciliation,
            profile=profile,
            ensemble=ensemble,
            progressive_lane=progressive_lane,
        )
'''
if source.count(old) != 1:
    raise RuntimeError("target call anchor changed")
source = source.replace(old, new, 1)

old = '''        profile: DecisionPolicyProfile,
        ensemble: GrowthEnsembleAssessment,
    ) -> float:
'''
new = '''        profile: DecisionPolicyProfile,
        ensemble: GrowthEnsembleAssessment,
        progressive_lane: bool,
    ) -> float:
'''
if source.count(old) != 1:
    raise RuntimeError("target signature anchor changed")
source = source.replace(old, new, 1)

old = '''        blended = (
            evidence_scale * 0.35
            + probability_scale * 0.25
            + edge_scale * 0.20
            + ensemble.target_multiplier * 0.20
        )
        target = robust_cap * max(0.15, min(1.0, blended))
'''
new = '''        if not progressive_lane:
            scale = min(evidence_scale, probability_scale, edge_scale)
            return round(max(0.0, robust_cap * scale), 8)
        blended = (
            evidence_scale * 0.35
            + probability_scale * 0.25
            + edge_scale * 0.20
            + ensemble.target_multiplier * 0.20
        )
        target = robust_cap * max(0.15, min(1.0, blended))
'''
if source.count(old) != 1:
    raise RuntimeError("target calculation anchor changed")
source = source.replace(old, new, 1)

path.write_text(source, encoding="utf-8")
print("preserved full-conviction acquisition sizing")
