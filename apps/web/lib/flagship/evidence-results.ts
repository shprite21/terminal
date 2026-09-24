export type Row = Record<string, unknown>;

export function chartAxis(rows: Row[], explicit?: string): string | undefined {
  return explicit || ['date', 'timestamp', 'step', 'time_ms', 'elapsed_bar'].find(key => key in (rows[0] || {}));
}

export function useGenericEquityCharts(artifact: Row, equity: Row[] | undefined): boolean {
  // Declared charts own their units and series. Basket comparisons, for example,
  // have baseline/optimized columns rather than a single account-equity column.
  return !(Array.isArray(artifact.charts) && artifact.charts.length > 0)
    && Boolean(equity?.some(row => typeof row.equity === 'number' && Number.isFinite(row.equity)));
}

// Convert only timestamps carrying an explicit zone. Never infer the user's zone
// for old records whose source did not specify one.
export function candleTimestamp(value: unknown): string {
  const raw = String(value ?? '');
  if (!/(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)) return raw ? `${raw} (source time)` : 'Unknown time';
  const parsed = new Date(raw);
  return Number.isFinite(parsed.getTime()) ? parsed.toISOString().replace('T', ' ').replace('.000Z', ' UTC').replace('Z', ' UTC') : raw;
}

export function normalizedPeriods(results: Record<string, Row>): Row[] {
  const rows: Row[] = [];
  for (const [label, result] of Object.entries(results)) {
    const initial = Number((result.configuration as Row)?.initial_cash);
    if (!(initial > 0) || !Array.isArray(result.equity)) continue;
    result.equity.forEach((point: Row, index: number) => {
      rows[index] ??= {elapsed_bar: index};
      if (typeof point.equity === 'number') rows[index][label] = point.equity / initial * 100;
    });
  }
  return rows;
}

export function drawdownRows(equity: Row[], initial: number): Row[] {
  let peak = initial;
  return equity.map(row => {
    const value = Number(row.equity);
    peak = Math.max(peak, value);
    return {...row, drawdown_percent: peak > 0 ? (value / peak - 1) * 100 : null};
  });
}

// Preserve each displayed series' extrema per bucket; exports/tables remain complete.
export function chartRows(rows: Row[], keys: string[], limit = 1200): Row[] {
  if (rows.length <= limit) return rows;
  const width = Math.ceil(rows.length / Math.max(1, Math.floor(limit / (2 * keys.length + 2))));
  const selected = new Set<number>([0, rows.length - 1]);
  for (let start = 0; start < rows.length; start += width) {
    const end = Math.min(rows.length, start + width);
    selected.add(start); selected.add(end - 1);
    for (const key of keys) {
      let min = -1, max = -1;
      for (let i = start; i < end; i++) {
        if (typeof rows[i][key] !== 'number') continue;
        if (min < 0 || Number(rows[i][key]) < Number(rows[min][key])) min = i;
        if (max < 0 || Number(rows[i][key]) > Number(rows[max][key])) max = i;
      }
      if (min >= 0) selected.add(min);
      if (max >= 0) selected.add(max);
    }
  }
  return [...selected].sort((a,b) => a-b).map(index => rows[index]);
}
