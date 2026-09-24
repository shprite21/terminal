export type Sleeve = { strategy: string; budget: number; lookback: number };
export type ResearchRequest = {
  name: string;
  hypothesis: string;
  data_mode: 'yahoo' | 'massive' | 'synthetic' | 'demo';
  symbols: string[];
  benchmark: string;
  period: '2y' | '5y' | '10y';
  sleeves: Sleeve[];
  long_only: boolean;
  initial_capital: number;
  volatility_target: number;
  max_asset_weight: number;
  max_gross_exposure: number;
  max_net_exposure: number;
  drawdown_limit: number;
  rebalance: 'daily' | 'weekly' | 'monthly';
  commission_bps: number;
  slippage_bps: number;
  annual_borrow_bps: number;
  regime_enabled: boolean;
  defensive_multiplier: number;
  constructive_multiplier: number;
  train_window: number;
  test_window: number;
  min_oos_sharpe: number;
  snapshot_run_id: string | null;
};
export type Metrics = Record<string, number | null>;
export type Catalog = {
  strategies: {
    id: string;
    name: string;
    family: string;
    lookback: number;
    description: string;
  }[];
  unavailable: { name: string; reason: string }[];
  demo_symbols: string[];
};
export type Evidence = {
  request: ResearchRequest;
  data: {
    source: string;
    data_mode: string;
    currency: string;
    benchmark: string;
    retrieved_at: string;
    start_date: string;
    end_date: string;
    evaluation_start: string;
    observations: number;
    warmup_observations: number;
    age_calendar_days: number;
    symbols: string[];
    snapshot_sha256: string;
  };
  provenance: {
    git_revision: string;
    working_tree_dirty: boolean | null;
    source_sha256: string;
  };
  metrics: Metrics;
  equity_curve: {
    date: string;
    portfolio: number;
    benchmark: number;
    gross: number;
    drawdown: number;
    regime: number;
  }[];
  validation: {
    method: string;
    metrics: Metrics;
    complete_windows: number;
    observations: number;
    windows: {
      window_id: number;
      train_start: string;
      train_end: string;
      test_start: string;
      test_end: string;
      train_sharpe: number;
      test_sharpe: number;
      test_total_return: number;
      test_max_drawdown: number;
    }[];
  };
  cost_stress: {
    multiplier: number;
    commission_bps: number;
    slippage_bps: number;
    cost_adjusted_sharpe: number;
    total_return: number;
    max_drawdown: number;
  }[];
  robustness: {
    lookback_scale: number;
    sharpe: number;
    total_return: number;
    max_drawdown: number;
  }[];
  sleeves: {
    strategy: string;
    name: string;
    budget: number;
    lookback: number;
    sharpe: number;
    total_return: number;
    max_drawdown: number;
  }[];
  correlations: ({ strategy: string } & Record<
    string,
    string | number | null
  >)[];
  regime: {
    current: string;
    enabled: boolean;
    multiplier: number;
    performance: ({ regime: number } & Metrics)[];
    transitions: ({ regime: number } & Metrics)[];
  };
  risk: Metrics;
  holdings: {
    symbol: string;
    current_weight: number;
    target_weight: number;
    change: number;
    indicative_notional: number;
    risk_contribution: number | null;
    return_contribution: number;
    signals: Record<string, number>;
  }[];
  attribution: {
    cost_contribution: number;
    total_return: number;
    asset_contribution: number;
  };
  proposal: {
    as_of: string;
    turnover: number;
    estimated_cost: number;
    basis: string;
  };
  scenarios: { scenario: string; return: number; date: string | null }[];
  gates: {
    name: string;
    status: 'pass' | 'review' | 'blocked';
    detail: string;
  }[];
  paper_candidate_eligible: boolean;
  quality: {
    flag_count: number;
    stale_prices: Record<string, unknown>[];
    outliers: Record<string, unknown>[];
    adjustment_warnings: Record<string, unknown>[];
  };
  limitations: string[];
};
export type Decision = {
  status: 'watchlist' | 'paper_candidate' | 'rejected';
  rationale: string;
  recorded_at: string;
};
export type ResearchJob = {
  run_id: string;
  name: string;
  created_at: string;
  updated_at: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  stage: string;
  request: ResearchRequest;
  decision: Decision | null;
  decisions: Decision[];
  metrics: Metrics | null;
  validation_metrics?: Metrics;
  result?: Evidence;
  error: string | null;
  snapshot_sha256?: string;
  evaluation_start?: string;
  end_date?: string;
  paper_candidate_eligible?: boolean;
};

export const defaults: ResearchRequest = {
  name: 'Regime allocation study',
  hypothesis:
    'Momentum and short-term reversal may diversify returns when sized to a regime-aware risk budget.',
  data_mode: 'yahoo',
  symbols: ['AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'JPM', 'XOM', 'UNH'],
  benchmark: 'SPY',
  period: '5y',
  sleeves: [
    { strategy: 'time_series_momentum', budget: 60, lookback: 126 },
    { strategy: 'mean_reversion', budget: 40, lookback: 20 },
  ],
  long_only: true,
  initial_capital: 1000000,
  volatility_target: 0.1,
  max_asset_weight: 0.2,
  max_gross_exposure: 1,
  max_net_exposure: 1,
  drawdown_limit: 0.15,
  rebalance: 'weekly',
  commission_bps: 2,
  slippage_bps: 3,
  annual_borrow_bps: 100,
  regime_enabled: true,
  defensive_multiplier: 0.5,
  constructive_multiplier: 1,
  train_window: 252,
  test_window: 63,
  min_oos_sharpe: 0.5,
  snapshot_run_id: null,
};
const ranges: Partial<Record<keyof ResearchRequest, [number, number]>> = {
  initial_capital: [1000, 1e9],
  volatility_target: [0.01, 0.6],
  max_asset_weight: [0.01, 1],
  max_gross_exposure: [0.1, 2],
  max_net_exposure: [0, 2],
  drawdown_limit: [0.01, 0.8],
  commission_bps: [0, 100],
  slippage_bps: [0, 100],
  annual_borrow_bps: [0, 5000],
  defensive_multiplier: [0, 1],
  constructive_multiplier: [0, 1.5],
  train_window: [126, 756],
  test_window: [21, 252],
  min_oos_sharpe: [-2, 5],
};
const strategyIds = new Set([
  'cross_sectional_momentum',
  'time_series_momentum',
  'moving_average_trend',
  'mean_reversion',
  'bollinger_band',
  'rsi_reversal',
  'atr_breakout',
  'volatility_compression',
]);

export function validateResearch(request: ResearchRequest): ResearchRequest {
  if (!request || typeof request !== 'object')
    throw new Error('A research configuration is required.');
  if (
    request.snapshot_run_id !== null &&
    !/^\d{8}T\d{6}Z-[a-f0-9]{8}$/.test(request.snapshot_run_id)
  )
    throw new Error('Snapshot source must be a saved experiment ID.');
  if (
    typeof request.name !== 'string' ||
    !request.name.trim() ||
    request.name.length > 80
  )
    throw new Error('Use a study name of 1–80 characters.');
  if (
    typeof request.hypothesis !== 'string' ||
    request.hypothesis.trim().length < 10 ||
    request.hypothesis.length > 2000
  )
    throw new Error('Record the investment hypothesis in 10–2,000 characters.');
  if (
    !['yahoo', 'massive', 'synthetic', 'demo'].includes(request.data_mode) ||
    !['2y', '5y', '10y'].includes(request.period) ||
    !['daily', 'weekly', 'monthly'].includes(request.rebalance)
  )
    throw new Error(
      'Select a valid data source, history and rebalance schedule.',
    );
  if (
    typeof request.long_only !== 'boolean' ||
    typeof request.regime_enabled !== 'boolean'
  )
    throw new Error('Mandate and regime switches must be true or false.');
  if (
    !Array.isArray(request.symbols) ||
    request.symbols.length < 2 ||
    request.symbols.length > 30 ||
    request.symbols.some((s) => typeof s !== 'string')
  )
    throw new Error('Choose 2–30 unique equity or ETF tickers.');
  if(request.data_mode==='massive'&&request.period!=='2y')throw new Error('Massive supports up to two years in this adapter. Select 2y.');
  const symbols = request.symbols.map((s) => s.trim().toUpperCase());
  const benchmark =
    typeof request.benchmark === 'string'
      ? request.benchmark.trim().toUpperCase()
      : '';
  if (
    new Set(symbols).size !== symbols.length ||
    [...symbols, benchmark].some(
      (s) => !/^[A-Z0-9^][A-Z0-9.^=-]{0,19}$/.test(s),
    )
  )
    throw new Error(
      'Use unique Yahoo tickers and a valid same-currency benchmark.',
    );
  for (const [key, [min, max]] of Object.entries(ranges)) {
    const value = request[key as keyof ResearchRequest];
    if (
      typeof value !== 'number' ||
      !Number.isFinite(value) ||
      value < min ||
      value > max
    )
      throw new Error(
        `${key.replaceAll('_', ' ')} must be between ${min} and ${max}.`,
      );
  }
  if (
    !Number.isInteger(request.train_window) ||
    !Number.isInteger(request.test_window)
  )
    throw new Error('Validation windows must be whole trading sessions.');
  if (
    !Array.isArray(request.sleeves) ||
    !request.sleeves.length ||
    request.sleeves.length > 8 ||
    request.sleeves.some(
      (s) =>
        !s ||
        !strategyIds.has(s.strategy) ||
        !Number.isFinite(s.budget) ||
        s.budget <= 0 ||
        s.budget > 100 ||
        !Number.isInteger(s.lookback) ||
        s.lookback < 5 ||
        s.lookback > 252,
    )
  )
    throw new Error(
      'Each sleeve needs an available strategy, positive budget and a 5–252 session lookback.',
    );
  if (
    new Set(request.sleeves.map((s) => s.strategy)).size !==
    request.sleeves.length
  )
    throw new Error('Select each strategy only once.');
  if (
    Math.abs(request.sleeves.reduce((sum, s) => sum + s.budget, 0) - 100) > 1e-6
  )
    throw new Error('Strategy budgets must total 100%.');
  if (
    request.max_net_exposure > request.max_gross_exposure ||
    (request.long_only && request.max_net_exposure === 0)
  )
    throw new Error(
      'Net limit must fit within gross; long-only needs a positive net limit.',
    );
  if (
    request.train_window <
    Math.max(...request.sleeves.map((s) => s.lookback)) + 2
  )
    throw new Error(
      'Training history must exceed the longest signal lookback by at least 2 sessions.',
    );
  return {
    ...request,
    name: request.name.trim(),
    hypothesis: request.hypothesis.trim(),
    symbols,
    benchmark,
  };
}

export const apiOrigin = '/integrations/engine';
export async function researchApi<T>(path: string, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiOrigin}/api/research${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      signal: AbortSignal.timeout(15000),
    });
  } catch {
    throw new Error(
      'Research API unavailable. Reconnect to start the research engine.',
    );
  }
  const payload = (await response.json()) as { detail?: unknown };
  if (!response.ok) {
    const detail = payload.detail;
    throw new Error(
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail
              .map(
                (item: { msg: string; loc: string[] }) =>
                  `${item.loc.slice(1).join(' ')}: ${item.msg}`,
              )
              .join('; ')
          : 'The research request failed.',
    );
  }
  return payload as T;
}

export function comparableRuns(jobs: ResearchJob[]): boolean {
  if (jobs.length < 2) return true;
  const first = jobs[0];
  return jobs.every(
    (job) =>
      Boolean(job.snapshot_sha256) &&
      job.snapshot_sha256 === first.snapshot_sha256 &&
      job.evaluation_start === first.evaluation_start &&
      job.end_date === first.end_date &&
      job.request.train_window === first.request.train_window &&
      job.request.test_window === first.request.test_window,
  );
}

export const pct = (value: number | null | undefined, digits = 2) =>
  value == null || !Number.isFinite(value)
    ? '—'
    : `${(value * 100).toFixed(digits)}%`;
export const num = (value: number | null | undefined, digits = 2) =>
  value == null || !Number.isFinite(value)
    ? '—'
    : value.toLocaleString(undefined, { maximumFractionDigits: digits });
