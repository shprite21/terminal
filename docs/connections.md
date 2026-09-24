# Q21 connections

Start `./start-q21.ps1` from the project root. It starts the local integration gateway on 127.0.0.1:5174 and the web app on 127.0.0.1:5173. The frontend proxies only `/integrations` to that gateway. This local integration is not accessible from a cloud-hosted Sites version without a separately configured private tunnel and authentication boundary.

## Codex

Codex is enabled for strategy development: discuss an idea in its panel or create a project under **Strategies → Custom strategy development**. It can write code, specifications, custom parameters and tests in that project. Attach selected market history for source-labeled research, inspect files and download saved versions. Custom strategies are not limited to the built-in signal catalogue; they use their own tested scripts rather than automatically entering Q's template backtester. Conversations and project versions survive browser reloads, and existing projects can be selected after gateway restarts.

Each project has its own Git directory and an offline Codex permission profile. Writes stay within the project; escalation and live trading are unavailable. Gateway credentials are removed from the child environment. Windows sandbox reads have platform limitations, so known existing credential paths are denied explicitly in addition to instructions forbidding account and credential access. The gateway never imports agent-authored code. Content-addressed snapshots stay outside the agent's writable project.

On Windows, Q resolves `codex.exe` from PATH or the signed-in user's installed `%LOCALAPPDATA%/OpenAI/Codex/bin` directories. This supports desktop launches without Codex's session PATH and rediscovers the executable after updates. `Q21_CODEX_PATH` can explicitly select a CLI executable. Restart Q after upgrading the gateway. Startup errors distinguish a missing executable from initialization failures; reinstalling Codex is not the default remedy.

Uses the installed `codex app-server --stdio` and its existing ChatGPT sign-in. Q never reads or copies Codex token files. The gateway implements initialization, account state, browser login, persistent project conversations, streamed turns, stop/interrupt, and conversation reset. Only public agent-message deltas and brief activity descriptions are sent to the browser; private reasoning is not exposed.

The connection passes selected strategy/backtest context, data provenance and research notes. Broker credentials and account snapshots are not included. Inherited app and MCP connections are disabled. Development edits are isolated; promotion to running deployments and direct broker trading are not enabled.

## Angel One

In Q21 → Connections → Angel One → Sign in securely, enter your SmartAPI API key, client code, trading PIN, and current authenticator TOTP. The form sends credentials only to the local gateway, which performs the official HTTPS SmartAPI login. Do not put credentials in source files or chat messages.

The backend retains the API key and access token in memory only. PIN/TOTP are discarded after the request. Closing/restarting the gateway or selecting Disconnect clears Q21's retained session. Disconnect clears Q21's copy; it does not revoke all sessions at Angel One. Public IP is auto-detected using ipify unless explicitly supplied. IP/MAC headers are derived from the local machine rather than fabricated constants.

The account view returns selected fields from holdings, positions, and RMS cash limits. A failed profile check or rejected session returns sign-in-required state. No place/modify/cancel-order routes are exposed.

## Interactive Brokers

Run `./start-ibkr.ps1`. It uses the official Client Portal Gateway installed under `.tools/ibkr-gateway` and the checksum-verified Eclipse Temurin Java runtime under `.tools/java`. Open https://localhost:5000 and complete your own IBKR login and two-factor authentication. Then refresh Q21's connection status.

The gateway ships with a self-signed local certificate. Q21's certificate exception applies only to the configured HTTPS loopback gateway; remote broker TLS validation remains enabled. The gateway IP allowlist is restricted to 127.0.0.1. Q21 does not collect your IBKR password or automate its authentication.

Q21 checks `/iserver/auth/status` and can fetch account/position snapshots. The first page (up to 100 positions) per account is displayed and labeled; it is not a complete reconciliation service. Broker session health is refreshed while Q21 is open. Reauthenticate when IBKR expires the session.

## Boundaries and tests

Live order submission remains disabled. Broker data is displayed separately from synthetic research and browser-local paper balances. No scheduler, live compliance system, persistent order ledger, automatic reconciliation, or production settlement service has been added by this connection change.

The local gateway checks loopback addresses, Host, Origin, JSON content type for mutations, payload sizes, and an explicit endpoint allowlist. It exposes no general HTTP proxy and no generic Codex RPC endpoint.

```sh
node --test apps/gateway/tests/connections.test.mjs
node --test apps/web/tests/quant.test.mjs
```

Official sources: [Codex App Server](https://learn.chatgpt.com/docs/app-server), [Angel One SmartAPI SDK](https://github.com/angel-one/smartapi-python/blob/main/SmartApi/smartConnect.py), [IBKR Gateway setup](https://www.interactivebrokers.com/campus/trading-lessons/launching-and-authenticating-the-gateway/), [IBKR Gateway authentication FAQ](https://www.interactivebrokers.com/docs/web-api/authentication/cpgw/client-portal-gateway-faq).
