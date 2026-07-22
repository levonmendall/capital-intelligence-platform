from __future__ import annotations
import json
from pathlib import Path
from .models import MarketSnapshot, RegimeResult, OpportunityScore

class OpportunityEngine:
    def __init__(self, config_path: str|Path, weights:dict[str,float], risk_penalties:dict[str,float]):
        self.catalog=json.loads(Path(config_path).read_text(encoding="utf-8")); self.weights=weights; self.risk_penalties=risk_penalties
    def _score_one(self, category,item,snapshot,regime):
        f=snapshot.opportunity_features.get(item["symbol"],{})
        defaults={"trend":50,"relative_strength":50,"breadth":50,"valuation":50,"quality":50,"risk":50}
        x={k:float(f.get(k,v)) for k,v in defaults.items()}
        macro=75 if regime.primary_regime in item.get("macro_tags",[]) else 45
        risk_quality=100-x["risk"]
        components={"trend":x["trend"],"relative_strength":x["relative_strength"],"breadth":x["breadth"],"macro_fit":macro,"valuation":x["valuation"],"quality":x["quality"],"risk":risk_quality}
        base=sum(components[k]*self.weights[k] for k in self.weights)
        penalty=self.risk_penalties.get(item.get("risk","moderate"),.15)*max(0,x["risk"]-50)
        score=max(0,min(100,base-penalty))
        available=sum(1 for k in defaults if k in f)/len(defaults); confidence=max(.45,min(.95,.55+.3*available+.1*regime.confidence))
        rationale=(f"{regime.primary_regime} macro fit: {macro:.0f}",f"Trend/relative strength: {x['trend']:.0f}/{x['relative_strength']:.0f}",f"Quality/valuation: {x['quality']:.0f}/{x['valuation']:.0f}",f"Risk score: {x['risk']:.0f}")
        return OpportunityScore(category,item["id"],item["label"],item["symbol"],score,confidence,components,rationale)
    def rank(self,snapshot,regime):
        result={}
        for category,items in self.catalog.items(): result[category]=tuple(sorted((self._score_one(category,i,snapshot,regime) for i in items), key=lambda x:x.score, reverse=True))
        return result
