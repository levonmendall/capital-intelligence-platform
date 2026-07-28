# Maximum Decision-Relevant Information Scope

## Objective

The platform must acquire and analyze the widest practical set of information that can materially affect asset prices or the single `COMPOUNDING` portfolio. Breadth is not sufficient by itself. Every source must be point-in-time usable, licensed for the intended use, attributable, historically reproducible, reliable, independently corroborated where appropriate, and mapped to explicit portfolio-impact channels.

The governing manifest is:

```text
config/maximum_decision_information_scope.json
```

It complements `config/all_markets_data_readiness.json`. The market-data manifest governs identity, prices, liquidity, corporate actions, fundamentals, calendars, benchmarks, and execution inputs. The maximum-information manifest governs current events, news, communications, positioning, physical activity, and alternative information. The combined `certified_data_ready` gate cannot pass unless both authorities are ready.

## Maximum scope

The manifest declares all of the following domains:

1. current events and global news;
2. geopolitical and security developments;
3. government policy and regulation;
4. central-bank statements, speeches, minutes, and implementation notices;
5. elections and political risk;
6. litigation, enforcement, sanctions, and legal events;
7. public-health developments;
8. cybersecurity incidents;
9. filings and corporate disclosures;
10. earnings-call transcripts;
11. management guidance;
12. analyst estimates and revisions;
13. credit ratings, defaults, and restructurings;
14. options-implied expectations, volatility surfaces, skew, and term structure;
15. futures positioning and open interest;
16. fund flows and cross-asset positioning;
17. short interest, borrow availability, fees, and securities lending;
18. insider and institutional ownership;
19. commodity production, stocks, inventories, outages, and physical balances;
20. shipping, ports, supply chains, and inventories;
21. weather, climate, and natural disasters;
22. power demand, grid constraints, outages, and generation mix;
23. consumer spending, mobility, web, app, and engagement activity;
24. labor, job-posting, and web activity;
25. real-estate transactions, listings, construction, and occupancy;
26. blockchain and on-chain network activity;
27. social and search sentiment;
28. patents, technology, research, and innovation.

This is the maximum governed scope, not a claim that every source is already connected.

## Current events and news analysis

The current-events process must continuously ingest and normalize material developments. A news item must retain:

- the underlying event time;
- original publication time;
- the first time it was available to the platform;
- retrieval time;
- correction, update, deletion, or supersession history;
- publisher and original source identity;
- licensing and usage-right identifiers;
- raw-content hash;
- canonical event identity for deduplication;
- entities, instruments, sectors, geographies, and topics;
- reliability, relevance, materiality, and independence assessments;
- corroborating source identifiers;
- portfolio-impact channels.

The platform must not create an investment action from a headline alone. `CurrentEventPortfolioAnalyzer` determines whether an event is sufficiently reliable, material, portfolio-relevant, and market-confirmed to require CIO review. It does not infer expected returns or issue trades.

Current events require three independent source groups before the domain is ready:

1. an original official or public-authority source;
2. a licensed global newswire;
3. an editorially independent journalism source.

Policy, health, legal, cyber, election, and geopolitical events have similarly explicit corroboration requirements.

## Point-in-time rules

Every record must distinguish:

- **event time** — when the underlying development occurred or is scheduled to occur;
- **publication time** — when the source published the information;
- **availability time** — when a compliant consumer could first have received it;
- **retrieval time** — when the platform obtained it;
- **knowledge cutoff** — the latest information boundary used by a decision.

Backtests and historical replays may only use records available by the simulated decision time. Corrections and later reporting can improve later decisions but cannot rewrite what was knowable previously.

Forecasts must preserve each vintage, model identifier, issue time, horizon, and uncertainty. Consensus datasets must preserve each point-in-time constituent population and revision. Address labels, classifications, panels, and methodologies must be versioned.

## Licensing requirements

A source cannot become ready merely because an endpoint responds. The licensing review must explicitly approve:

- automated retrieval;
- historical backfills;
- internal storage;
- encrypted backup and recovery;
- retention during and after the subscription;
- derived analytics;
- model features and transformations;
- internal user display;
- controlled paper simulation;
- raw-content quotation or excerpt limits;
- redistribution restrictions;
- geography and user-count restrictions;
- deletion obligations;
- audit requirements;
- source attribution;
- service levels and rate limits.

Secret values remain outside source control. The manifest stores only environment-variable names and certification identifiers.

## Reliability and independence

Each source must have documented controls for:

- publisher or authority identity;
- source hierarchy and primary-source preference;
- factual corrections and version history;
- duplicate and syndicated-content detection;
- entity and instrument mapping;
- geographic mapping;
- stale and missing data;
- rumor and unverified claims;
- social manipulation, bots, and coordinated behavior;
- panel drift and sample bias;
- survivorship and look-ahead bias;
- model and methodology changes;
- chain reorganizations and address-label changes;
- forecast uncertainty;
- independent corroboration.

Repeated copies of the same article, press release, estimate, or underlying dataset do not count as independent evidence.

## Portfolio relevance

Information must be mapped to one or more explicit impact channels:

- growth;
- inflation;
- policy;
- liquidity;
- discount rates;
- earnings;
- credit;
- supply;
- demand;
- commodities;
- currencies;
- volatility;
- regulation;
- geopolitics;
- operations;
- cyber risk;
- climate and weather;
- positioning;
- sentiment;
- counterparty risk.

The platform should continuously monitor the complete scope, but surface an alert only when a governed event materially changes the portfolio assessment, a thesis, a risk limit, or the relative attractiveness of an alternative use of capital.

## Fail-closed readiness

Evaluate the information scope independently:

```bash
python run_decision_information_readiness.py \
  --output database/maximum-decision-information-readiness.json
```

Evaluate the combined market and information supply chain:

```bash
python run_data_readiness.py \
  --output database/combined-data-readiness.json
```

The combined command reports:

- market-data readiness;
- maximum decision-information readiness;
- current-events and news readiness;
- every missing environment variable;
- every source deficiency;
- each domain's ready sources and independent source groups.

A satisfied `certified_data_ready` gate can be generated only when both manifests are fully ready. The certification retains both evidence identifiers.

## Current boundary

The repository now provides the scope, contracts, evaluator, CLI, configuration names, and fail-closed combined gate. It does not fabricate subscriptions or imply that placeholder sources are licensed, integrated, backfilled, or certified.

SEC EDGAR remains partially usable but does not yet provide complete historical archives, ownership coverage, or geographic mapping. Most current-event, transcript, estimates, positioning, physical-economy, weather, alternative, and on-chain provider slots remain intentionally disabled until procurement and certification are completed.

## Source onboarding order

For each source:

1. select the original or licensed provider;
2. review the full license and retention rights;
3. implement bounded retrieval with explicit timeouts and retries;
4. preserve raw records and content hashes;
5. normalize event, publication, availability, retrieval, and correction times;
6. complete historical backfills and vintages;
7. reconcile entities, instruments, geographies, topics, and duplicates;
8. document reliability, manipulation, and independence policies;
9. validate portfolio-impact mappings;
10. run deterministic certification scenarios;
11. record an expiring certification identifier;
12. enable the source in the manifest;
13. rerun both readiness commands.

Maximum coverage is reached only when every declared domain satisfies its required source count and independence count. More data that cannot pass these controls remains research-only and cannot satisfy readiness.
