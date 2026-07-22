from pathlib import Path
from intelligence.providers import JSONSnapshotProvider
from intelligence.pipeline import IntelligencePipeline

if __name__=="__main__":
    root=Path(__file__).resolve().parent
    decision,decision_id=IntelligencePipeline(JSONSnapshotProvider(root/"data/sample_market_snapshot.json")).run(persist=True)
    print(f"Archived intelligence decision #{decision_id}")
    print(decision.summary)
    print(f"Confidence: {decision.confidence:.1%}")
