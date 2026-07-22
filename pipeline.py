from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from core.config_loader import load_json
from .models import CIOIntelligenceDecision
from .providers import MarketDataProvider
from .regime_engine import ProbabilisticRegimeEngine
from .council import convene
from .opportunity_engine import OpportunityEngine
from .journal import persist_snapshot,persist_decision

ROOT=Path(__file__).resolve().parents[1]
class IntelligencePipeline:
    def __init__(self, provider:MarketDataProvider):
        self.provider=provider; self.cfg=load_json("config/intelligence_model.json")
        self.regime_engine=ProbabilisticRegimeEngine(self.cfg["regime_temperature"])
        self.opportunity_engine=OpportunityEngine(ROOT/"config/opportunities.json",self.cfg["opportunity_weights"],self.cfg["risk_penalties"])
    def run(self,persist:bool=True)->tuple[CIOIntelligenceDecision,int|None]:
        snapshot=self.provider.fetch_snapshot(); regime=self.regime_engine.score(snapshot); council=convene(snapshot)
        weights=self.cfg["council_weights"]; weighted=sum(o.score*weights.get(o.specialist_id,0) for o in council); total=sum(weights.get(o.specialist_id,0) for o in council); composite=weighted/total if total else 50
        council_conf=sum(o.confidence*weights.get(o.specialist_id,0) for o in council)/total if total else .5
        confidence=max(.45,min(.95,.45*regime.confidence+.55*council_conf)); rankings=self.opportunity_engine.rank(snapshot,regime)
        warnings=tuple(flag for o in council for flag in o.risk_flags)
        top=[]
        for category,items in rankings.items():
            if items: top.append(f"{category}: {items[0].label} ({items[0].score:.0f})")
        summary=f"Primary regime is {regime.primary_regime}. Council risk score is {composite:.1f}/100. Leading opportunities — "+"; ".join(top)
        decision=CIOIntelligenceDecision(datetime.now(timezone.utc).isoformat(),snapshot.as_of,self.cfg["version"],regime,council,rankings,composite,confidence,summary,warnings)
        if not persist:return decision,None
        sid=persist_snapshot(snapshot); did=persist_decision(sid,decision); return decision,did
