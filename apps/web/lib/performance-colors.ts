/** Display-only sign styling. Zero and unavailable values remain neutral. */
export function isPerformanceValue(key: string, context = '') {
  return /pnl|p&l|profit|realized|return|drawdown/i.test(key)
    || (/attribution|regime_performance/i.test(context)
      && ['momentum', 'mean_reversion', 'statistical_arbitrage'].includes(key));
}

export function performanceTone(key: string, value: unknown, context = '') {
  if (!isPerformanceValue(key, context) || typeof value !== 'number' || !Number.isFinite(value) || value === 0) return undefined;
  return value > 0 ? 'positive' : 'negative';
}
