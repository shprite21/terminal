# Q product specification

Product name: **Q**. Technical namespace: `q21`.

Q is the single system for all future development. The former regime platform and Evidence are integrated into Q. Older names in the original specifications below are historical references; they do not define separate active products.

This document combines the three supplied specifications in their original order. Sections 71–100 supersede the earlier custom command-assistant proposal: the integrated assistant is **Codex**.

You are a senior quant developer, trading-systems engineer, product designer, and full-stack architect.

I want you to build a production-quality institutional quantitative trading terminal.

The product should be a SINGLE unified terminal where I can:

RESEARCH → BUILD → BACKTEST → VALIDATE → PAPER TRADE → DEPLOY → MONITOR → ANALYZE

strategies without switching applications.

The experience should feel like a combination of:

- Bloomberg Terminal
- institutional quant research platform
- TradingView
- QuantConnect
- portfolio/risk management terminal
- AI coding/research assistant

but with the visual language of the screenshots I have provided.

==================================================
1. PRIMARY PRODUCT IDEA
==================================================

Build an institutional systematic trading terminal centered around one concept:

"Command the market."

I should be able to interact with the entire system through either:

1. traditional UI controls
2. natural-language commands
3. keyboard command palette
4. strategy code

Examples:

"Backtest 6-month momentum on NIFTY 500 from 2018."

"Create a mean-reversion strategy using RSI and Bollinger Bands."

"Run this strategy across all liquid NSE stocks."

"Compare this strategy against NIFTY 50."

"Show me strategies with Sharpe > 1.5 and drawdown < 12%."

"Increase the stop loss from 1.5% to 2% and rerun."

"Run 100 parameter variations."

"Perform walk-forward validation."

"Check whether this strategy is overfitted."

"Paper trade this strategy using Angel One."

"Show my current portfolio factor exposures."

"Why did today's strategy P&L fall?"

"Disable strategies losing more than 2 ATR from expected behaviour."

The command system should translate natural-language intent into structured platform actions.

Never allow an AI-generated strategy to jump directly into live execution.

The lifecycle must be:

COMMAND
↓
PLAN
↓
USER REVIEW
↓
BACKTEST
↓
VALIDATION
↓
PAPER TRADING
↓
DEPLOYMENT APPROVAL
↓
LIVE

==================================================
2. VISUAL DESIGN — IMPORTANT
==================================================

Use the supplied Astral screenshots as the PRIMARY DESIGN REFERENCE.

I want the visual appearance to be extremely close in:

- color palette
- darkness
- spacing
- typography feel
- border treatments
- cards
- gradients
- shadows
- chart styling
- glow effects
- rounded corners
- overall density

Do NOT copy Astral logos, names, written copy, or proprietary graphics.

Create our own identity.

Temporary product name:

Q21

Logo can initially be a minimal geometric four-point / star / cross symbol.

DESIGN LANGUAGE:

Background:
near-black / blue-black.

Suggested base:
#05070B
#070A10
#0A0E16

Panel backgrounds:
#0D111A
#101521
#121826

Primary blue:
bright electric/cobalt blue approximately:
#176BFF
#2474FF
#2F7BFF

Text:
#FFFFFF primary
#B6BDC9 secondary
#747D8C tertiary

Positive:
muted institutional green

Negative:
muted red

Borders:
very subtle blue-gray / white at 6-10% opacity.

Use blue primarily for:

- selected navigation
- interactive controls
- AI actions
- important metrics
- active tabs
- chart highlights
- deployment state

Avoid rainbow dashboards.

The UI must feel professional and institutional rather than crypto/gaming.

Typography should resemble modern financial SaaS:
Inter / Geist / SF Pro style.

Use:
- large bold section headers
- compact metric typography
- monospaced fonts for market/code data

The terminal should visually match the supplied screenshots very closely.

==================================================
3. APPLICATION SHELL
==================================================

Build a desktop-first terminal optimized for:

2560x1440
1920x1080

Responsive down to laptops.

Main layout:

LEFT SIDEBAR
CENTER WORKSPACE
RIGHT INTELLIGENCE PANEL
TOP GLOBAL COMMAND BAR
BOTTOM SYSTEM STATUS BAR

LEFT SIDEBAR:

Q21 logo

Home
Markets
Research
Scanner
Strategies
Backtests
Portfolio
Risk
Deployments
Execution
Data
Library

Bottom:

Connections
Settings
Account

The sidebar should collapse to icons.

==================================================
4. HOME / COMMAND CENTER
==================================================

This should be the main landing screen.

Top:

"Good afternoon"
"Command the market."

Large centered command input:

"Ask Q21 to research, build, backtest or deploy..."

Command examples rotating underneath.

Command box supports:

/
@ symbol
ticker symbols
strategy references
saved datasets
saved models
portfolio references

Example:

"Backtest @MomentumV3 on RELIANCE from 2019"

Immediately below:

MARKET OVERVIEW

NIFTY
BANK NIFTY
S&P 500
NASDAQ
VIX
USD/INR

Then:

ACTIVE STRATEGIES
TODAY'S P&L
PORTFOLIO EXPOSURE
RISK
RECENT BACKTESTS
SYSTEM HEALTH

==================================================
5. AI COMMAND SYSTEM
==================================================

This is one of the most important features.

Create an AI Copilot called:

Q21 COMMAND

Accessible through:

CMD/CTRL + K

and through a persistent command input.

The assistant should be able to access platform tools.

Architecture:

User command
↓
intent parser
↓
tool planner
↓
structured JSON command
↓
execution engine
↓
results
↓
assistant explanation

Create internal tools such as:

market.search()
market.quote()
market.history()

research.fundamentals()
research.technicals()
research.factor_analysis()
research.news()

strategy.create()
strategy.modify()
strategy.clone()
strategy.inspect()

backtest.run()
backtest.compare()
backtest.optimize()
backtest.walk_forward()
backtest.monte_carlo()

portfolio.exposure()
portfolio.optimize()
portfolio.rebalance()

risk.var()
risk.expected_shortfall()
risk.stress_test()
risk.factor_exposure()

deployment.paper()
deployment.pause()
deployment.resume()

broker.orders()
broker.positions()

The LLM must NEVER directly manipulate broker APIs.

All commands must pass through deterministic backend services.

==================================================
6. AI ACTION PREVIEW
==================================================

Before executing important commands show:

COMMAND UNDERSTOOD

Example:

Strategy:
Cross-sectional momentum

Universe:
NIFTY 200

Signal:
12M momentum excluding latest month

Rebalance:
Weekly

Position count:
20

Weighting:
Equal-weight

Transaction costs:
0.15%

Backtest:
2016 → Present

Then buttons:

RUN
EDIT
CANCEL

For deployment:

DEPLOYMENT PLAN

Broker
Account
Capital
Max position size
Stop conditions
Risk limits
Strategy hash
Data source

Require confirmation.

==================================================
7. RESEARCH TERMINAL
==================================================

Create a full research workspace.

Search any:

ticker
ETF
index
sector
industry
factor
strategy

Stock screen layout:

LEFT:
watchlist

CENTER:
interactive price chart

RIGHT:
security intelligence

Tabs:

Overview
Financials
Valuation
Technicals
Factors
Earnings
Ownership
Events
Strategy Tests

Security summary should include:

Price
Return
Market cap
Volume
ATR
Beta
Volatility
Momentum
RSI
Relative strength
Sector ranking

Financial data:

Revenue
EBITDA
EBIT
PAT
EPS
ROE
ROCE
Margins
Debt
FCF

Chart overlays:

SMA
EMA
VWAP
Bollinger
RSI
MACD
ATR
Volume
custom signals

==================================================
8. UNIVERSAL SCANNER
==================================================

Build an institutional scanner.

Users can visually create screens like:

Market cap > 10,000 Cr
ROCE > 18%
Debt/equity < 0.5
6M momentum > 15%
Price > 50DMA
Volume > 1.5x average

Support AND / OR groups.

Also allow:

"Find Indian stocks with strong momentum, improving earnings and low leverage."

Translate that command into scanner filters.

Save scans.

==================================================
9. STRATEGY BUILDER
==================================================

Strategies need three creation modes.

MODE 1 — PROMPT

"Create a volatility breakout strategy."

MODE 2 — VISUAL

IF
condition

AND
condition

THEN
buy/sell

MODE 3 — CODE

Python strategy editor.

Suggested interface:

LEFT
strategy tree

CENTER
chart / code editor

RIGHT
strategy parameters

BOTTOM
logs/results

Every strategy should have:

Universe
Data
Features
Signals
Entries
Exits
Sizing
Portfolio construction
Risk rules
Execution rules

==================================================
10. STRATEGY OBJECT MODEL
==================================================

Use a reusable structure similar to:

Strategy

metadata

universe

features

signal_engine

entry_rules

exit_rules

position_sizing

portfolio_rules

risk_rules

execution_rules

parameters

Every backtest must store the exact strategy configuration/version used.

Generate immutable strategy hashes.

==================================================
11. STRATEGY LIBRARY
==================================================

Provide starter research templates:

Cross-sectional momentum
Time-series momentum
Short-term mean reversion
Pairs trading
Statistical arbitrage
Breakout
Volatility expansion
PEAD
Sector rotation
Trend following
Moving-average crossover
RSI mean reversion
Bollinger mean reversion
Factor portfolio
Minimum variance
Risk parity

These should be research templates, not advertised as profitable strategies.

==================================================
12. BACKTEST ENGINE
==================================================

Create a serious backtesting engine.

It must account for:

commissions
brokerage
slippage
bid/ask spread
liquidity
position sizing
cash
corporate actions
look-ahead bias
survivorship bias where possible

Support:

daily
hourly
15-minute
5-minute

Architecture should allow higher frequencies later.

Output:

Total return
CAGR
Annual volatility
Sharpe
Sortino
Calmar
Max drawdown
Win rate
Profit factor
Expectancy
Turnover
Number trades
Average holding period
Beta
Alpha
VaR
Expected Shortfall

Visualizations:

equity curve
drawdown
rolling Sharpe
monthly returns
trade distribution
return distribution
exposure
turnover
benchmark comparison

==================================================
13. BACKTEST RESULTS DESIGN
==================================================

Make this one of the strongest-looking pages.

TOP:

Strategy name
Universe
Period
Status

LARGE METRICS:

CAGR
SHARPE
MAX DD
VOLATILITY
TOTAL RETURN

Large equity curve.

Then:

Performance
Risk
Trades
Exposure
Regimes
Parameters
Logs

Make the results presentation resemble a professional hedge-fund research report.

==================================================
14. PARAMETER LAB
==================================================

Inspired by the supplied screenshot showing multiple strategy variations.

Add:

FORK STRATEGY

Then allow:

Parameter sweep
Grid search
Random search
Bayesian optimization

Example cards:

Momentum V1

Entry:
Z > 1

Exit:
Z < 0.2

Stop:
1.5%

Sharpe:
1.27

Max DD:
-10.3%

---

Momentum V2

Entry:
Z > 1.35

etc.

Allow:

COMPARE

Prominent warning:

"Parameter optimization can cause overfitting."

==================================================
15. WALK-FORWARD ANALYSIS
==================================================

Implement:

train
validation
test

windows.

Display:

IN-SAMPLE
OUT-OF-SAMPLE

results separately.

Never mix them.

Support rolling walk-forward testing.

Show:

performance degradation
parameter stability
signal stability

==================================================
16. MONTE CARLO ENGINE
==================================================

Allow simulation of trade outcomes.

Run:

1,000
5,000
10,000 simulations.

Outputs:

expected return distribution
drawdown distribution
probability of loss
95th percentile drawdown
risk-of-ruin approximation

==================================================
17. OVERFITTING / STRATEGY QUALITY PANEL
==================================================

Create a validation scorecard.

Metrics:

Out-of-sample Sharpe
In-sample Sharpe
Performance decay
Parameter sensitivity
Number of trades
Turnover
Maximum drawdown
Monte Carlo robustness
Regime stability
Benchmark alpha

Generate warnings such as:

LOW SAMPLE SIZE
PARAMETER INSTABILITY
OUT-OF-SAMPLE DECAY
HIGH TURNOVER
EXCESSIVE TAIL RISK

Do not invent an arbitrary "AI strategy score" without exposing how it is calculated.

==================================================
18. REGIME ENGINE
==================================================

Create regime analysis.

Possible features:

trend
realized volatility
VIX
breadth
correlation
rates
credit conditions

Support:

rule-based regimes initially

then architecture for:

HMM
GMM
clustering
Bayesian models

Example:

RISK-ON TREND
RISK-OFF
HIGH VOLATILITY
LOW VOLATILITY
SIDEWAYS

Backtests can show returns by regime.

==================================================
19. PORTFOLIO TERMINAL
==================================================

Portfolio dashboard:

NAV
daily P&L
realized P&L
unrealized P&L
cash
gross exposure
net exposure
beta

Holdings table:

symbol
quantity
price
market value
weight
P&L
strategy
sector
beta

Visualizations:

sector exposure
factor exposure
strategy exposure
position concentration

==================================================
20. PORTFOLIO CONSTRUCTION
==================================================

Support:

Equal weight
Volatility weighting
Inverse volatility
Risk parity
Minimum variance
Maximum Sharpe
Custom weights

Constraints:

max asset weight
max sector weight
turnover cap
gross exposure
net exposure
cash buffer

==================================================
21. RISK TERMINAL
==================================================

Dedicated institutional risk page.

Show:

Portfolio VaR
Expected Shortfall
Volatility
Beta
Gross exposure
Net exposure
Largest position
Largest sector
Correlation concentration

Stress tests:

Market -5%
Market -10%
Volatility +50%
Interest rate shock
Custom ticker shocks

Future architecture:

historical crisis scenarios.

==================================================
22. DEPLOYMENT CENTER
==================================================

Statuses:

RESEARCH
BACKTEST
VALIDATED
PAPER
LIVE
PAUSED
FAILED

Strategies displayed as cards/table.

Each deployed strategy shows:

P&L
capital
positions
orders
drawdown
Sharpe
last signal
next scheduled run
broker
health

Actions:

PAUSE
RESUME
STOP
VIEW LOGS

==================================================
23. PAPER TRADING FIRST
==================================================

Build execution architecture so PAPER TRADING works first.

Paper broker should simulate:

market orders
limit orders
stop orders
fills
commission
slippage

Only after this architecture is stable should external brokers be connected.

==================================================
24. BROKER ABSTRACTION
==================================================

Build broker integration behind:

BrokerAdapter

methods:

connect()
disconnect()
get_account()
get_positions()
get_orders()
place_order()
cancel_order()
modify_order()
get_order_status()

Implement:

PaperBrokerAdapter

first.

Then design:

AngelOneBrokerAdapter

for Angel One SmartAPI.

Never hardcode Angel One-specific logic into strategies.

This allows future:

Interactive Brokers
Alpaca
Zerodha
others.

==================================================
25. ANGEL ONE SMARTAPI
==================================================

Prepare infrastructure for:

authentication
instrument lookup
historical market data
quotes
websocket market feed
orders
positions
holdings
order updates

Credentials must only exist in backend environment variables / secret storage.

Never expose API secrets in frontend code.

Default to PAPER MODE.

Show unmistakable:

PAPER

or

LIVE

status across the entire UI.

==================================================
26. EXECUTION ENGINE
==================================================

Separate:

SIGNAL ENGINE

from

EXECUTION ENGINE.

Strategy produces:

TargetPosition

Execution engine determines how to trade toward that target.

This design should eventually support:

market orders
limit orders
TWAP
VWAP
participation algorithms

But initially implement basic execution safely.

==================================================
27. KILL SWITCH
==================================================

Provide a prominent global:

KILL SWITCH

Available from every page.

It should:

disable new orders
cancel pending orders
optionally flatten positions

Flattening requires explicit confirmation.

==================================================
28. MARKET DATA ARCHITECTURE
==================================================

Create standardized containers:

OHLCV
fundamentals
benchmark
sector data
volatility data
macro data
alternative data

Normalize everything before strategies consume it.

Provide caching.

Separate:

raw
normalized
features

data layers.

==================================================
29. DATA PAGE
==================================================

Create a data-management terminal.

Show connected sources:

BROKER
MARKET DATA
FUNDAMENTALS
MACRO
NEWS

Each with:

CONNECTED
DEGRADED
OFFLINE

Show:

last update
latency
number of symbols
storage used

==================================================
30. STRATEGY VERSIONING
==================================================

Every strategy change creates a new version.

Example:

Momentum
v1.0
v1.1
v1.2

Users can:

compare
fork
restore
backtest

versions.

Never overwrite historical strategy definitions used in prior backtests.

==================================================
31. RESEARCH NOTEBOOK
==================================================

Create a notebook/research section.

Research documents can contain:

markdown
charts
tables
backtest links
strategy links
code

Think lightweight institutional research notebook.

Every experiment should be reproducible.

==================================================
32. COMMAND HISTORY
==================================================

Maintain complete history of:

user command
generated plan
actions
results
strategy changes
backtests
deployments

Allow:

"Show me what I changed yesterday."

==================================================
33. NOTIFICATIONS
==================================================

System alerts:

strategy failed
broker disconnected
data stale
risk limit approached
risk limit breached
unexpected position
order rejected
drawdown threshold breached

Create notification center.

==================================================
34. OBSERVABILITY
==================================================

Create SYSTEM HEALTH page.

Show:

market data feed
database
broker
strategy workers
scheduler
AI service

Status:

healthy
degraded
down

Include structured logs.

==================================================
35. TECH STACK
==================================================

Use a maintainable professional architecture.

FRONTEND

Next.js
TypeScript
React
Tailwind
shadcn/ui where useful

Charting:
TradingView Lightweight Charts or another high-performance finance charting library.

State:
Zustand or equivalent.

BACKEND

Python
FastAPI
Pydantic
SQLAlchemy

QUANT

pandas
numpy
scipy
statsmodels
scikit-learn
cvxpy

Optional later:
hmmlearn
Optuna

DATABASE

PostgreSQL

Architecture should allow TimescaleDB later.

CACHE/JOBS

Redis

Background worker:
Celery / RQ / equivalent

REAL-TIME

WebSockets

INFRASTRUCTURE

Docker
docker-compose

Do not introduce Kubernetes yet.

==================================================
36. REPOSITORY STRUCTURE
==================================================

Use a monorepo similar to:

/apps
    /web
    /api

/packages
    /ui
    /types

/quant
    /data
    /features
    /strategies
    /backtest
    /portfolio
    /risk
    /execution
    /brokers
    /validation
    /regimes

/infrastructure

/tests

/docs

==================================================
37. CORE DATA MODELS
==================================================

Design models for:

User
BrokerConnection
Instrument
Dataset
Strategy
StrategyVersion
Backtest
BacktestTrade
Experiment
Deployment
Order
Fill
Position
Portfolio
RiskSnapshot
Alert
Command
AuditEvent

Use migrations.

==================================================
38. API DESIGN
==================================================

Create clean APIs such as:

GET /markets/{symbol}

POST /research/query

POST /strategies

GET /strategies

GET /strategies/{id}

POST /strategies/{id}/fork

POST /backtests

GET /backtests/{id}

POST /backtests/{id}/optimize

POST /deployments

POST /deployments/{id}/pause

GET /portfolio

GET /risk

POST /command

Use WebSockets for:

quotes
backtest progress
order updates
deployment events
logs

==================================================
39. COMMAND PALETTE UX
==================================================

CMD/CTRL + K

opens a large floating command overlay.

Dark glass panel.

Blue glow.

Examples:

Research NVDA

Backtest Momentum v3

Open risk dashboard

Compare backtest 142 and 167

Paper deploy mean-reversion strategy

Search strategy library

The command palette should feel extremely fast.

==================================================
40. MICRO-INTERACTIONS
==================================================

Use subtle animations.

Examples:

blue border glow on hover
smooth tab transitions
loading skeletons
animated command processing
live status dots
chart hover crosshair

Avoid excessive animation.

This is an institutional terminal.

==================================================
41. FIRST DEMO DATA
==================================================

The project must work locally without paid APIs.

Generate realistic synthetic/sample data.

Include:

SPY
QQQ
AAPL
MSFT
NVDA
GOOG
AMZN
RELIANCE
TCS
HDFCBANK
INFY

Create sample strategies.

Create sample backtests.

Create simulated paper positions.

This allows the full UI to be demonstrated immediately.

==================================================
42. FIRST IMPLEMENTATION STRATEGIES
==================================================

Actually implement these backtestable strategies:

SMA crossover

RSI mean reversion

Bollinger mean reversion

Breakout

Time-series momentum

Cross-sectional momentum

Do not make them static UI examples.

They must connect to the actual backtesting engine.

==================================================
43. DEMO COMMANDS
==================================================

The following should eventually function:

"Research NVDA."

"Create a 20-day breakout strategy on NVDA."

"Backtest it from 2020."

"Change breakout period to 50."

"Compare both tests."

"Run a parameter sweep from 10-100 days."

"Show the best 10 parameter combinations."

"Perform walk-forward validation."

"Paper deploy the best validated strategy."

"Show the strategy's current position."

"Why did it enter this trade?"

==================================================
44. EXPLAINABILITY
==================================================

Every trade should allow:

WHY THIS TRADE?

Display:

signal
signal value
threshold
market state
regime
position sizing decision
risk adjustments
execution price

Example:

NVDA LONG

Momentum z-score:
+1.74

Entry threshold:
+1.35

Regime:
Risk-on trend

Target weight:
4.2%

Reduced to:
3.6%

Reason:
portfolio volatility constraint

==================================================
45. REPRODUCIBILITY
==================================================

Backtests must store:

strategy version
parameters
universe
data range
data version where possible
fees
slippage assumptions
benchmark
code/config hash
timestamp

A backtest should always be reproducible.

==================================================
46. SECURITY
==================================================

Never place:

API keys
broker passwords
access tokens

inside frontend code.

Use environment variables / encrypted backend secrets.

Do not log secrets.

Mask sensitive configuration values.

==================================================
47. TESTING
==================================================

Add tests for:

indicator calculations
position sizing
P&L calculations
fees
slippage
portfolio accounting
order simulation
risk calculations
strategy signals
backtest reproducibility

Backtest correctness is more important than visual polish.

==================================================
48. IMPLEMENTATION PHILOSOPHY
==================================================

DO NOT make a giant fake dashboard.

I want a functional system.

Every major UI component should ultimately connect to real backend state.

Avoid hardcoding:

returns
charts
positions
Sharpe
backtest metrics
orders

except inside explicit demo fixtures.

Separate:

UI
domain logic
market data
strategies
backtesting
portfolio
risk
execution
broker integrations

==================================================
49. BUILD ORDER
==================================================

Do NOT attempt the entire platform at once.

Start by inspecting the existing repository.

Preserve working code where sensible.

Then build vertically.

PHASE 1

Application shell
design system
sidebar
command bar
dashboard

PHASE 2

Market data architecture
market research page
charts

PHASE 3

strategy specification system
strategy editor
strategy library

PHASE 4

real backtesting engine
metrics
backtest dashboard

PHASE 5

parameter experiments
comparison
walk-forward
Monte Carlo

PHASE 6

portfolio
risk

PHASE 7

paper execution engine

PHASE 8

Q21 Command natural-language interface

PHASE 9

Angel One SmartAPI integration

PHASE 10

production hardening

==================================================
50. WHAT I WANT YOU TO DO NOW
==================================================

First inspect the ENTIRE current repository.

Understand:

existing architecture
working components
existing strategies
market-data code
backtesting code
frontend
backend
tests
dependencies

Do not unnecessarily rewrite working code.

Then provide:

A. Current repository architecture

B. What can be reused

C. What needs restructuring

D. Proposed final architecture

E. Exact implementation phases

F. Files/directories that will be created or modified

Then immediately start implementing PHASE 1.

Do not create placeholder screens containing meaningless cards.

The Phase 1 UI should already look like a polished institutional trading terminal.

Use the supplied screenshots as the visual reference throughout development.

Pay particular attention to:

near-black background
electric blue highlights
large white typography
minimal borders
large dark chart areas
soft blue glow
clean financial metric cards
dense professional information hierarchy

The finished product should feel like:

an institutional trading desk built around an AI command system,

not a retail trading dashboard.

==================================================
51. INDIA RESIDENT + US EQUITIES ARCHITECTURE
==================================================

The owner/operator of this terminal is an Indian resident.

The platform must therefore explicitly support Indian and US markets using
different regulatory, account, execution and settlement assumptions.

TARGET MARKETS:

INDIA
NSE equities initially

US
NYSE / NASDAQ listed equities and ETFs

PRIMARY BROKERS:

India:
Angel One SmartAPI

United States:
Interactive Brokers

Secondary/future US adapter:
Alpaca

Never couple strategy logic to a specific broker.

==================================================
52. MARKET / BROKER SEPARATION
==================================================

Use this architecture:

Strategy
↓
TargetPortfolio
↓
Portfolio Engine
↓
Risk Engine
↓
Compliance Engine
↓
OMS
↓
EMS
↓
BrokerAdapter

BrokerAdapter implementations:

PaperBrokerAdapter
AngelOneBrokerAdapter
IBKRBrokerAdapter
AlpacaBrokerAdapter

Strategies must NEVER call broker APIs directly.

==================================================
53. COMPLIANCE PROFILE ENGINE
==================================================

Create:

ComplianceProfile

with account/jurisdiction-specific capabilities.

Implement:

INDIA_NSE_RETAIL

INDIA_RESIDENT_US_CASH

PAPER

For INDIA_RESIDENT_US_CASH default to:

margin_enabled = false
short_stock_enabled = false
derivatives_enabled = false
cash_borrowing_enabled = false

us_equities_enabled = true
us_etfs_enabled = true
intraday_enabled = true

settled_cash_required = true
allow_unsettled_cash_reuse = false

Do not rely on an LLM to enforce these rules.

They must be deterministic backend rules.

An AI command which violates account capabilities must be rejected
before reaching the OMS.

==================================================
54. SETTLEMENT ENGINE
==================================================

Implement a first-class settlement ledger.

Track:

total_cash
settled_cash
unsettled_cash
reserved_cash
pending_settlements
available_to_trade

Each pending settlement must contain:

currency
amount
trade_date
settlement_date
source_trade_id

US equity settlement assumptions must be configurable and should
default to the currently applicable T+1 model.

Do NOT assume sale proceeds can immediately be recycled inside a
cash account.

Provide:

CashAvailabilityService

Methods:

get_total_cash()
get_settled_cash()
get_unsettled_cash()
get_buying_cash()
reserve_cash()
release_cash()
process_settlements()

==================================================
55. MULTI-CURRENCY ACCOUNTING
==================================================

Q21 must support:

INR
USD

Every position should expose:

native market value
base currency market value
FX rate
equity P&L
FX P&L
combined P&L

Allow portfolio base currency:

INR

Store the FX rate used for every:

trade
dividend
fee
tax
deposit
withdrawal

==================================================
56. US MARKET DATA ARCHITECTURE
==================================================

Broker market data must NOT be the only research data source.

Create:

MarketDataAdapter

Implement:

SyntheticDataAdapter
CSVDataAdapter
IBKRDataAdapter

Prepare adapters for:

Massive / Polygon-compatible US equity data
Databento or similar institutional providers later

Data architecture:

RAW
↓
NORMALIZED
↓
CORPORATE ACTION ADJUSTMENT
↓
FEATURE STORE
↓
STRATEGY

Support:

1d
1h
30m
15m
5m
1m

Architecture may support seconds/ticks later.

Do not optimize for HFT.

==================================================
57. US SESSION ENGINE
==================================================

Create a proper exchange calendar.

Do not hard-code India clock times.

Use timezone-aware timestamps.

Store timestamps internally as UTC.

Understand:

US Eastern Time
India Standard Time

Support:

pre-market
regular session
after-hours

Strategies can define:

REGULAR_ONLY
REGULAR_PLUS_EXTENDED

==================================================
58. SWING TRADING ENGINE
==================================================

Primary target:

2–20 trading day holding period

Support:

cross-sectional momentum
time-series momentum
mean reversion
breakouts
PEAD
relative strength
sector rotation
volatility expansion
factor strategies

Recommended data:

daily
60-minute
30-minute

Portfolio can rebalance:

daily
weekly
signal-driven

==================================================
59. INTRADAY ENGINE
==================================================

Primary target:

5-minute to 60-minute systematic trading.

Do not design the system around microsecond or HFT assumptions.

Support:

opening-range breakout
intraday momentum
VWAP deviation
relative strength
volume expansion
mean reversion
gap continuation
gap reversal

Every intraday strategy must specify:

session
entry window
exit window
overnight_allowed
max trades
max daily loss
max symbol exposure

For a cash account, order generation must consult SettledCashService
before every purchase.

==================================================
60. CAPITAL SLEEVES
==================================================

Allow a portfolio to divide capital into sleeves:

SWING

INTRADAY_A

INTRADAY_B

CASH_RESERVE

Each strategy may receive a capital allocation.

Track settlement constraints per sleeve while retaining a consolidated
account cash ledger.

==================================================
61. INTERACTIVE BROKERS INTEGRATION
==================================================

IBKR should be the primary US execution adapter.

Initially implement:

IBKRPaperBrokerAdapter

then:

IBKRBrokerAdapter

Prefer an architecture compatible with:

IB Gateway
TWS API

Broker adapter should expose:

connect()
disconnect()
health()
get_account()
get_cash()
get_positions()
get_orders()
get_fills()
place_order()
cancel_order()
modify_order()
get_contract()
get_market_clock()

Implement a persistent order-state machine.

Never assume an order succeeded merely because the API request
returned successfully.

Track states:

CREATED
VALIDATING
SUBMITTED
ACKNOWLEDGED
PARTIALLY_FILLED
FILLED
CANCEL_PENDING
CANCELLED
REJECTED
UNKNOWN

==================================================
62. BROKER SESSION SUPERVISOR
==================================================

Create:

BrokerSessionSupervisor

States:

CONNECTED
DEGRADED
AUTH_REQUIRED
DISCONNECTED
RECONNECTING

If broker authentication or connectivity is lost:

block new orders
do not discard open-order state
retain local position state
attempt reconciliation
notify user

Never blindly resubmit orders after reconnection.

==================================================
63. RECONCILIATION
==================================================

Broker state is ultimately authoritative for live execution.

Continuously reconcile:

local orders vs broker orders
local fills vs broker fills
local positions vs broker positions
local cash vs broker cash

Any unexplained mismatch should generate:

RECONCILIATION ALERT

and optionally disable new orders.

==================================================
64. PAPER TRADING PIPELINE
==================================================

Maintain TWO paper modes:

Q21 SIM

and

BROKER PAPER.

Q21 SIM tests:

strategy
fills
fees
slippage
latency
settlement
portfolio accounting

BROKER PAPER tests:

authentication
broker connectivity
contract mapping
order lifecycle
order rejection handling
broker reconciliation

Required lifecycle:

BACKTEST
↓
WALK-FORWARD
↓
SHADOW
↓
Q21 SIM
↓
IBKR PAPER
↓
LIVE

==================================================
65. US PRE-TRADE RISK
==================================================

Before every order evaluate:

market session
symbol eligibility
data freshness
settled cash
reserved cash
position size
portfolio exposure
strategy allocation
daily P&L
strategy drawdown
portfolio drawdown
order duplication
broker health
market-data health

Then produce:

APPROVE

REJECT

or

REQUIRE_CONFIRMATION

==================================================
66. UNIFIED INDIA + US PORTFOLIO
==================================================

The Portfolio Terminal must aggregate:

Angel One / India

IBKR / US

Display:

global NAV
India NAV
US NAV
INR cash
USD cash
FX exposure
equity exposure
sector exposure
strategy exposure
daily P&L
realized P&L
unrealized P&L
currency P&L

Base currency should be configurable and default to INR.

==================================================
67. TAX / REPORTING LEDGER
==================================================

Maintain sufficient records to assist with Indian foreign asset and
foreign income reporting.

Track:

foreign brokerage accounts
foreign equity holdings
purchase dates
sale dates
USD cost basis
INR-equivalent cost
USD proceeds
INR-equivalent proceeds
FX rates
dividends
foreign withholding tax
broker fees
LRS remittances
TCS records
peak account value
year-end account value

Do NOT present the system as tax advice.

Provide CSV/Excel export for accountant review.

==================================================
68. AI COMMAND AWARENESS
==================================================

Q21 COMMAND must understand market/account constraints.

Example:

"Short NVDA with $10,000."

If active profile is INDIA_RESIDENT_US_CASH:

REJECT

Reason:
Short selling is unavailable under this account capability profile.

Example:

"Buy $5,000 NVDA."

Before presenting execution preview check:

settled cash
portfolio limits
strategy limits
US session
broker health

Example:

"Why wasn't my AAPL order sent?"

Q21 should be able to answer:

Order blocked by pre-trade validation.
Required cash: $4,820
Settled cash: $3,910
Unsettled proceeds: $2,130
Next settlement: tomorrow

==================================================
69. DEPLOYMENT ARCHITECTURE
==================================================

Use a modular monolith first.

Docker services:

web
api
worker
scheduler
postgres
redis

Separate deployment worker responsible for live broker connectivity.

The trading engine must continue operating if the frontend is closed.

Frontend must NEVER be responsible for running strategies.

The browser is only an interface.

Backend workers own:

market data
strategy scheduling
signals
risk checks
orders
broker connectivity
reconciliation

==================================================
70. MOST IMPORTANT RULE
==================================================

Q21 is not a chatbot connected to a brokerage account.

Q21 is a deterministic institutional trading system with an AI
command layer on top.

The AI may:

research
explain
generate
modify
compare
plan

The deterministic system must control:

data
backtests
portfolio accounting
risk
compliance
cash
settlement
orders
execution
broker state.

==================================================
71. REPLACE Q21 COMMAND WITH CODEX
==================================================

IMPORTANT ARCHITECTURAL CHANGE:

Do NOT create a generic custom AI chatbot called "Q21 Command."

The conversational/development intelligence inside Q21 should be
CODEX itself.

Use the supported OpenAI Codex agent architecture, preferably through
the Codex SDK / Codex App Server architecture appropriate for embedding
Codex into a custom interactive application.

The objective is to make the Q21 terminal feel like:

QUANT TERMINAL
+
RESEARCH ENVIRONMENT
+
IDE
+
CODEX

inside one application.

The user should be able to discuss a trading idea with Codex and then
have Codex actually inspect, build, modify, test and validate the
implementation without leaving the terminal.

==================================================
72. CODEX PANEL
==================================================

Create a persistent CODEX panel on the right side of the terminal.

The panel should be collapsible and resizable.

It should use the same:

near-black
electric blue
white typography
subtle borders

visual design as the rest of Q21.

Header:

CODEX

Show:

current thread
active project
active strategy
working branch/worktree
execution status

Main body:

conversation

Bottom:

large command input

Placeholder:

"Ask Codex about this strategy..."

Support:

text
code references
ticker references
strategy references
backtest references
chart references
portfolio references

Example:

@MomentumV4
@Backtest-284
@NVDA

==================================================
73. CODEX IS CONTEXT-AWARE
==================================================

Codex must understand what the user is currently looking at.

The frontend should send structured UI context to the Codex integration.

Examples:

If user is viewing:

NVDA chart

Codex context includes:

symbol
timeframe
visible date range
active indicators
selected strategy
selected trades

If viewing:

Backtest 184

Codex context includes:

strategy ID
strategy version
parameters
universe
performance metrics
trade log
validation results

If viewing:

strategy editor

Codex receives:

strategy ID
relevant source files
current git diff
tests
latest backtests

Never blindly dump the entire application state into every prompt.

Use context selectors.

==================================================
74. CODEX MODES
==================================================

Provide several interaction modes.

DISCUSS

For:

strategy ideas
quant theory
market hypotheses
architecture discussions
research interpretation

Example:

"Would momentum or mean reversion make more sense here?"

--------------------------------------------------

RESEARCH

Codex may use Q21 research tools to investigate hypotheses.

Example:

"Investigate whether this signal performs differently in high-volatility
regimes."

--------------------------------------------------

BUILD

Codex may inspect and modify repository code.

Example:

"Implement this strategy."

--------------------------------------------------

DEBUG

Codex may:

inspect logs
inspect failed tests
inspect backtest failures
trace code
modify implementation
rerun tests

Example:

"Why did yesterday's signal calculation fail?"

--------------------------------------------------

REVIEW

Codex reviews:

strategy code
look-ahead bias
data leakage
portfolio logic
execution assumptions
tests
architecture

Example:

"Audit this strategy for backtest leakage."

==================================================
75. CODEX STRATEGY DEVELOPMENT EXPERIENCE
==================================================

The desired workflow is conversational.

Example:

USER:

"I have an idea. Stocks making 20-day highs with strong relative volume
might continue trending for several days. What do you think?"

CODEX:

Discuss the economic intuition.

Point out potential issues:

market regime
liquidity
gap risk
look-ahead bias
transaction costs
selection bias

Then allow:

[ BUILD STRATEGY ]

USER:

"Build it."

CODEX:

Creates a strategy specification.

Example:

Universe:
S&P 500

Signal:
Close > previous 20-day high

Volume:
> 1.5x 20-day average volume

Holding:
5 days

Sizing:
inverse volatility

Risk:
2% max position

Then:

[ REVIEW SPEC ]
[ IMPLEMENT ]

USER:

"Implement."

Codex creates/modifies the necessary source code.

==================================================
76. CODEX DEVELOPMENT WORKTREE
==================================================

Never let Codex directly modify the production strategy codebase without
isolation.

Each significant development task should run inside:

git branch

or preferably:

git worktree

Example:

codex/momentum-volume-breakout

Codex may:

inspect repository
create files
edit files
run tests
run scripts
run backtests
inspect outputs
create commits/diffs

Show the user:

FILES CHANGED

+ strategies/volume_breakout.py
+ tests/test_volume_breakout.py

Modified:

strategy_registry.py

Then provide:

VIEW DIFF
RUN TESTS
BACKTEST
APPLY
DISCARD

==================================================
77. CODEX STRATEGY DISCUSSION
==================================================

Codex should maintain long-running threads per research project.

Example:

THREAD

"NVDA Momentum Research"

Thread contains:

research discussion
hypotheses
strategy changes
backtest results
charts
failed experiments
successful experiments
code changes

Users should be able to return days later and continue:

"What did we conclude about the volatility filter?"

Codex should have access to the project's recorded research artifacts.

==================================================
78. TALK TO CODEX ABOUT RESULTS
==================================================

Every important object in Q21 should contain:

ASK CODEX

Examples:

BACKTEST

[ Ask Codex ]

PORTFOLIO

[ Ask Codex ]

TRADE

[ Ask Codex ]

CHART

[ Ask Codex ]

RISK REPORT

[ Ask Codex ]

Example:

User opens a poor backtest and presses ASK CODEX.

Context:

MomentumV6
Sharpe: 0.72
Max DD: -22%
Previous version Sharpe: 1.41

User:

"Why did this get worse?"

Codex should investigate:

code changes
parameter changes
trade distribution
regimes
turnover
cost assumptions
data changes

and provide evidence.

==================================================
79. CODEX + CHART
==================================================

The chart should be directly discussable with Codex.

Allow:

SELECT REGION

on chart.

Then:

ASK CODEX

Example:

"Why did the strategy lose money here?"

Codex receives:

symbol
date range
bars
signals
positions
trades
regime
relevant features

Codex can respond:

The strategy entered at 14:35 after the breakout threshold was exceeded.

Relative volume:
1.83x

ATR:
2.7%

The move subsequently reversed.

Potential issue:
breakout entries during elevated intraday volatility.

Then user can say:

"Test an ATR filter."

Codex can immediately create the experiment.

==================================================
80. CODEX EXPERIMENT LOOP
==================================================

This should be one of Q21's flagship features.

USER

"Test an ATR filter."

↓

CODEX

Creates experiment.

↓

Backtest Engine

Runs baseline + variant.

↓

CODEX

Analyzes result.

↓

UI

Displays comparison.

Example:

BASELINE                ATR FILTER

Sharpe
1.02                    1.31

CAGR
14.2%                   15.8%

Max DD
-18.7%                  -12.6%

Trades
842                     616

Turnover
7.2x                    5.4x

Then Codex explains:

what changed
why it may have changed
whether the result is economically plausible
whether additional validation is required

Then suggest:

RUN WALK-FORWARD

rather than automatically declaring the variant superior.

==================================================
81. NATURAL LANGUAGE DEVELOPMENT
==================================================

Codex should understand development commands such as:

"Add regime filtering."

"Change sizing to inverse volatility."

"Refactor the execution module."

"Write tests for settlement accounting."

"Optimize this calculation."

"Explain this function."

"Find why the P&L differs between paper and backtest."

"Add IBKR support for this order type."

"Review the risk engine."

"Create a notebook comparing these three strategies."

Codex should be capable of modifying the actual repository when
the user explicitly asks it to build/change something.

==================================================
82. CODEX TOOL ACCESS
==================================================

Expose Q21 capabilities to Codex through strongly typed tools.

Prefer an MCP/tool architecture.

Example namespace:

q21.market.quote

q21.market.history

q21.market.search

q21.market.fundamentals

q21.strategy.get

q21.strategy.create_spec

q21.strategy.compare

q21.backtest.run

q21.backtest.get

q21.backtest.compare

q21.backtest.optimize

q21.backtest.walk_forward

q21.backtest.monte_carlo

q21.portfolio.get

q21.portfolio.exposure

q21.risk.analyze

q21.data.inspect

q21.logs.query

q21.execution.status

q21.broker.status

Codex may call these tools while reasoning about the project.

==================================================
83. CODEX REPOSITORY ACCESS
==================================================

Codex should have controlled access to the Q21 repository.

Allow:

read files
search files
inspect git history
inspect diffs
create files
modify files
run tests
run approved development commands
run backtests

Codex should understand the entire architecture rather than generating
isolated snippets that do not fit the repository.

Create an AGENTS.md file explaining:

repository architecture
coding standards
quant conventions
testing standards
backtest rules
data conventions
execution safety rules

Codex must read these project instructions.

==================================================
84. CODEX TERMINAL
==================================================

Provide Codex with an isolated development terminal.

Allowed examples:

pytest

ruff

mypy

npm test

npm run build

python scripts/...

git diff

backtest CLI

data validation CLI

Do not give Codex unrestricted access to live broker credentials.

==================================================
85. CODEX ACTION DISPLAY
==================================================

When Codex performs development work, show its activity visually.

Example:

CODEX

● Reading strategy.py
● Reading portfolio.py
● Searching backtest engine
● Modifying momentum.py
● Writing tests
● Running pytest

✓ 128 tests passed

Then:

3 FILES CHANGED

[ VIEW DIFF ]

[ APPLY ]

[ DISCARD ]

The experience should resemble a professional agentic development
environment, not a basic chat widget.

==================================================
86. CODEX DIFF VIEW
==================================================

Create a proper code diff interface.

Side-by-side or unified diff.

Show:

added lines
removed lines
modified files
test results

Allow:

APPLY ALL

APPLY FILE

DISCARD

CONTINUE WITH CODEX

Example:

"Don't use pandas rolling here. Rewrite it using NumPy."

Codex continues editing the same worktree.

==================================================
87. CODEX CAN CREATE STRATEGIES
==================================================

Strategy development should use two artifacts:

StrategySpec

and

StrategyImplementation

Codex initially creates:

StrategySpec

including:

hypothesis
universe
signal
entry
exit
holding period
sizing
portfolio constraints
cost assumptions
risk rules
validation plan

Only after specification approval should implementation begin.

This prevents vague conversational ideas from immediately becoming code.

==================================================
88. RESEARCH MEMORY
==================================================

Store persistent project-level research artifacts.

Not generic conversational memory.

For each strategy/project store:

hypotheses
decisions
experiments
backtests
parameter changes
rejected approaches
research notes
code versions

Codex can retrieve this context.

Example:

USER:

"Why did we remove the RSI filter?"

CODEX:

Search the project history and identify the experiment where the decision
was made.

==================================================
89. CODEX PROJECTS
==================================================

Allow creation of Codex research projects.

Example:

US Momentum Research

Pairs Trading

NVDA Intraday

Regime Engine

Execution Improvements

Each project contains:

Codex threads
strategies
backtests
datasets
research notes
code branches
experiments

This becomes the primary workspace organization model.

==================================================
90. CODEX PARALLEL AGENTS
==================================================

Design for multiple Codex tasks to run independently.

Example:

Main conversation:

"Improve this strategy."

Codex can launch separate development/research tasks conceptually such as:

Agent A:
audit signal construction

Agent B:
test transaction cost sensitivity

Agent C:
review implementation for leakage

Agent D:
run regime analysis

Results return to the primary Codex thread.

Do not allow concurrent agents to modify the same production files
without worktree isolation and controlled merging.

==================================================
91. CODEX + BACKTEST JOBS
==================================================

Backtests may take longer than a normal HTTP request.

Codex should submit asynchronous jobs.

Example:

Codex
↓
q21.backtest.run()
↓
Job ID
↓
worker queue
↓
results
↓
Codex notified

Frontend displays:

BACKTEST RUNNING

42%

The Codex conversation must remain usable while jobs execute.

==================================================
92. CODEX RESEARCH SAFETY
==================================================

Codex may freely:

research
discuss
write strategy code
modify research code
run backtests
run simulations

Codex may NOT directly:

place live broker orders
disable compliance checks
disable risk limits
access raw broker credentials
modify production execution policy
bypass deployment approval

The live trading boundary must remain deterministic.

==================================================
93. LIVE STRATEGY CODE PROMOTION
==================================================

Codex development code must NEVER immediately replace a running strategy.

Required lifecycle:

CODEX WORKTREE
↓
TESTS
↓
BACKTEST
↓
VALIDATION
↓
USER REVIEW
↓
STRATEGY VERSION CREATED
↓
PAPER
↓
DEPLOYMENT APPROVAL
↓
LIVE

A running deployment references an immutable:

StrategyVersion

and code/config hash.

Codex modifying source code must not alter the immutable version currently
being traded.

==================================================
94. CODEX EXECUTION QUESTIONS
==================================================

Codex may have READ-ONLY access to live execution state.

This allows questions like:

"Why didn't NVDA execute?"

"Why is the position smaller than requested?"

"Why was this order rejected?"

"What changed in today's P&L?"

Codex may inspect:

orders
fills
risk decisions
broker status
market state
strategy signals

but cannot directly override them.

Example response:

NVDA order rejected by PreTradeRiskService.

Requested:
$6,200

Available settled cash:
$4,810

Reserved:
$1,250

Therefore available:
$3,560.

==================================================
95. CODEX COMMAND PALETTE
==================================================

CTRL/CMD + K should open CODEX.

This should replace the previously proposed generic Q21 command assistant.

Examples:

"Open NVDA."

"Research NVDA."

"Explain this chart."

"Build a breakout strategy."

"Backtest current strategy."

"Fix this failing test."

"Compare versions."

"Audit for look-ahead bias."

"Open portfolio risk."

"Why wasn't my order executed?"

Commands may result in:

navigation
conversation
research
development
backtest
analysis

through Codex.

==================================================
96. CODEX UI EXPERIENCE
==================================================

The Codex panel should feel deeply integrated into the application.

Do not make it look like an embedded ChatGPT webpage.

Use the Q21 visual system.

Messages may contain interactive financial components:

strategy cards
metric tables
mini equity curves
parameter comparison cards
code diffs
trade cards
risk warnings
backtest results

Example Codex response:

"I tested your hypothesis."

Then directly render:

┌──────────────────────────────┐
│ Momentum + ATR Filter        │
│                              │
│ Sharpe              1.31     │
│ CAGR                15.8%    │
│ Max DD             -12.6%    │
│ Trades                616    │
│                              │
│ [RESULTS] [DIFF] [VALIDATE]  │
└──────────────────────────────┘

==================================================
97. CODEX ARCHITECTURE
==================================================

Recommended architecture:

Q21 WEB
↓
WebSocket / API
↓
CodexGateway
↓
Codex SDK / Codex App Server
↓
Codex Thread

Codex has access to:

Repository Worktree
Development Sandbox
Q21 MCP Server
Backtest Jobs
Research Data
Logs

Q21 MCP Server connects to:

MarketDataService
ResearchService
StrategyService
BacktestService
ExperimentService
PortfolioService
RiskService
DataService
ExecutionReadService

Live execution remains separately controlled by:

PreTradeRiskService
ComplianceService
OMS
EMS
BrokerAdapter

==================================================
98. CODEX GATEWAY
==================================================

Create a backend service:

CodexGateway

Responsibilities:

Codex authentication/session handling
thread management
streaming responses
tool registration
project context
worktree management
approval handling
job events
Codex status

Do not call Codex directly from browser JavaScript.

Architecture:

Browser
↓
Q21 API
↓
CodexGateway
↓
Codex

Keep credentials and sensitive integration configuration server-side.

==================================================
99. CODEX STREAMING
==================================================

Codex responses and actions should stream into the terminal.

Use WebSockets or equivalent.

UI should show meaningful agent activity.

Example:

Understanding request...

Inspecting momentum strategy...

Reviewing 42 trades...

Running transaction-cost sensitivity...

Backtest submitted...

Analyzing results...

Avoid exposing private/internal chain-of-thought.

Show tool activity, progress, files and results instead.

==================================================
100. CORE PRODUCT PHILOSOPHY
==================================================

The defining experience of Q21 should become:

THINK WITH CODEX
↓
RESEARCH WITH CODEX
↓
BUILD WITH CODEX
↓
TEST WITH CODEX
↓
VALIDATE WITH CODEX
↓
PAPER TRADE
↓
DEPLOY THROUGH Q21

Codex is the research and development partner.

Q21 is the deterministic quantitative trading infrastructure.

The user should never need to leave the Q21 terminal to go to another
IDE just to discuss, build, modify or debug a systematic strategy.
