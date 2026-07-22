# AI Chief Investment Office — V3 Sprint 1

A personal, paper-only virtual asset manager built around one CIO market view and eight distinct mandates.

## Included
- Eight mandates seeded with $25,000 each on July 22, 2026
- $200,000 total virtual starting AUM
- SQLite portfolio, cash, trade, NAV, decision and journal records
- Configurable spread, slippage, commission and sell regulatory costs
- Explainable CIO regime and allocation engine
- Manual paper-trade validation screen
- Streamlit executive dashboard
- Preserved V2.1 historical intelligence files in `legacy_v2_1/`

## Run locally
```bash
python -m pip install -r requirements.txt
python initialize.py
streamlit run app.py
```

## Important
This code cannot connect to a brokerage or execute real trades. Prices entered in Sprint 1 are manual. Automated market-price ingestion and approval-based rebalancing belong to Sprint 2.


## Sprint 2 Intelligence Core
See `docs/SPRINT_2_INTELLIGENCE.md`. Run `python run_intelligence.py` to archive a complete demonstration decision.
