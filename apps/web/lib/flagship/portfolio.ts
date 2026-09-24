export type Holding = { ticker: string; weight: number };
export type PortfolioDraft = {
  name: string;
  source?: 'yahoo' | 'massive' | 'synthetic';
  holdings: Holding[];
  period: '6mo' | '1y' | '2y' | '5y';
  benchmark: string;
  initial_capital: number;
  risk_free_rate: number;
};
export type Analysis = {
  source: string;
  retrieved_at: string;
  currency: string;
  start_date: string;
  end_date: string;
  observations: number;
  request: Omit<PortfolioDraft, 'name'>;
  metrics: Record<string, number | null>;
  holdings: {
    ticker: string;
    target_weight: number;
    ending_weight: number;
    latest_adjusted_close: number;
    total_return: number;
    return_contribution: number;
    annualized_volatility: number;
    initial_allocation: number;
    ending_value: number;
  }[];
  equity_curve: {
    date: string;
    portfolio: number;
    benchmark: number;
    drawdown: number;
  }[];
  warnings: string[];
};

export const storageKey = 'shprite.portfolios.v1';
// Read the former key without deleting it, so renaming never loses saved portfolios.
export const legacyStorageKey = 'axiom.portfolios.v1';
export const tickerPattern = /^[A-Z0-9^][A-Z0-9.^=-]{0,19}$/;
export const starter: PortfolioDraft = {
  name: 'My equity portfolio',
  period: '1y',
  benchmark: 'SPY',
  initial_capital: 100000,
  risk_free_rate: 0,
  holdings: [
    { ticker: 'AAPL', weight: 25 },
    { ticker: 'MSFT', weight: 25 },
    { ticker: 'NVDA', weight: 20 },
    { ticker: 'JPM', weight: 15 },
    { ticker: 'XOM', weight: 15 },
  ],
};

export function parsePortfolio(input: unknown): PortfolioDraft {
  if (!input || typeof input !== 'object')
    throw new Error('A portfolio is required.');
  const value = input as Record<string, unknown>;
  if (
    typeof value.name !== 'string' ||
    !value.name.trim() ||
    value.name.trim().length > 60
  )
    throw new Error('Give the portfolio a name of 1–60 characters.');
  if (
    !Array.isArray(value.holdings) ||
    !value.holdings.length ||
    value.holdings.length > 30
  )
    throw new Error('Choose between 1 and 30 holdings.');
  if (value.source!==undefined&&!['yahoo','massive','synthetic'].includes(String(value.source)))throw new Error('Choose Yahoo, Massive or Synthetic.');
  const holdings = value.holdings.map((item: unknown) => {
    if (!item || typeof item !== 'object') throw new Error('Invalid holding.');
    const holding = item as Record<string, unknown>;
    const ticker =
      typeof holding.ticker === 'string'
        ? holding.ticker.trim().toUpperCase()
        : '';
    if (!tickerPattern.test(ticker))
      throw new Error('Use valid Yahoo Finance ticker symbols.');
    if (
      typeof holding.weight !== 'number' ||
      !Number.isFinite(holding.weight) ||
      holding.weight <= 0 ||
      holding.weight > 100
    )
      throw new Error(
        'Each weight must be greater than 0 and no more than 100%.',
      );
    return { ticker, weight: holding.weight };
  });
  if (new Set(holdings.map((h) => h.ticker)).size !== holdings.length)
    throw new Error('Each ticker must appear only once.');
  if (Math.abs(holdings.reduce((sum, h) => sum + h.weight, 0) - 100) > 0.000001)
    throw new Error('Portfolio weights must total exactly 100%.');
  if (!['6mo', '1y', '2y', '5y'].includes(String(value.period)))
    throw new Error('Choose a supported history window.');
  const benchmark =
    typeof value.benchmark === 'string'
      ? value.benchmark.trim().toUpperCase()
      : '';
  if (!tickerPattern.test(benchmark))
    throw new Error('Enter a valid benchmark ticker.');
  if (
    typeof value.initial_capital !== 'number' ||
    !Number.isFinite(value.initial_capital) ||
    value.initial_capital < 1 ||
    value.initial_capital > 1e9
  )
    throw new Error('Initial capital must be between 1 and 1,000,000,000.');
  if (
    typeof value.risk_free_rate !== 'number' ||
    !Number.isFinite(value.risk_free_rate) ||
    value.risk_free_rate < 0 ||
    value.risk_free_rate > 25
  )
    throw new Error('Annual risk-free rate must be between 0 and 25%.');
  return {
    name: value.name.trim(),
    ...(value.source===undefined?{}:{source:value.source as PortfolioDraft['source']}),
    holdings,
    benchmark,
    period: value.period as PortfolioDraft['period'],
    initial_capital: value.initial_capital,
    risk_free_rate: value.risk_free_rate,
  };
}

export function equalWeights(holdings: Holding[]): Holding[] {
  if (!holdings.length) return [];
  const weight = Math.floor(10000 / holdings.length) / 100;
  return holdings.map((holding, index) => ({
    ...holding,
    weight:
      index === holdings.length - 1
        ? Math.round((100 - weight * index) * 100) / 100
        : weight,
  }));
}

export function readSaved(raw: string | null): PortfolioDraft[] {
  if (!raw) return [];
  const parsed: unknown = JSON.parse(raw);
  if (!Array.isArray(parsed) || parsed.length > 50)
    throw new Error('Invalid saved portfolio file.');
  const portfolios = parsed.map(parsePortfolio);
  if (new Set(portfolios.map((p) => p.name)).size !== portfolios.length)
    throw new Error('Duplicate saved portfolio names.');
  return portfolios;
}

export function equityCsv(result: Analysis): string {
  return [
    'date,portfolio_value,benchmark_value,drawdown',
    ...result.equity_curve.map((row) =>
      [row.date, row.portfolio, row.benchmark, row.drawdown].join(','),
    ),
  ].join('\n');
}

export function loadSaved(storage: {
  getItem: (key: string) => string | null;
}): PortfolioDraft[] {
  // A deliberately empty new snapshot must not resurrect the old portfolio list.
  return readSaved(
    storage.getItem(storageKey) ?? storage.getItem(legacyStorageKey),
  );
}

export function mergeSaved(existing: PortfolioDraft[], incoming: PortfolioDraft[]): PortfolioDraft[] {
  const merged = existing.map(parsePortfolio);
  for (const raw of incoming) {
    const portfolio = parsePortfolio(raw);
    if (merged.some(item => JSON.stringify(item) === JSON.stringify(portfolio))) continue;
    const original = portfolio.name;
    let suffix = 1;
    while (merged.some(item => item.name === portfolio.name)) {
      const ending = ` (import ${suffix++})`;
      portfolio.name = original.slice(0,60-ending.length) + ending;
    }
    merged.push(portfolio);
  }
  if (merged.length > 50) throw new Error('Import would exceed 50 portfolios. No saved portfolios were changed.');
  return merged;
}
