# Sprint 2 — Intelligence Core

## Delivered
- Provider abstraction and JSON snapshot provider
- Strict normalized market snapshot model
- Eight-regime probabilistic classifier
- Twelve standardized investment council specialists
- Weighted council synthesis
- Asset-class, region, sector, and innovation ranking
- Versioned model configuration
- Persistent snapshots, decisions, specialist opinions, and opportunity scores
- Intelligence Center dashboard
- Isolated test databases

## Deliberate boundary
The included snapshot is demonstration data, not a claim about current markets. A future provider may obtain licensed or public market/economic data and normalize it into the same stable interface without changing the regime, council, ranking, or journal modules.

## Run
```bash
python run_intelligence.py
streamlit run app.py
pytest -q
```
