'use client';

import { useState } from 'react';
import { Loader2, Play, Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  NativeSelect,
  NativeSelectOption,
} from '@/components/ui/native-select';
import { Field, Panel } from '@/components/flagship/research-primitives';
import { num, type Catalog, type ResearchRequest } from '@/lib/flagship/research';

export function Mandate({
  draft,
  change,
  catalog,
  submitting,
  connected,
  launch,
}: {
  draft: ResearchRequest;
  change: (draft: ResearchRequest) => void;
  catalog: Catalog | null;
  submitting: boolean;
  connected: boolean;
  launch: () => void;
}) {
  const [symbolsText, setSymbolsText] = useState(draft.symbols.join(', '));
  function patch<K extends keyof ResearchRequest>(
    key: K,
    value: ResearchRequest[K],
  ) {
    change({
      ...draft,
      [key]: value,
      ...(key==='data_mode'&&value==='massive'?{period:'2y' as const}:{}),
      snapshot_run_id: ['data_mode', 'symbols', 'benchmark', 'period'].includes(
        key,
      )
        ? null
        : key === 'snapshot_run_id'
          ? (value as string | null)
          : draft.snapshot_run_id,
    });
  }
  const numeric = (
    key: keyof ResearchRequest,
    label: string,
    scale = 1,
    step = 1,
  ) => (
    <Field label={label}>
      <Input
        type="number"
        step={step}
        value={
          Number.isFinite(Number(draft[key])) ? Number(draft[key]) * scale : ''
        }
        onChange={(event) =>
          patch(
            key,
            event.target.value === ''
              ? NaN
              : Number(event.target.value) / scale,
          )
        }
      />
    </Field>
  );
  const totalBudget = draft.sleeves.reduce(
    (sum, sleeve) => sum + sleeve.budget,
    0,
  );
  return (
    <aside className="min-w-0 space-y-4 xl:sticky xl:top-4 xl:max-h-[calc(100vh-2rem)] xl:overflow-y-auto xl:pr-2">
      <Panel
        title="01 / Investment mandate"
        detail="Each run freezes its configuration with the evidence."
      >
        <div className="space-y-4">
          {draft.snapshot_run_id && (
            <div className="rounded-md border border-blue-300/30 p-3 text-sm">
              <p>
                Reusing the archived data from {draft.snapshot_run_id.slice(-8)}{' '}
                for a controlled variant.
              </p>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => patch('snapshot_run_id', null)}
              >
                Fetch new data instead
              </Button>
            </div>
          )}
          <Field label="Study name">
            <Input
              value={draft.name}
              maxLength={80}
              onChange={(e) => patch('name', e.target.value)}
            />
          </Field>
          <Field label="Investment hypothesis">
            <textarea
              className="research-textarea"
              rows={3}
              value={draft.hypothesis}
              maxLength={2000}
              onChange={(e) => patch('hypothesis', e.target.value)}
            />
          </Field>
          <Field label="Data source">
            <NativeSelect
              className="w-full"
              value={draft.data_mode}
              onChange={(e) =>
                patch(
                  'data_mode',
                  e.target.value as ResearchRequest['data_mode'],
                )
              }
            >
              <NativeSelectOption value="yahoo">
                Yahoo · market observations
              </NativeSelectOption>
              <NativeSelectOption value="massive">Massive · US daily · up to 2 years</NativeSelectOption>
              <NativeSelectOption value="synthetic">Synthetic · selected symbols · seed 42</NativeSelectOption>
              <NativeSelectOption value="demo">
                Legacy synthetic fixture · workflow demonstration
              </NativeSelectOption>
            </NativeSelect>
          </Field>
          {draft.data_mode === 'synthetic' && <p className="text-amber-200 text-xs">SYNTHETIC · artificial prices for selected symbols, seed 42, fixed end 2025-12-31. Weekday labels only; not market evidence.</p>}
          {draft.data_mode === 'demo' && (
            <p className="rounded-md border border-amber-300/25 bg-amber-300/5 p-3 text-sm text-amber-100">
              Fixed 8-stock synthetic fixture, 2018–2021, with a synthetic
              benchmark. Market inputs below apply to provider and selected-symbol synthetic runs.
            </p>
          )}
          <fieldset
            disabled={draft.data_mode === 'demo'}
            className="space-y-4 disabled:opacity-40"
          >
            <Field label="Universe · comma-separated tickers">
              <textarea
                className="research-textarea font-mono"
                rows={2}
                value={symbolsText}
                onChange={(e) => {
                  setSymbolsText(e.target.value);
                  patch(
                    'symbols',
                    e.target.value.split(/[\s,;]+/).filter(Boolean),
                  );
                }}
              />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Benchmark">
                <Input
                  value={draft.benchmark}
                  onChange={(e) => patch('benchmark', e.target.value)}
                />
              </Field>
              <Field label="History">
                <NativeSelect
                  className="w-full"
                  value={draft.period}
                  onChange={(e) =>
                    patch('period', e.target.value as ResearchRequest['period'])
                  }
                >
                  {(draft.data_mode==='massive'?['2y']:['2y', '5y', '10y']).map((period) => (
                    <NativeSelectOption key={period} value={period}>
                      {period.replace('y', ' years')}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
              </Field>
            </div>
            <p className="text-xs leading-5 text-muted-foreground">
              One currency. Use .NS tickers with ^NSEI for India. Shared
              sessions must align.
            </p>
          </fieldset>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Mandate">
              <NativeSelect
                className="w-full"
                value={draft.long_only ? 'long' : 'ls'}
                onChange={(e) => patch('long_only', e.target.value === 'long')}
              >
                <NativeSelectOption value="long">Long-only</NativeSelectOption>
                <NativeSelectOption value="ls">Long / short</NativeSelectOption>
              </NativeSelect>
            </Field>
            {numeric('initial_capital', 'Initial capital')}
          </div>
        </div>
      </Panel>
      <Panel
        title="02 / Alpha sleeves"
        detail="Budgets blend signals before netting and risk sizing."
      >
        <div className="space-y-4">
          {draft.sleeves.map((sleeve, index) => (
            <div className="space-y-2 rounded-lg border p-3" key={index}>
              <div className="flex items-center gap-2">
                <NativeSelect
                  className="min-w-0 flex-1"
                  aria-label={`Strategy sleeve ${index + 1}`}
                  value={sleeve.strategy}
                  onChange={(e) => {
                    const option = catalog?.strategies.find(
                      (s) => s.id === e.target.value,
                    );
                    patch(
                      'sleeves',
                      draft.sleeves.map((row, i) =>
                        i === index
                          ? {
                              ...row,
                              strategy: e.target.value,
                              lookback: option?.lookback ?? row.lookback,
                            }
                          : row,
                      ),
                    );
                  }}
                >
                  {catalog ? (
                    catalog.strategies.map((s) => (
                      <NativeSelectOption
                        key={s.id}
                        value={s.id}
                        disabled={draft.sleeves.some(
                          (other, i) => i !== index && other.strategy === s.id,
                        )}
                      >
                        {s.name}
                      </NativeSelectOption>
                    ))
                  ) : (
                    <NativeSelectOption value={sleeve.strategy}>
                      {sleeve.strategy.replaceAll('_', ' ')}
                    </NativeSelectOption>
                  )}
                </NativeSelect>
                <Button
                  aria-label={`Remove sleeve ${index + 1}`}
                  size="icon"
                  variant="ghost"
                  disabled={draft.sleeves.length === 1}
                  onClick={() =>
                    patch(
                      'sleeves',
                      draft.sleeves.filter((_, i) => i !== index),
                    )
                  }
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Budget %">
                  <Input
                    type="number"
                    min={1}
                    max={100}
                    value={Number.isFinite(sleeve.budget) ? sleeve.budget : ''}
                    onChange={(e) =>
                      patch(
                        'sleeves',
                        draft.sleeves.map((s, i) =>
                          i === index
                            ? {
                                ...s,
                                budget:
                                  e.target.value === ''
                                    ? NaN
                                    : Number(e.target.value),
                              }
                            : s,
                        ),
                      )
                    }
                  />
                </Field>
                <Field label="Lookback · sessions">
                  <Input
                    type="number"
                    min={5}
                    max={252}
                    value={
                      Number.isFinite(sleeve.lookback) ? sleeve.lookback : ''
                    }
                    onChange={(e) =>
                      patch(
                        'sleeves',
                        draft.sleeves.map((s, i) =>
                          i === index
                            ? {
                                ...s,
                                lookback:
                                  e.target.value === ''
                                    ? NaN
                                    : Number(e.target.value),
                              }
                            : s,
                        ),
                      )
                    }
                  />
                </Field>
              </div>
              <p className="text-xs leading-5 text-muted-foreground">
                {
                  catalog?.strategies.find((s) => s.id === sleeve.strategy)
                    ?.description
                }
              </p>
            </div>
          ))}
          <div className="flex items-center justify-between">
            <span
              className={`font-mono text-sm ${Math.abs(totalBudget - 100) < 1e-6 ? 'text-blue-300' : 'text-amber-200'}`}
            >
              {num(totalBudget)} / 100%
            </span>
            <Button
              size="sm"
              variant="outline"
              disabled={
                !catalog || draft.sleeves.length === catalog.strategies.length
              }
              onClick={() => {
                const next = catalog?.strategies.find(
                  (s) => !draft.sleeves.some((row) => row.strategy === s.id),
                );
                if (next)
                  patch('sleeves', [
                    ...draft.sleeves,
                    { strategy: next.id, budget: 10, lookback: next.lookback },
                  ]);
              }}
            >
              <Plus className="size-4" />
              Add sleeve
            </Button>
          </div>
          <details className="text-sm">
            <summary className="cursor-pointer text-muted-foreground">
              Strategies requiring additional inputs
            </summary>
            <div className="mt-3 space-y-3">
              {catalog?.unavailable.map((s) => (
                <p key={s.name}>
                  <strong>{s.name}</strong>
                  <br />
                  <span className="text-muted-foreground">{s.reason}</span>
                </p>
              ))}
            </div>
          </details>
        </div>
      </Panel>
      <Panel title="03 / Risk & implementation">
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            {numeric('volatility_target', 'Volatility target %', 100)}
            {numeric('max_asset_weight', 'Position cap %', 100)}
            {numeric('max_gross_exposure', 'Gross limit %', 100, 5)}
            {numeric('max_net_exposure', 'Absolute net limit %', 100, 5)}
            {numeric('drawdown_limit', 'OOS drawdown limit %', 100)}
            <Field label="Rebalance">
              <NativeSelect
                className="w-full"
                value={draft.rebalance}
                onChange={(e) =>
                  patch(
                    'rebalance',
                    e.target.value as ResearchRequest['rebalance'],
                  )
                }
              >
                {['daily', 'weekly', 'monthly'].map((s) => (
                  <NativeSelectOption key={s} value={s}>
                    {s}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </Field>
            {numeric('commission_bps', 'Commission · bps', 1, 0.5)}
            {numeric('slippage_bps', 'Slippage · bps', 1, 0.5)}
          </div>
          {!draft.long_only &&
            numeric('annual_borrow_bps', 'Annual short borrow · bps')}
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-4 accent-blue-400"
              checked={draft.regime_enabled}
              onChange={(e) => patch('regime_enabled', e.target.checked)}
            />
            Apply regime allocation
          </label>
          {draft.regime_enabled && (
            <div className="grid grid-cols-2 gap-3">
              {numeric('defensive_multiplier', 'Defensive multiplier', 1, 0.1)}
              {numeric(
                'constructive_multiplier',
                'Constructive multiplier',
                1,
                0.1,
              )}
            </div>
          )}
          <p className="text-xs leading-5 text-muted-foreground">
            Hard caps apply after volatility targeting. Holdings drift between
            trades. Daily signals execute with one-session lag.
          </p>
        </div>
      </Panel>
      <Panel title="04 / Validation protocol">
        <div className="grid grid-cols-2 gap-3">
          {numeric('train_window', 'Initial history · sessions')}
          {numeric('test_window', 'Test block · sessions')}
          {numeric('min_oos_sharpe', 'Minimum OOS Sharpe', 1, 0.1)}
        </div>
        <p className="mt-3 text-xs leading-5 text-muted-foreground">
          Expanding history, frozen rules, 1×/2×/3× trading costs and ±20%
          lookback sensitivity. Paper candidates need three complete test
          blocks.
        </p>
      </Panel>
      <div className="sticky bottom-3 z-10 rounded-xl border border-blue-300/30 bg-background p-3 shadow-xl">
        <Button
          className="w-full"
          size="lg"
          disabled={submitting || !connected}
          onClick={launch}
        >
          {submitting ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Play className="size-4" />
          )}
          {submitting ? 'Queuing research…' : 'Run research experiment'}
        </Button>
        <p className="mt-2 text-center text-xs text-muted-foreground">
          Saves a new run and its evidence.
        </p>
      </div>
    </aside>
  );
}
