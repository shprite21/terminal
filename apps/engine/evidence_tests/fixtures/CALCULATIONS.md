# Manually verified numerical expectations

These are arithmetic checks on actual NSE RELIANCE EQ observations, not an
Angel One demonstration or an empirical claim that the signal is useful.
All 40 excerpt observations retain their original source fields. The manifest
in `provenance.json` lists each official archive URL, archive hash and retrieval
timestamp. No test generates or modifies an OHLCV observation.

For a one-session momentum rule with ₹10,000, zero-friction **test assumptions**,
and a one-session holding horizon:

- January 1, 2024 close: ₹2,590.25.
- January 2 close: ₹2,611.70. Signal = 21.45 / 2590.25.
- After January 2 close: order for floor(10000 / 2611.70) = 3 shares.
- January 3 open: ₹2,610. Simulated purchase = ₹7,830; cash = ₹2,170.
- January 3 close: ₹2,583.30. Holdings = ₹7,749.90; equity = ₹9,919.90.
- January 4 open: ₹2,588. Simulated sale = ₹7,764; final cash = ₹9,934.
- Realized simulated loss = ₹66; net return = -0.0066; maximum drawdown = -0.00801.
- January 2 to January 3 close-to-close label = -28.40 / 2611.70.

Nonzero charge arithmetic for the same ₹7,830 observed-price turnover uses
explicit **test parameters**, not a claim about January 2024 tariff applicability:
brokerage ₹7.83; STT ₹7.83; exchange ₹0.24; SEBI ₹0.01; IPFT rounds to ₹0;
buy stamp ₹1.17; GST rounds from 18% × (7.83 + 0.24 + 0.01) to ₹1.45.

Date availability is deliberately delayed in chronology tests; the original
market observations remain unchanged. Missing-data tests withhold observations.
Transport tests raise faults or replay preserved real excerpts, without invented
market responses. All test research is stored under pytest temporary directories.
