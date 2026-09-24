# Real market data

The displayed product name is Q. Technical paths, local storage keys and service names retain the q21 namespace for compatibility.

## Sources and access

- Nasdaq's official symbol directory provides current listed securities, with test issues excluded and ETFs distinguished. Other Nasdaq security types remain labeled Listed security rather than guessed to be common shares.
- NSE's official equity, SME and ETF CSV directories provide searchable Indian listings. A `.NS` suffix disambiguates these catalogue symbols from US tickers; it is not a claim of a Massive NSE symbol mapping.
- Massive is the only built-in price-history provider. There is no Yahoo or synthetic fallback. Massive currently supports US equities, not NSE. NSE history can be supplied through Data → Import historical CSV.
- Enter a Massive key under Connections. It goes through the same-origin loopback gateway and is retained in backend memory only. `MASSIVE_API_KEY` can alternatively be supplied in the backend environment. The key is sent to api.massive.com using an Authorization header, never a URL, browser storage, logs, or Codex context.
- Requests are paced 12.5 seconds apart for compatibility with the Basic plan's five calls per minute. History requests cover 729 days, staying inside the two-year entitlement. A dataset fetch requires daily bars, splits and dividends, including pagination. No all-market automatic price crawl runs at startup.

## Storage and provenance

Local `.data/market` contains cached exchange directories, immutable SHA-256 dataset snapshots, latest-version pointers, and backend result records. Keep this directory private and excluded from source control. Historical snapshots survive restarts; credentials do not.

The browser uses `q21-workspace-real-v2`. The previous `q21-workspace-v1` is preserved intact and can be exported as a legacy synthetic workspace under Settings. Its generated prices and results are not restored into the active real-data workspace. New results require explicit real datasets; backtesting cannot generate bars implicitly. Deterministic invented fixtures exist only under tests.

Dataset identity includes instrument, provider, price basis and every input bar/corporate action. Result identity includes strategy, dataset identity and engine version. Unavailable prices remain missing, current-day bars are excluded, cached refresh failures are labeled, and missing RSI/momentum history is shown as unavailable. CSV imports must declare their actual source and raw/unadjusted price basis; that declaration is not independent verification of provenance.

## Quant conventions and limitations

Massive raw aggregates (`adjusted=false`) preserve historical share-price units. Split and original cash-dividend fields are joined on effective dates. Charts are split-adjusted; signal windows adjust past closes only for splits known by the signal date. Strategy fills use the next supplied session's open, whole shares, available cash and per-side fees. Fractional shares from reverse splits are modeled as cash in lieu at that session's open.

Dividend income accrues on ex-date to prior holders as non-reinvestable receivables. This first accounting extension does not use pay dates or tax withholding. NAV includes receivables, so final reconciliation is cash + marked shares + dividend receivables. The buy-and-hold reference includes cash dividends without reinvestment and is frictionless. Trade-level realized P&L and win rate exclude dividend income.

CAGR uses elapsed calendar days; Sharpe and volatility assume 252 sessions/year and zero risk-free rate. No holiday or missing-session bars are fabricated. Production session calendars, historical constituents, complete delisted coverage, corporate reorganizations, withheld taxes and point-in-time fundamentals remain unimplemented. This is a single-instrument research engine, not a portfolio or production execution service.

Manual paper orders are disabled because daily history is not an executable live quote. Broker account access remains separate and read-only. Data connection never enables live orders.

## Verification

From apps/web: `node --test tests/quant.test.mjs`, TypeScript checking, and the Sites application build.
From the root: `node --test apps/gateway/tests/*.test.mjs`.

Tests exercise next-open timing, future-data isolation, fee/cash invariants, splits and dividend receivables, input failures, provider authentication and request pacing, pagination, CSV validation, snapshot identity and restart persistence. Authenticated Massive live-network validation additionally requires the user's API key.

Official references: https://massive.com/docs/rest/quickstart ; https://massive.com/docs/rest/stocks/aggregates/custom-bars ; https://massive.com/docs/rest/stocks/corporate-actions/splits ; https://massive.com/docs/rest/stocks/corporate-actions/dividends ; https://massive.com/knowledge-base/article/does-massive-offer-international-data ; https://massive.com/pricing?product=stocks
