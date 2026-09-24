'use client';

import { useState } from 'react';
import { Download, Loader2, ShieldCheck } from 'lucide-react';
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  XAxis,
  YAxis,
} from 'recharts';
import { Button } from '@/components/ui/button';
import {
  NativeSelect,
  NativeSelectOption,
} from '@/components/ui/native-select';
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart';
import {
  DataTable,
  Field,
  Panel,
  Stat,
  Status,
} from '@/components/flagship/research-primitives';
import {
  apiOrigin,
  num,
  pct,
  type Decision,
  type Evidence,
  type ResearchJob,
} from '@/lib/flagship/research';

const date = (value: string) => value.slice(0, 10);
const regimeName = (value: number) =>
  ['Defensive', 'Neutral', 'Constructive'][value];
const chartConfig = {
  portfolio: { label: 'Net portfolio', color: '#2563eb' },
  benchmark: { label: 'Benchmark', color: '#94a3b8' },
  gross: { label: 'Gross portfolio', color: '#60a5fa' },
  drawdown: { label: 'Drawdown', color: '#f87171' },
};

function Gates({ result }: { result: Evidence }) {
  return (
    <div className="divide-y">
      {result.gates.map((gate) => (
        <div
          key={gate.name}
          className="flex items-start justify-between gap-4 py-3 first:pt-0"
        >
          <div>
            <p className="text-sm font-medium">{gate.name}</p>
            <p className="mt-1 text-sm text-muted-foreground">{gate.detail}</p>
          </div>
          <Status value={gate.status} />
        </div>
      ))}
    </div>
  );
}
function Artifact({
  runId,
  name,
  label,
}: {
  runId: string;
  name: string;
  label: string;
}) {
  return (
    <a
      className="inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm hover:bg-secondary"
      href={`${apiOrigin}/api/research/runs/${runId}/artifacts/${name}`}
      download
    >
      <Download className="size-3.5" />
      {label}
    </a>
  );
}
function EquityChart({
  result,
  drawdown = false,
}: {
  result: Evidence;
  drawdown?: boolean;
}) {
  return (
    <ChartContainer
      config={chartConfig}
      className={drawdown ? 'h-[170px] w-full' : 'h-[310px] w-full'}
    >
      <ComposedChart data={result.equity_curve}>
        <CartesianGrid vertical={false} strokeDasharray="3 5" />
        <XAxis
          dataKey="date"
          tickFormatter={(value) => String(value).slice(0, 7)}
          minTickGap={60}
          tickLine={false}
        />
        <YAxis
          width={65}
          tickFormatter={(value) =>
            drawdown ? pct(value, 0) : `${num(value / 1000, 0)}k`
          }
          tickLine={false}
          axisLine={false}
          domain={['auto', 'auto']}
        />
        <ChartTooltip
          content={
            <ChartTooltipContent
              formatter={(value, name) => (
                <span>
                  {String(name)}:{' '}
                  {drawdown
                    ? pct(Number(value))
                    : `${num(Number(value))} ${result.data.currency}`}
                </span>
              )}
            />
          }
        />
        <Area
          dataKey={drawdown ? 'drawdown' : 'portfolio'}
          stroke={drawdown ? 'var(--color-drawdown)' : 'var(--color-portfolio)'}
          fill={drawdown ? 'var(--color-drawdown)' : 'var(--color-portfolio)'}
          fillOpacity={0.08}
          strokeWidth={2}
          isAnimationActive={false}
        />
        {!drawdown && (
          <Line
            dataKey="benchmark"
            stroke="var(--color-benchmark)"
            dot={false}
            strokeDasharray="5 4"
            isAnimationActive={false}
          />
        )}
        {!drawdown && (
          <Line
            dataKey="gross"
            stroke="var(--color-gross)"
            dot={false}
            strokeWidth={1}
            isAnimationActive={false}
          />
        )}
      </ComposedChart>
    </ChartContainer>
  );
}

export function ResearchEvidence({
  job,
  view,
  onDecision,
}: {
  job: ResearchJob & { result: Evidence };
  view: 'overview' | 'validation' | 'portfolio';
  onDecision: (status: Decision['status'], rationale: string) => Promise<void>;
}) {
  const [status, setStatus] = useState<Decision['status']>('watchlist');
  const [rationale, setRationale] = useState('');
  const [saving, setSaving] = useState(false);
  const result = job.result;
  async function saveDecision() {
    if (saving || rationale.trim().length < 10) return;
    setSaving(true);
    try {
      await onDecision(status, rationale);
      setRationale('');
    } finally {
      setSaving(false);
    }
  }
  return (
    <>
      <div
        className={`rounded-lg border p-3 text-sm ${['demo','synthetic'].includes(result.data.data_mode) ? 'border-amber-300/30 text-amber-100' : 'text-muted-foreground'}`}
      >
        <strong>{result.data.source}</strong> · {result.data.currency} ·{' '}
        {result.data.start_date} → {result.data.end_date} ·{' '}
        {result.data.observations} sessions
        {['demo','synthetic'].includes(result.data.data_mode)
          ? ' · SYNTHETIC — no market inference'
          : result.data.age_calendar_days > 5
            ? ` · DATA STALE (${result.data.age_calendar_days} calendar days)`
            : ''}
        <p className="mt-1 text-xs">
          Retrieved {new Date(result.data.retrieved_at).toLocaleString()} ·
          Benchmark: {result.data.benchmark}
        </p>
      </div>
      {view === 'overview' && (
        <>
          <div className="grid grid-cols-2 gap-3 2xl:grid-cols-4">
            <Stat
              label="OOS Sharpe"
              value={num(result.validation.metrics.sharpe)}
              detail={`${result.validation.complete_windows} complete test windows`}
            />
            <Stat
              label="OOS net return"
              value={pct(result.validation.metrics.total_return)}
              detail={`${result.validation.observations} test sessions`}
            />
            <Stat
              label="OOS drawdown"
              value={pct(result.validation.metrics.max_drawdown)}
              detail={`Mandate limit ${pct(result.request.drawdown_limit, 0)}`}
            />
            <Stat
              label="Latest regime"
              value={result.regime.current}
              detail={
                result.regime.enabled
                  ? `${num(result.regime.multiplier)}× allocation multiplier`
                  : 'Allocation overlay disabled'
              }
            />
          </div>
          <Panel
            title="Research performance"
            detail={`Net of commission, slippage and assumed borrow. Evaluation starts ${result.data.evaluation_start}; ${result.data.warmup_observations} warmup sessions excluded. Chart includes training and test history.`}
          >
            <EquityChart result={result} />
            <div className="mt-3 flex flex-wrap gap-4 text-xs">
              <span className="text-blue-300">● Net portfolio</span>
              <span className="text-slate-400">● Benchmark</span>
              <span className="text-blue-300">● Gross portfolio</span>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3 2xl:grid-cols-4">
              <Stat
                label="Net research return"
                value={pct(result.metrics.total_return)}
              />
              <Stat
                label="Active return"
                value={pct(result.metrics.active_return)}
                detail="Versus selected benchmark"
              />
              <Stat
                label="Tracking error"
                value={pct(result.metrics.tracking_error)}
              />
              <Stat
                label="Annual traded notional"
                value={`${num(result.metrics.annual_turnover)}×`}
              />
            </div>
          </Panel>
          <Panel
            title="Alpha sleeve diagnostics"
            detail="Standalone returns before portfolio constraints. Budgets blend signals; sleeve returns do not sum to portfolio returns."
          >
            <DataTable
              rows={result.sleeves}
              columns={[
                { label: 'Strategy', value: (s) => s.name },
                { label: 'Budget', value: (s) => `${s.budget}%` },
                { label: 'Lookback', value: (s) => s.lookback },
                { label: 'Net return', value: (s) => pct(s.total_return) },
                { label: 'Sharpe', value: (s) => num(s.sharpe) },
                { label: 'Drawdown', value: (s) => pct(s.max_drawdown) },
              ]}
            />
          </Panel>
          <div className="grid gap-4 2xl:grid-cols-2">
            <Panel
              title="Performance by prior-day regime"
              detail="Descriptive attribution; regime labels precede the measured return."
            >
              <DataTable
                rows={result.regime.performance}
                columns={[
                  { label: 'Regime', value: (row) => regimeName(row.regime) },
                  { label: 'Return', value: (row) => pct(row.total_return) },
                  { label: 'Sharpe', value: (row) => num(row.sharpe) },
                ]}
              />
            </Panel>
            <Panel title="Research gates">
              <Gates result={result} />
            </Panel>
          </div>
          <Panel title="Research drawdown">
            <EquityChart result={result} drawdown />
          </Panel>
        </>
      )}
      {view === 'validation' && (
        <>
          <Panel
            title="Walk-forward evidence"
            detail={result.validation.method}
          >
            <p className="mb-4 text-sm text-muted-foreground">
              Signal and holding history carry across test boundaries. Rules are
              pre-specified; training does not optimize them. A final partial
              block enters OOS metrics but does not count as a complete window.
            </p>
            <DataTable
              rows={result.validation.windows}
              columns={[
                { label: 'Fold', value: (w) => w.window_id },
                { label: 'Training through', value: (w) => date(w.train_end) },
                {
                  label: 'Test period',
                  value: (w) => `${date(w.test_start)} → ${date(w.test_end)}`,
                },
                { label: 'Train Sharpe', value: (w) => num(w.train_sharpe) },
                { label: 'Test Sharpe', value: (w) => num(w.test_sharpe) },
                { label: 'Net return', value: (w) => pct(w.test_total_return) },
                { label: 'Drawdown', value: (w) => pct(w.test_max_drawdown) },
              ]}
            />
          </Panel>
          <div className="grid gap-4 2xl:grid-cols-2">
            <Panel
              title="Trading cost stress"
              detail="Full history. Rebalance and lag held constant; commission and slippage scaled together."
            >
              <DataTable
                rows={result.cost_stress}
                columns={[
                  { label: 'Cost', value: (row) => `${row.multiplier}×` },
                  {
                    label: 'Trade bps',
                    value: (row) => num(row.commission_bps + row.slippage_bps),
                  },
                  { label: 'Return', value: (row) => pct(row.total_return) },
                  {
                    label: 'Sharpe',
                    value: (row) => num(row.cost_adjusted_sharpe),
                  },
                ]}
              />
            </Panel>
            <Panel
              title="Lookback sensitivity"
              detail="All selected lookbacks perturbed together. Full-history diagnostic, not model selection."
            >
              <DataTable
                rows={result.robustness}
                columns={[
                  {
                    label: 'Lookback',
                    value: (row) => `${num(row.lookback_scale)}×`,
                  },
                  { label: 'Return', value: (row) => pct(row.total_return) },
                  { label: 'Sharpe', value: (row) => num(row.sharpe) },
                  { label: 'Drawdown', value: (row) => pct(row.max_drawdown) },
                ]}
              />
            </Panel>
          </div>
          <Panel
            title="Sleeve return correlation"
            detail="Net standalone return correlation over the research evaluation period."
          >
            <DataTable
              rows={result.correlations}
              columns={[
                {
                  label: 'Strategy',
                  value: (row) =>
                    result.sleeves.find((s) => s.strategy === row.strategy)
                      ?.name,
                },
                ...result.sleeves.map((s) => ({
                  label: s.name,
                  value: (row: Evidence['correlations'][number]) =>
                    num(
                      typeof row[s.strategy] === 'number'
                        ? (row[s.strategy] as number)
                        : null,
                    ),
                })),
              ]}
            />
          </Panel>
          <Panel title="Model review">
            <Gates result={result} />
          </Panel>
          <Panel
            title="Data diagnostics"
            detail={`${result.quality.flag_count} flagged observations. Details are retained in the evidence JSON.`}
          >
            {result.quality.flag_count === 0 ? (
              <p className="text-sm text-muted-foreground">
                No stale-price, outlier or adjustment flags in this snapshot.
                This does not establish point-in-time universe validity.
              </p>
            ) : (
              <pre className="max-h-80 overflow-auto whitespace-pre-wrap text-xs">
                {JSON.stringify(result.quality, null, 2)}
              </pre>
            )}
          </Panel>
        </>
      )}
      {view === 'portfolio' && (
        <>
          <div className="grid grid-cols-2 gap-3 2xl:grid-cols-4">
            <Stat
              label="Target gross / net"
              value={`${pct(result.risk.target_gross, 1)} / ${pct(result.risk.target_net, 1)}`}
            />
            <Stat
              label="Target volatility estimate"
              value={pct(result.risk.predicted_volatility)}
              detail="63-session sample covariance"
            />
            <Stat
              label="Benchmark beta"
              value={num(result.risk.benchmark_beta)}
              detail={`63-session beta ${num(result.risk.rolling_benchmark_beta)}`}
            />
            <Stat
              label="Daily expected shortfall"
              value={pct(result.metrics.expected_shortfall_95)}
              detail="Mean of worst 5% net return days"
            />
          </div>
          <Panel title="Rebalance review" detail={result.proposal.basis}>
            <div className="mb-4 flex flex-wrap gap-4 text-sm">
              <span>As of {result.proposal.as_of}</span>
              <span>Indicative turnover {pct(result.proposal.turnover)}</span>
              <span>
                Estimated trading cost {pct(result.proposal.estimated_cost)}
              </span>
            </div>
            <DataTable
              rows={result.holdings}
              columns={[
                { label: 'Asset', value: (h) => <strong>{h.symbol}</strong> },
                { label: 'Simulated', value: (h) => pct(h.current_weight) },
                { label: 'Target', value: (h) => pct(h.target_weight) },
                {
                  label: 'Change',
                  value: (h) => (
                    <span
                      className={
                        h.change >= 0 ? 'text-blue-300' : 'text-red-300'
                      }
                    >
                      {h.change > 0 ? '+' : ''}
                      {pct(h.change)}
                    </span>
                  ),
                },
                {
                  label: `Notional · ${result.data.currency}`,
                  value: (h) => num(h.indicative_notional, 0),
                },
                { label: 'Risk share', value: (h) => pct(h.risk_contribution) },
              ]}
            />
            <p className="mt-3 text-xs text-muted-foreground">
              Risk share is component variance contribution and can be negative
              for hedges. Targets are latest signals; scheduling, fresh quotes
              and actual positions must be reconciled separately.
            </p>
          </Panel>
          <Panel
            title="Signals behind the target"
            detail="Latest standalone target weights before blending, regime allocation and constraints."
          >
            <DataTable
              rows={result.holdings}
              columns={[
                { label: 'Asset', value: (h) => h.symbol },
                ...result.sleeves.map((s) => ({
                  label: s.name,
                  value: (h: Evidence['holdings'][number]) =>
                    pct(h.signals[s.strategy]),
                })),
              ]}
            />
          </Panel>
          <div className="grid gap-4 2xl:grid-cols-2">
            <Panel
              title="Return attribution"
              detail="Percentage-point contributions, linked through NAV over the evaluation period."
            >
              <DataTable
                rows={[
                  ...result.holdings.map((h) => ({
                    name: h.symbol,
                    contribution: h.return_contribution,
                  })),
                  {
                    name: 'Commission, slippage & borrow',
                    contribution: result.attribution.cost_contribution,
                  },
                  {
                    name: 'Net portfolio',
                    contribution: result.attribution.total_return,
                  },
                ]}
                columns={[
                  { label: 'Source', value: (row) => row.name },
                  {
                    label: 'Contribution',
                    value: (row) => `${num(row.contribution * 100)} pp`,
                  },
                ]}
              />
            </Panel>
            <div className="space-y-4">
              <Panel
                title="Frozen-target scenarios"
                detail="One-day shocks applied to latest targets, before trading costs."
              >
                {result.scenarios.map((s) => (
                  <div
                    key={s.scenario}
                    className="flex justify-between gap-3 border-b py-3 text-sm"
                  >
                    <div>
                      {s.scenario}
                      {s.date && (
                        <p className="text-xs text-muted-foreground">
                          {s.date}
                        </p>
                      )}
                    </div>
                    <span className="font-mono">{pct(s.return)}</span>
                  </div>
                ))}
              </Panel>
              <Panel title="Drift and exposure review">
                <p className="text-sm text-muted-foreground">
                  Between trades, holdings exceeded the gross limit on{' '}
                  {num(result.risk.gross_limit_days, 0)} days, net limit on{' '}
                  {num(result.risk.net_limit_days, 0)} days, and position cap on{' '}
                  {num(result.risk.asset_limit_days, 0)} days.
                </p>
                <p className="mt-3 text-sm">
                  Simulated gross / net: {pct(result.risk.current_gross)} /{' '}
                  {pct(result.risk.current_net)}
                </p>
                <p className="mt-3 text-sm">
                  Effective target positions:{' '}
                  {num(result.risk.effective_positions, 1)}
                </p>
              </Panel>
            </div>
          </div>
        </>
      )}
      <Panel
        title="PM research decision"
        detail="Record your assessment against this evidence. Paper candidate is a research label; it does not start trading."
      >
        {job.decision && (
          <p className="mb-4 text-sm">
            Latest: <strong>{job.decision.status.replaceAll('_', ' ')}</strong>{' '}
            · {new Date(job.decision.recorded_at).toLocaleString()}
          </p>
        )}
        <div className="grid items-end gap-3 2xl:grid-cols-[180px_minmax(0,1fr)_auto]">
          <Field label="Disposition">
            <NativeSelect
              className="w-full"
              value={status}
              onChange={(e) => setStatus(e.target.value as Decision['status'])}
            >
              <NativeSelectOption value="watchlist">
                Watchlist
              </NativeSelectOption>
              <NativeSelectOption
                value="paper_candidate"
                disabled={!result.paper_candidate_eligible}
              >
                Paper candidate
              </NativeSelectOption>
              <NativeSelectOption value="rejected">
                Reject hypothesis
              </NativeSelectOption>
            </NativeSelect>
          </Field>
          <Field label="Rationale · include unresolved review items">
            <textarea
              className="research-textarea"
              rows={2}
              maxLength={3000}
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
            />
          </Field>
          <Button
            onClick={() => void saveDecision().catch(() => {})}
            disabled={
              saving ||
              rationale.trim().length < 10 ||
              (status === 'paper_candidate' && !result.paper_candidate_eligible)
            }
          >
            {saving ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <ShieldCheck className="size-4" />
            )}
            Record decision
          </Button>
        </div>
        {!result.paper_candidate_eligible && (
          <p className="mt-3 text-xs text-amber-200">
            Research gates block paper candidacy. Watchlist and rejection remain
            available.
          </p>
        )}
        {!!job.decisions.length && (
          <details className="mt-4 text-sm">
            <summary className="cursor-pointer text-muted-foreground">
              Decision history ({job.decisions.length})
            </summary>
            {job.decisions.map((d, i) => (
              <p className="mt-3 rounded-md border p-3" key={i}>
                <strong>{d.status.replaceAll('_', ' ')}</strong> ·{' '}
                {new Date(d.recorded_at).toLocaleString()}
                <br />
                {d.rationale}
              </p>
            ))}
          </details>
        )}
      </Panel>
      <Panel title="Evidence & reproducibility">
        <div className="flex flex-wrap gap-2">
          {[
            ['memo', 'PM memo'],
            ['result', 'Evidence JSON'],
            ['prices', 'OHLCV snapshot'],
            ['benchmark', 'Benchmark'],
            ['targets', 'Target weights'],
            ['holdings', 'Simulated holdings'],
            ['returns', 'Equity curves'],
            ['source', 'Research source'],
          ].map(([name, label]) => (
            <Artifact key={name} runId={job.run_id} name={name} label={label} />
          ))}
        </div>
        <p className="mt-4 break-all font-mono text-xs text-muted-foreground">
          Data SHA-256 {result.data.snapshot_sha256}
          <br />
          Code SHA-256 {result.provenance.source_sha256}
          <br />
          Git {result.provenance.git_revision}
          {result.provenance.working_tree_dirty
            ? ' · working tree modified'
            : ''}
        </p>
        <details className="mt-4">
          <summary className="cursor-pointer text-sm">
            Frozen mandate and research limitations
          </summary>
          <pre className="my-3 max-h-80 overflow-auto rounded-md bg-background p-3 text-xs">
            {JSON.stringify(result.request, null, 2)}
          </pre>
          <ul className="list-disc space-y-2 pl-5 text-sm leading-6 text-muted-foreground">
            {result.limitations.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </details>
      </Panel>
    </>
  );
}
