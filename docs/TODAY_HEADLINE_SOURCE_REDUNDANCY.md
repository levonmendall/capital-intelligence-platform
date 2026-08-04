# Today headline source redundancy

## Objective

The Today surface must not depend on one broad-news provider and must never render an empty primary section. Headline awareness remains educational and cannot authorize a portfolio change.

## Source layers

The dedicated headline collector runs every five minutes and supplements the existing governed public-information collector.

Credential-free publisher feeds:

- BBC Business
- BBC World, filtered for investment-relevant developments
- NPR Business
- NPR Economy
- The Guardian Business
- CoinDesk

Optional financial-news APIs, activated only when their environment variables are configured:

- Finnhub (`FINNHUB_API_KEY`)
- Alpha Vantage Market News (`ALPHA_VANTAGE_API_KEY`)
- EODHD Financial News (`EODHD_API_KEY`)
- Marketaux (`MARKETAUX_API_TOKEN`)

GDELT remains one discovery source in the original public-information catalog, but it is no longer the sole broad headline path.

## Persistence and outage behavior

The headline worker and the original public-information collector share the same atomic persistence lease. Every successful pass merges new headline metadata with the bounded rolling public-event history. A thin or failed pass therefore cannot erase recently verified stories.

Today uses this order:

1. source-qualified headlines published during the current 24-hour window;
2. latest verified headlines, with original timestamps, during a bounded 72-hour continuity window;
3. a live market-pulse card showing market session, governed quote coverage, provider-refresh status, and what to watch next.

The third state is not presented as news. It exists so the section remains useful without inventing a headline or implying that an empty feed means nothing happened.

## Rights and governance

Only headline metadata, a short source-provided description, and the original article link are stored. Article bodies are not stored. Every record preserves provider identity, publication time, retrieval time, source link, independence group, quality state, limitations, and a deterministic event identity.

These records have no candidate, ranking, specialist, CIO, sizing, construction, execution, or real-money authority.
