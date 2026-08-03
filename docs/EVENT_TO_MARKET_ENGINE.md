# General Event-to-Market Transmission Engine

## Purpose

The event-to-market engine is the causal layer between the governed public-information system and the six-specialist/CIO process.

It is not an Iran or oil rule. It evaluates major headlines across recurring market-moving domains, identifies the economic drivers inside each event, maps those drivers to asset and portfolio exposures, and checks the proposed direction against contemporaneous market evidence.

The engine remains evidence only. It cannot create a candidate, alter an expected-return estimate, change a specialist conclusion, issue a CIO action, size a position, construct a portfolio, authorize a paper order, or enable real money.

## General operating flow

```text
public headline or official event
→ point-in-time quality and provenance checks
→ broad analysis-eligibility gate
→ semantic clustering and source-authority/corroboration assessment
→ causal driver classification and exposure mapping
→ contemporaneous market confirmation
→ strict specialist/CIO escalation gate
→ CIO review through the existing canonical process
```

## Analysis eligibility versus CIO escalation

The platform deliberately uses two different standards.

### Broad analysis gate

An event may enter causal analysis when:

- its evidence is not disputed, unverified, or missing;
- reliability is at least `0.35`;
- relevance is at least `0.20`; and
- materiality is at least `0.20`.

Novelty, a second source, and a contemporaneous market move are not required at this stage. This lets the platform analyze meaningful official announcements, early reports, evolving situations, market-closed events, and developments whose effects may emerge over time.

### Strict CIO escalation gate

An analyzed event may enter CIO context only when the stricter requirements also pass:

- a high-quality official, regulatory, or issuer source, or at least two independent sources;
- materiality of at least `0.50`;
- novelty of at least `0.50`;
- initial market confirmation of at least `0.10`;
- a governed causal rule and material directional transmission;
- the event-market confirmation, coverage, and confidence thresholds; and
- the existing portfolio-impact gate.

Direct authoritative announcements may satisfy source sufficiency without waiting for a news organization to repeat the same announcement. A single non-authoritative report may still be analyzed, but it cannot be escalated until independently corroborated.

Evolving events are no longer treated as simply old or new. An explicit update that supersedes prior evidence receives partial novelty of `0.75`. This allows developments such as a ceasefire violation, revised policy announcement, restored shipping route, amended earnings guidance, or resolved outage to be evaluated as meaningful changes within an existing event.

This separation broadens awareness without lowering any investment, construction, or trading threshold.

## Composable drivers

A headline is not forced into one simplistic category. The engine may identify several simultaneous drivers.

For example, a central-bank rate cut during a recession can contain:

- monetary-policy easing, which supports bonds and rate-sensitive valuations;
- growth deterioration, which pressures cyclicals and credit; and
- liquidity relief, if funding markets improve.

The engine combines the drivers target by target. When material drivers imply opposite directions for the same market, that transmission is marked `mixed` instead of silently selecting one narrative.

## Covered major headline domains

The Version 2 rule catalog covers the major recurring event families:

| Domain | Examples | Typical transmission areas |
|---|---|---|
| Macro growth | GDP, PMIs, retail sales, industrial production, recession signals | equities, cyclicals, commodities, credit, Treasuries |
| Inflation | CPI, PPI, wages, inflation expectations | rates, bonds, growth equities, currency, real assets |
| Labor | payrolls, unemployment, layoffs, job openings, wages | consumption, cyclicals, rates, bonds, credit |
| Monetary policy | rate decisions, guidance, QE/QT, liquidity operations | bonds, growth equities, credit, real estate, currencies |
| Fiscal policy | stimulus, tax changes, infrastructure, austerity, shutdowns | growth, sectors, inflation, yields, volatility |
| Geopolitics | war, ceasefire, blockade, sanctions risk, diplomatic resolution | regional assets, volatility, defense, commodities, currencies |
| Trade and sanctions | tariffs, export controls, embargoes, trade agreements | importers, exporters, substitutes, supply chains, inflation |
| Commodity and physical supply | production cuts, outages, inventories, restored capacity | commodities, producers, consumers, inflation, transport |
| Corporate | earnings, guidance, capital returns, recalls, approvals, contract awards | issuer equity, peers, suppliers, issuer credit |
| Credit and financial stability | defaults, bank runs, funding stress, rescues, upgrades | financials, credit, equities, volatility, safe havens |
| Regulation and legal | rules, permits, enforcement, antitrust, litigation | affected issuers, sectors, compliance beneficiaries |
| Operational and cyber | ransomware, outages, factory shutdowns, recovery | issuers, customers, suppliers, cybersecurity, volatility |
| Weather and disasters | hurricanes, fires, floods, earthquakes, drought | regions, insurers, commodities, supply chains, reconstruction |
| Public health | outbreaks, restrictions, treatments, containment | travel, healthcare, labor, growth, volatility |
| Politics and elections | contested elections, government formation, debt-ceiling resolution | regional assets, currencies, volatility, policy-sensitive sectors |
| Market liquidity | funding freezes, forced selling, trading halts, liquidity facilities | credit, small caps, volatility, safe assets |
| Currency | devaluations, intervention, reserve losses | exporters, importers, inflation, foreign-currency debt |
| Technology and innovation | trials, breakthroughs, commercial milestones | innovators, suppliers, disrupted incumbents, sectors |

## Broad coverage without invented certainty

No finite rule catalog can guarantee correct directional analysis for every future event. The engine therefore has a governed fallback for unfamiliar major headlines.

When an analysis-eligible event is material but no defensible directional rule matches, it is classified as `unresolved_major_event`. The engine:

- preserves the affected impact channels;
- generates neutral exposure hypotheses rather than fabricated directions;
- marks the event for causal review;
- records the specific unanswered questions; and
- prevents the event from entering CIO context until directional and market evidence are sufficient.

This ensures that a novel major event is noticed without allowing the system to pretend it understands a causal relationship that has not been established.

## Market confirmation

A headline-derived hypothesis is not enough for CIO escalation. For each predicted target, the engine compares point-in-time observations with the expected direction.

The assessment records:

- confirmation strength;
- confirmation coverage across the material transmission map;
- targets moving opposite the hypothesis;
- alternative explanations; and
- overall causal confidence.

Lack of immediate confirmation leaves an event in analysis and monitoring. It does not erase the event or prevent causal evaluation. CIO escalation remains fail-closed until the market and portfolio gates pass.

## Portfolio and candidate mapping

Rules use stable economic exposure identifiers rather than hard-coded securities, including:

- `affected_issuer`;
- `affected_sector`;
- `affected_region`;
- `affected_commodity`;
- `credit`;
- `bond_prices`;
- `growth_equities`;
- `financials`;
- `supply_chain`;
- `airlines`;
- `energy_producers`; and
- `cybersecurity_vendors`.

The production exposure maps translate those economic targets into current holdings and screened candidates. Candidate evidence is advisory input to the existing specialists and cannot modify the candidate's expected return directly.

## Cause-dependent oil example

A corroborated de-escalation event involving Persian Gulf energy flows may produce:

```text
lower conflict probability
→ lower tanker and Strait of Hormuz disruption risk
→ lower crude supply-risk premium
→ lower oil and near-term inflation pressure
→ support for airlines, transportation and broad equities
→ reduced pricing support for energy producers
```

A separate demand-weakness driver produces a different interpretation:

```text
recession risk
→ lower expected petroleum consumption
→ lower oil prices and producer cash flow
→ weaker broad equities and credit
```

The engine therefore does not encode “oil down means equities up.” It identifies why oil moved and checks the broader market response.

## Validation coverage

The focused regression suite covers:

- single authoritative announcements entering analysis before market confirmation;
- authoritative-source escalation only after the market gate passes;
- single non-authoritative reports remaining analysis-only until corroborated;
- explicit updates receiving partial novelty;
- repeated non-updates remaining outside CIO context;
- disputed and low-materiality records being rejected from analysis;
- Iran/energy de-escalation;
- inflation and policy transmission;
- simultaneous policy easing and recession weakness;
- issuer earnings and guidance;
- bank failure and credit stress;
- tariffs and export controls;
- ransomware and operational disruption;
- hurricane, insurance and supply effects;
- unfamiliar material-event causal review;
- contradictory market reactions;
- combined event and portfolio review gates; and
- append-only persistence.

## Protected invariants

- One governed `$250,000` paper portfolio remains unchanged.
- Exactly six advisory specialist analyses remain unchanged.
- Only the CIO may authorize an investment action.
- Event evidence cannot create or promote a candidate.
- Event evidence cannot directly alter expected return or position size.
- Existing strategy, cash hurdle, CIO thresholds, construction constraints, and paper-only controls remain unchanged.
- All event assessments remain point-in-time, provenance-preserving, and append-only.
