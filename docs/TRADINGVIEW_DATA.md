# TradingView data feasibility — 2026-10-20

## Current application

IDX imports Yahoo Finance daily OHLCV for BMRI, BBCA, BBRI, BBNI and TLKM. XAUUSD imports Dukascopy bid H1 candles and retrains four forecast horizons. Both jobs currently refresh every six hours. The ten-second systemd timer checks deployment commits; it does not control market data frequency.

## Official access

TradingView now documents an official beta MCP service at `https://mcp.tradingview.com/mcp`. It requires Essential or higher (trials excluded), authenticates with OAuth 2.1, and exposes `get_ohlcv(symbol, interval, count, summary)` with up to 5,000 bars and UTC Unix timestamps. Daily and H1 intervals are supported. The documented rate limit is approximately 100 calls/minute/user. This establishes an available interface, but unattended server operation, account entitlements and usage permissions still require validation.

Source: [TradingView MCP documentation](https://www.tradingview.com/mcp/docs).

The separate REST API is intended for broker integration; TradingView's help page says it does not provide a general data API. The newer MCP documentation is more specific about current AI-client access.

Source: [TradingView API help](https://www.tradingview.com/support/solutions/43000474413-i-need-access-to-your-api-in-order-to-get-data-or-indicator-values/).

## Proposed symbols and validation

- IDX: `IDX:BMRI`, `IDX:BBCA`, `IDX:BBRI`, `IDX:BBNI`, `IDX:TLKM`, interval `1D`, initially about 500 completed daily bars per symbol. Confirm each with symbol search after authentication.
- Gold: explicitly select a provider, for example `OANDA:XAUUSD`, interval `1h`, initially up to 5,000 bars. Verify the exact symbol and whether quotes are bid, ask or midpoint before comparing against Dukascopy bid data. Keep provider histories separate and retrain after migration.
- IDX coverage currently lists free data delayed by ten minutes. A TradingView platform subscription and exchange real-time entitlement are separate considerations.

Sources: [IDX example](https://www.tradingview.com/symbols/IDX-BBCA/), [OANDA XAUUSD](https://www.tradingview.com/symbols/XAUUSD/?exchange=OANDA), [Market coverage](https://www.tradingview.com/data-coverage/).

## Migration design

1. Authenticate a suitable TradingView account and verify six sample series before changing production defaults. No password should be stored in the repository.
2. Confirm candle timestamp semantics, completion status, adjustment settings, IDX trading dates and exchange time zone. Convert Gold H1 to the application's UTC candle-close convention. Do not assume that a UTC timestamp represents candle close.
3. Add a provider adapter that preserves existing CSV schemas, validates OHLCV and duplicates, and records provider/symbol/interval metadata. Persist complete history locally; do not assume pagination beyond the documented 5,000-bar limit.
4. Compare overlapping data and session gaps. Exclude incomplete candles. Use exact future timestamps for Gold targets. Recompute IDX simulations using the verified adjustment convention and retrain Gold on one consistent feed.
5. Use atomic publication and retain the last successful report. Report authentication failures and stale data explicitly. Keep the existing sources available while access is evaluated.
6. After a deployment push, verify the deployed commit, containers, successful sync logs, local API and public pages over the SSH connection specified in AGENTS.md.

## Permissions and alternatives

TradingView's general terms restrict non-display uses, including algorithmic processing, and redistribution. The existence of MCP access does not itself establish permission to train this application's models or publish derived results. Confirm applicable permissions with TradingView/the provider before production ingestion.

Source: [TradingView terms, section 3](https://www.tradingview.com/policies/).

Official CSV export covers loaded chart data. Webhooks send alert messages, not a historical backfill. Neither feature alone supplies an authorized unattended training dataset. The community `tvdatafeed` library advertises up to 5,000 bars and limited unauthenticated access; it is not the official MCP service or a service guarantee.

Sources: [CSV export](https://www.tradingview.com/support/solutions/43000537255-how-to-export-chart-data/), [Webhooks](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/), [tvdatafeed](https://github.com/rongardF/tvdatafeed).

## Implementation status

The user selected experimental free access. The application now defaults to an unauthenticated chart WebSocket adapter (separate from the paid MCP service). It requests unadjusted regular-session IDX daily bars and OANDA:XAUUSD H1, validates completed candles, preserves previous reports on failure, and records source information. No credentials or paid entitlements are used. Local live requests succeeded for all five IDX symbols and OANDA:XAUUSD; server verification is required after each deployment. The previous sources remain explicitly selectable through environment variables, without automatic mixing. General usage restrictions noted above remain relevant; this change does not claim a supported API or additional data rights.
