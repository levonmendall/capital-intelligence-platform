from __future__ import annotations
import json
from core.database import connection
from .models import MarketSnapshot, CIOIntelligenceDecision

def persist_snapshot(snapshot:MarketSnapshot)->int:
    with connection() as conn:
        cur=conn.execute("""INSERT INTO market_snapshots(as_of,source,signals_json,features_json,metadata_json) VALUES(?,?,?,?,?)""",(snapshot.as_of,snapshot.source,json.dumps(snapshot.signals,sort_keys=True),json.dumps(snapshot.opportunity_features,sort_keys=True),json.dumps(snapshot.metadata,sort_keys=True)))
        return int(cur.lastrowid)

def persist_decision(snapshot_id:int, decision:CIOIntelligenceDecision)->int:
    payload=decision.to_dict()
    with connection() as conn:
        cur=conn.execute("""INSERT INTO intelligence_decisions(snapshot_id,created_at,model_version,primary_regime,confidence,composite_risk_score,decision_json) VALUES(?,?,?,?,?,?,?)""",(snapshot_id,decision.created_at,decision.model_version,decision.regime.primary_regime,decision.confidence,decision.composite_risk_score,json.dumps(payload,sort_keys=True)))
        decision_id=int(cur.lastrowid)
        for opinion in decision.council:
            conn.execute("""INSERT INTO council_opinions(intelligence_decision_id,specialist_id,score,confidence,recommendation,opinion_json) VALUES(?,?,?,?,?,?)""",(decision_id,opinion.specialist_id,opinion.score,opinion.confidence,opinion.recommendation,json.dumps(opinion.to_dict(),sort_keys=True)))
        for category, rankings in decision.opportunity_rankings.items():
            for rank,item in enumerate(rankings,1):
                conn.execute("""INSERT INTO opportunity_scores(intelligence_decision_id,category,rank,opportunity_id,symbol,score,confidence,score_json) VALUES(?,?,?,?,?,?,?,?)""",(decision_id,category,rank,item.opportunity_id,item.symbol,item.score,item.confidence,json.dumps(item.to_dict(),sort_keys=True)))
        return decision_id
