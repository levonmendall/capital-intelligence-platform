# Upgrade the working V2 repository to V2.1

V2.1 adds append-only historical intelligence while preserving the existing
Command Center, portfolio, rotation, risk, committee, reports, and system-health pages.

## Upload all replacement files

Upload the contents of the V2.1 upgrade package into the existing repository and
replace files when GitHub asks.

### New files

- `historical_engine.py`
- `backfill_history.py`
- `data/history/market_history.csv`
- `data/history/regime_history.csv`
- `data/history/rotation_history.csv`
- `data/history/decision_outcomes.csv`
- `.github/workflows/historical_backfill.yml`

### Replacement files

- `app.py`
- `refresh_all.py`
- `storage.py`
- `.github/workflows/daily_refresh.yml`
- `.github/workflows/validate.yml`

## Validate

After committing, wait for **Validate Polished V2 Application** to turn green.

## Run the initial backfill

Open:

`Actions → Historical Intelligence Backfill → Run workflow`

Recommended first run:

- Period: `10y`
- Frequency: `W-FRI`

Weekly history gives a useful ten-year record without creating an unnecessarily
large repository.

## Confirm historical files

The workflow should commit:

- `capital_rotation_v21.db`
- `data/history/market_history.csv`
- `data/history/regime_history.csv`
- `data/history/rotation_history.csv`

## Reboot Streamlit

Use:

`Manage app → Reboot app`

A new sidebar page should appear:

`Historical Intelligence`

## Daily continuation

The Daily V2 Market Refresh now refreshes the current market snapshot and appends
the same date to the historical database and CSV exports.

## Important limitation

The first backfill reconstructs historical breadth, flows, and some risk fields
from transparent price-based proxies when licensed point-in-time datasets are
not available. It is research history, not a perfect institutional vintage dataset.
