# Provider credential recovery

The application cannot produce a governed CIO briefing or paper recommendation until the production host can authenticate to both Alpaca paper/IEX and FRED.

## Required deployment secrets

Configure these values in the Render service Environment page:

```text
APCA_API_KEY_ID
APCA_API_SECRET_KEY
FRED_API_KEY
```

Use a matching key and secret from the same Alpaca **paper** account. Do not use live-account credentials. Do not include quotation marks, leading spaces, trailing spaces, placeholder text, or values copied from different key generations.

The FRED value must be an active API key. Values such as `PASTE_YOUR_FRED_API_KEY`, `REPLACE_ME`, or example keys are rejected as placeholders.

## Required fixed provider settings

The Render Blueprint supplies:

```text
APCA_API_BASE_URL=https://paper-api.alpaca.markets
APCA_DATA_BASE_URL=https://data.alpaca.markets
APCA_DATA_FEED=iex
```

Do not change the brokerage endpoint to a live endpoint. Real-money authority remains disabled.

## Recovery sequence

1. Replace the Alpaca paper key ID and secret together.
2. Replace the FRED placeholder with a valid key.
3. Save the Render environment.
4. Restart or redeploy the service so cached provider clients and settings are recreated.
5. Sign in to the Render application and run the production smoke test.

## Successful evidence

A recovered deployment must show all of the following:

- Paper account status is available rather than `Unavailable`.
- Live quote coverage is populated for the governed strategic wrapper set; the daily company-discovery lane additionally requires authenticated Alpaca asset/snapshot access and SEC company evidence.
- The Environment screen contains a live market table and economic readings.
- A canonical environment brief exists.
- Today contains a governed CIO briefing with a decision identifier.
- Portfolio contains either a valid paper construction or an explicit governed no-trade/hold conclusion.
- History records the briefing and any construction, execution attempt, thesis, or no-transaction record.

An HTTP 401 from Alpaca is an authentication failure, not a market-data outage. Replace the paper key pair. A FRED 400 response while a placeholder key is present is a configuration failure, not a valid provider observation.

The application intentionally remains fail-closed until these checks pass. It must not invent market evidence, a CIO decision, or a transaction merely to make the interface appear active.
