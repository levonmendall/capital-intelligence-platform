# Paper Trading Readiness

## Current classification

Capital Intelligence now contains a decision-complete source path for controlled unattended paper trading through the governed U.S.-listed wrapper pilot. Production readiness remains conditional on deployment and a successful live production smoke test using the configured Alpaca paper/IEX, FRED, persistent-storage, scheduler, execution, and backup authorities.

The system remains paper-only. No change in this release creates brokerage order-submission authority or permits real-money trading.

## Required decision gates

A full paper-CIO decision is complete only when the production cycle has certified candidate evidence for every qualified candidate, compared those candidates with cash and current holdings, completed all six independent specialist analyses, issued a CIO decision, and either produced an executable construction or an evidence-supported no-superior-opportunity conclusion.

The listed-wrapper publisher now:

- collects authenticated point-in-time IEX quotes and daily bars plus official FRED macro observations;
- publishes complete candidate or explicit exclusion coverage for every approved pilot instrument;
- persists governed market, macro, forecast, independent valuation, liquidity, cost, and evidence-lineage inputs for each qualified candidate;
- marks the canonical portfolio at the exact decision timestamp;
- publishes holding evidence for every owned pilot position and blocks the cycle when any mandatory holding evidence is unavailable;
- restores prior CIO decisions and active living theses before synthesis so hysteresis and ownership continuity remain auditable;
- routes every current holding through the mandatory holding-review lane.

`INSUFFICIENT_EVIDENCE` and `IMPLEMENTATION_BLOCKED` remain safe governed outcomes, but they do not prove that the CIO completed a comparative investment decision. Missing evidence for a prospective instrument creates an explicit exclusion. Missing evidence for a current holding blocks the complete cycle.

## Morning operating schedule

The persistent Render operator is configured to run the daily canonical CIO cycle at **5:00 AM America/Los_Angeles**. Public live information refreshes at least every 30 minutes, and the scheduler polls every 60 seconds. A restart after the scheduled boundary catches up the same market-date cycle instead of skipping it.

The completed cycle writes the CIO briefing, portfolio construction or governed no-action conclusion, pending paper-transaction report, portfolio state, and history records used by the Today, Environment, Portfolio, and History screens. The interface may truthfully show a buy, sell, hold, or no-trade recommendation; it must never fabricate a transaction merely to make the application appear active.

## Pilot policy authority

The scheduled CIO construction and paper executor use the same pilot limits:

- minimum cash weight from the versioned free-paper universe;
- maximum batch turnover from that universe;
- the lower of the canonical and pilot single-position limits;
- instrument-specific limits remain enforced by the final execution validator.

The evidence publisher has no ranking, sizing, construction, execution, or real-money authority. The existing Opportunity Engine, independent specialists, CIO, Portfolio Construction Engine, and paper executor remain the respective authorities for those stages.

## Ten-year historical learning

The ten-year replay remains subordinate calibration and governance evidence. It may reduce confidence or position size, but it cannot create a candidate, increase expected return, increase confidence, enlarge a position, authorize execution, or promote policy.

Live calibration requires point-in-time macro coverage, original-decision-horizon outcome alignment, and completed certification. Capability-policy-only outcomes and macro-incomplete cutoffs remain available for audit but are excluded from live forecast, confidence, and sizing calibration.

Ten years do not cover every market regime, security-master change, instrument history, or structural break. Historical learning therefore remains a conservative modifier rather than a primary signal or performance promise.

## Readiness decision

The merged source becomes ready for controlled unattended paper trading only after the deployed release passes the stricter production smoke test. That test must confirm persistent state, a current successful CIO cycle, complete provider observations, a governed comparative outcome or completed paper execution, and a healthy encrypted backup.

Passing these readiness gates demonstrates process and operational readiness; it does not establish future investment performance.
