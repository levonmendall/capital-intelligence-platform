from pathlib import Path
from intelligence.providers import JSONSnapshotProvider
from intelligence.pipeline import IntelligencePipeline
from intelligence.regime_engine import ProbabilisticRegimeEngine
from intelligence.models import MarketSnapshot
from core.database import connection,initialize_schema

ROOT=Path(__file__).resolve().parents[1]
def test_regime_probabilities_sum_to_one():
    snap=MarketSnapshot("2026-01-01","test",{"growth":70,"inflation":45,"employment":65,"equity_trend":72,"breadth":68,"volatility":30,"credit":65,"liquidity":60})
    result=ProbabilisticRegimeEngine().score(snap)
    assert abs(sum(result.probabilities.values())-1)<1e-9
    assert result.primary_regime in result.probabilities

def test_full_pipeline_persists_decision():
    initialize_schema()
    decision,did=IntelligencePipeline(JSONSnapshotProvider(ROOT/"data/sample_market_snapshot.json")).run(True)
    assert did and len(decision.council)==12
    assert set(decision.opportunity_rankings)>={"asset_classes","regions","sectors","innovation"}
    with connection() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM intelligence_decisions").fetchone()["n"]==1
        assert conn.execute("SELECT COUNT(*) n FROM council_opinions").fetchone()["n"]==12

def test_rankings_descend():
    decision,_=IntelligencePipeline(JSONSnapshotProvider(ROOT/"data/sample_market_snapshot.json")).run(False)
    for items in decision.opportunity_rankings.values():
        assert [x.score for x in items]==sorted([x.score for x in items],reverse=True)
