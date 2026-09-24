# Q project instructions

Q is the canonical product name and the single system going forward. Build all future capabilities in this checkout as parts of Q. The former regime platform and Evidence are integrated modules and historical sources, not separate products to develop. Preserve their original projects for reference and migration verification. Existing `q21`, `flagship`, and `evidence` technical identifiers may remain for compatibility with stored data, scripts and imports.

Read docs/implementation.md and the relevant methodology documentation before substantial changes. The original docs/q21-product-specification.md is retained locally when available; it is historical planning, not a claim of implemented capabilities.

- Keep UI, research calculations, account simulation, data, and broker services separate.
- Keep demo data explicitly labeled and reproducible. Never fabricate connectivity, live prices, AI responses, or backtest results.
- Use only past bars to generate signals and execute no earlier than the next eligible bar. Account for costs, available cash, and whole-share rounding.
- Preserve historical strategy/result snapshots. An edited research strategy must not change a running deployment.
- Live execution must remain disabled until deterministic risk, compliance, settlement, broker, reconciliation, and approval services exist.
- No broker credentials in browser code or logs. Codex may not directly place live orders.
- Use UTC dates in data and explicit exchange calendars for production sessions.
- Validate quant changes with independent invariants and numerical edge cases. Run node --test tests/quant.test.mjs from apps/web, TypeScript checking, and the application build.
- The web project is a Sites project; preserve its hosting manifest and Vite Sites plugin.
