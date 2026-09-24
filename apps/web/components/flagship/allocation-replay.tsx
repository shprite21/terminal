'use client';


import {
  Activity,
  ArrowUpRight,
  BarChart3,
  Download,
  Loader2,
  Plus,
  Save,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { flushSync } from 'react-dom';
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  ComposedChart,
  XAxis,
  YAxis,
} from 'recharts';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart';
import { Input } from '@/components/ui/input';
import {
  NativeSelect,
  NativeSelectOption,
} from '@/components/ui/native-select';
import { Progress } from '@/components/ui/progress';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  equalWeights,
  equityCsv,
  parsePortfolio,
  loadSaved,
  readSaved,
  mergeSaved,
  starter,
  storageKey,
  tickerPattern,
  type Analysis,
  type PortfolioDraft,
} from '@/lib/flagship/portfolio';
import { usePortfolioTools } from '@/lib/flagship/use-portfolio-tools';

const percent = (value: number | null | undefined) =>
  value == null ? '—' : (value * 100).toFixed(2) + '%';
const number = (value: number | null | undefined, digits = 2) =>
  value == null
    ? '—'
    : value.toLocaleString(undefined, {
        maximumFractionDigits: digits,
        minimumFractionDigits: digits,
      });
const chartConfig = {
  portfolio: { label: 'Portfolio', color: '#2563eb' },
  benchmark: { label: 'Benchmark', color: '#93a8b2' },
  drawdown: { label: 'Drawdown', color: '#f87171' },
};

export default function AllocationReplay({onOpenResearch}:{onOpenResearch:()=>void}) {
  const [draft, setDraft] = useState<PortfolioDraft>(starter);
  const [saved, setSaved] = useState<PortfolioDraft[]>([]);
  const [importPreview,setImportPreview] = useState<PortfolioDraft[]|null>(null);
  const [selected, setSelected] = useState('');
  const [storageReady, setStorageReady] = useState(false);
  const [ticker, setTicker] = useState('');
  const [weight, setWeight] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Analysis | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const totalWeight = draft.holdings.reduce(
    (sum, item) => sum + item.weight,
    0,
  );
  let validation = '';
  try {
    parsePortfolio(draft);
  } catch (failure) {
    validation = (failure as Error).message;
  }

  // Hydrate device-local storage after SSR; one deliberate client-only state update.
  /* oxlint-disable react/react-compiler */
  useEffect(() => {
    try {
      setSaved(loadSaved(localStorage));
      setStorageReady(true);
    } catch {
      setError(
        'Saved portfolios could not be read. Browser storage may be blocked or damaged; existing data has not been overwritten. You can still analyze.',
      );
    }
    return () => requestRef.current?.abort();
  }, []);
  /* oxlint-enable react/react-compiler */

  function configure(next: PortfolioDraft) {
    if (requestRef.current)
      throw new Error('Wait for the current analysis to finish.');
    setDraft(next);
    setResult(null);
    setError('');
    setMessage('');
  }

  function addHolding() {
    const symbol = ticker.trim().toUpperCase();
    const allocation = Number(weight);
    if (!tickerPattern.test(symbol)) {
      setError('Use a supported ticker, such as AAPL or RELIANCE.NS.');
      return;
    }
    if (!Number.isFinite(allocation) || allocation <= 0 || allocation > 100) {
      setError('Enter a weight greater than 0 and no more than 100%.');
      return;
    }
    if (draft.holdings.length >= 30) {
      setError('This workspace supports up to 30 holdings.');
      return;
    }
    if (draft.holdings.some((item) => item.ticker === symbol)) {
      setError(symbol + ' is already included. Edit its weight below.');
      return;
    }
    configure({
      ...draft,
      holdings: [...draft.holdings, { ticker: symbol, weight: allocation }],
    });
    setTicker('');
    setWeight('');
  }

  function savePortfolio() {
    try {
      const portfolio = parsePortfolio(draft);
      if (!storageReady)
        throw new Error(
          'Browser storage is unavailable. Your portfolio has not been saved.',
        );
      if (
        saved.length >= 50 &&
        !saved.some((item) => item.name === portfolio.name)
      )
        throw new Error('Maximum 50 saved portfolios. Remove one first.');
      const next = [
        ...saved.filter((item) => item.name !== portfolio.name),
        portfolio,
      ];
      localStorage.setItem(storageKey, JSON.stringify(next));
      setSaved(next);
      setSelected(portfolio.name);
      setError('');
      setMessage(
        'Saved on this device. A matching portfolio name updates that saved snapshot.',
      );
    } catch (failure) {
      setError((failure as Error).message);
    }
  }

  function deleteSaved() {
    if (
      !selected ||
      !window.confirm(
        'Delete saved portfolio "' +
          selected +
          '" from this device? Your current draft will remain.',
      )
    )
      return;
    try {
      const next = saved.filter((item) => item.name !== selected);
      localStorage.setItem(storageKey, JSON.stringify(next));
      setSaved(next);
      setSelected('');
      setMessage('Saved snapshot removed. The current draft is unchanged.');
      setError('');
    } catch {
      setError('Could not update browser storage. Nothing was removed.');
    }
  }

  function exportPortfolios() {
    const url=URL.createObjectURL(new Blob([JSON.stringify(saved,null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='q-saved-portfolios.json';link.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }

  function importPortfolios() {
    try {
      if(!storageReady||!importPreview)throw new Error('Review a portfolio file first.');
      // Re-read storage before applying; never replace a same-name saved snapshot.
      const next=mergeSaved(loadSaved(localStorage),importPreview);
      localStorage.setItem(storageKey,JSON.stringify(next));
      setSaved(next);setImportPreview(null);setError('');setMessage('Portfolios imported. Existing snapshots retained; conflicting names receive an import suffix.');
    } catch(cause){setError((cause as Error).message);}
  }

  async function analyze() {
    if (requestRef.current) throw new Error('An analysis is already running.');
    const portfolio = parsePortfolio(draft);
    const { name: _name, ...payload } = portfolio;
    const controller = new AbortController();
    requestRef.current = controller;
    setBusy(true);
    setError('');
    setMessage('');
    setResult(null);
    const timeout = setTimeout(() => controller.abort(), portfolio.source==='massive'?30*60*1000:120000);
    try {
      const response = await fetch(
        '/integrations/engine/api/portfolio/analyze',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
          signal: controller.signal,
        },
      );
      const data = (await response.json()) as Analysis & { detail?: unknown };
      if (!response.ok)
        throw new Error(
          typeof data.detail === 'string'
            ? data.detail
            : 'The portfolio request was rejected. Check tickers and weights.',
        );
      if (!data.equity_curve?.length || !data.holdings?.length || !data.metrics)
        throw new Error('The API returned an incomplete result.');
      flushSync(() => setResult(data as Analysis));
      return {
        status: 'analyzed',
        start_date: data.start_date,
        end_date: data.end_date,
        currency: data.currency,
        metrics: data.metrics,
      };
    } catch (failure) {
      const original = failure as Error;
      const text = controller.signal.aborted
        ? 'Analysis timed out or was cancelled. Retry with fewer tickers or a shorter history.'
        : original instanceof TypeError
          ? 'Cannot reach the research API. Start the Python server on 127.0.0.1:8000, then retry.'
          : original.message;
      setError(text);
      throw new Error(text);
    } finally {
      clearTimeout(timeout);
      requestRef.current = null;
      flushSync(() => setBusy(false));
    }
  }

  usePortfolioTools({
    configure,
    analyze,
    read: () => ({
      portfolio: draft,
      busy,
      result: result
        ? {
            start_date: result.start_date,
            end_date: result.end_date,
            metrics: result.metrics,
          }
        : null,
    }),
  });

  function downloadCsv() {
    if (!result) return;
    const url = URL.createObjectURL(
      new Blob([equityCsv(result)], { type: 'text/csv;charset=utf-8' }),
    );
    const link = document.createElement('a');
    link.href = url;
    link.download = 'shprite-equity-curve-' + result.end_date + '.csv';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  const metricCards = [
    {
      label: 'Total return',
      value: percent(result?.metrics.total_return),
      note: result
        ? 'Benchmark ' + percent(result.metrics.benchmark_return)
        : 'Portfolio growth',
    },
    {
      label: 'Annual volatility',
      value: percent(result?.metrics.annualized_volatility),
      note: '252-observation estimate',
    },
    {
      label: 'Sharpe ratio',
      value: number(result?.metrics.sharpe),
      note: 'Risk-free rate ' + draft.risk_free_rate + '%',
    },
    {
      label: 'Max drawdown',
      value: percent(result?.metrics.max_drawdown),
      note: 'Peak-to-trough loss',
    },
  ];

  return (
    <div className="min-h-0">
      <h2 className="text-xl font-semibold">Allocation replay</h2>

      <div className="mx-auto max-w-full py-2">
        <div className="mb-5 flex justify-end">
          <Button
            size="lg"
            disabled={!!validation || busy}
            className="h-10 px-4"
            onClick={() =>
              void analyze().catch((failure) => setError(failure.message))
            }
          >
            {busy ? (
              <>
                <Loader2 className="animate-spin" />
                Loading selected history…
              </>
            ) : (
              <>
                Analyze portfolio
                <ArrowUpRight />
              </>
            )}
          </Button>
        </div>

        <div className="grid items-start gap-5 xl:grid-cols-[minmax(340px,0.85fr)_minmax(0,1.65fr)]">
          <fieldset
            disabled={busy}
            className="min-w-0 space-y-5 disabled:opacity-65"
          >
            <legend className="sr-only">Portfolio construction</legend>
            <Card className="py-0">
              <CardHeader className="border-b border-white/8 py-4">
                <CardTitle className="flex items-center gap-2">
                  <Activity className="size-4 text-neutral-300" />
                  Target portfolio
                </CardTitle>
                <CardDescription>
                  Long-only equities / ETFs. Up to 30 holdings.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4 pb-4">
                <details><summary>Transfer saved portfolios</summary><p className="my-2 text-sm">Import the JSON exported from the former portfolio dashboard. Review names before adding them; matching names never overwrite existing portfolios.</p><Button variant="outline" disabled={!storageReady} onClick={exportPortfolios}>Export saved portfolios</Button><label className="block my-2">Portfolio JSON<Input type="file" accept=".json" onChange={async event=>{const file=event.target.files?.[0];setImportPreview(null);if(!file)return;try{if(file.size>500000)throw new Error('Portfolio file exceeds 500 KB.');setImportPreview(readSaved(await file.text()));setError('');}catch(cause){setError((cause as Error).message);}event.target.value='';}}/></label>{importPreview&&<><p>{importPreview.length} portfolios: {importPreview.map(p=>p.name).join(', ')}</p><Button disabled={!storageReady||!importPreview.length} onClick={importPortfolios}>Add reviewed portfolios</Button><Button variant="ghost" onClick={()=>setImportPreview(null)}>Cancel import</Button></>}</details>
                <div>
                  <label
                    htmlFor="saved-portfolio"
                    className="mb-1.5 block text-xs text-muted-foreground"
                  >
                    Saved portfolios · this device only
                  </label>
                  <div className="flex gap-2">
                    <NativeSelect
                      id="saved-portfolio"
                      className="flex-1"
                      value={selected}
                      onChange={(event) => {
                        const name = event.target.value;
                        setSelected(name);
                        const portfolio = saved.find(
                          (item) => item.name === name,
                        );
                        if (portfolio) configure(structuredClone(portfolio));
                      }}
                    >
                      <NativeSelectOption value="">
                        Select a saved portfolio
                      </NativeSelectOption>
                      {saved.map((item) => (
                        <NativeSelectOption key={item.name} value={item.name}>
                          {item.name}
                        </NativeSelectOption>
                      ))}
                    </NativeSelect>
                    <Button
                      variant="ghost"
                      size="icon"
                      disabled={!selected}
                      aria-label="Delete saved portfolio"
                      onClick={deleteSaved}
                    >
                      <Trash2 />
                    </Button>
                  </div>
                </div>
                <div className="flex gap-2">
                  <Input
                    aria-label="Portfolio name"
                    maxLength={60}
                    value={draft.name}
                    onChange={(event) =>
                      configure({ ...draft, name: event.target.value })
                    }
                  />
                  <Button
                    variant="secondary"
                    disabled={!storageReady || !!validation}
                    onClick={savePortfolio}
                  >
                    <Save />
                    Save / update
                  </Button>
                </div>
                <p className="text-[11px] leading-5 text-muted-foreground">
                  Saving updates the snapshot with this name. Use a new name to
                  keep another version. Example holdings are illustrative, not
                  recommendations.
                </p>
                <form
                  className="grid grid-cols-[minmax(0,1fr)_100px_auto] gap-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    addHolding();
                  }}
                >
                  <Input
                    aria-label="Ticker symbol"
                    value={ticker}
                    maxLength={20}
                    onChange={(event) => setTicker(event.target.value)}
                    placeholder="Ticker, e.g. COST"
                    className="h-10 bg-black/15 font-mono uppercase"
                  />
                  <Input
                    aria-label="New holding weight percent"
                    value={weight}
                    onChange={(event) => setWeight(event.target.value)}
                    type="number"
                    min="0.01"
                    max="100"
                    step="any"
                    placeholder="Weight %"
                    className="h-10 bg-black/15 text-right font-mono"
                  />
                  <Button
                    type="submit"
                    aria-label="Add holding"
                    size="icon-lg"
                    variant="secondary"
                    className="size-10"
                  >
                    <Plus />
                  </Button>
                </form>
                <div className="overflow-hidden rounded-lg border border-white/8">
                  <Table>
                    <TableHeader className="bg-white/[0.025]">
                      <TableRow>
                        <TableHead>Equity ticker</TableHead>
                        <TableHead className="text-right">Target</TableHead>
                        <TableHead className="w-10">
                          <span className="sr-only">Actions</span>
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {draft.holdings.map((holding) => (
                        <TableRow key={holding.ticker}>
                          <TableCell className="font-mono font-semibold tracking-wide">
                            {holding.ticker}
                          </TableCell>
                          <TableCell>
                            <div className="ml-auto flex w-[110px] items-center gap-1.5">
                              <Input
                                aria-label={holding.ticker + ' weight percent'}
                                type="number"
                                min="0"
                                max="100"
                                step="any"
                                value={holding.weight}
                                className="text-right font-mono"
                                onChange={(event) =>
                                  configure({
                                    ...draft,
                                    holdings: draft.holdings.map((item) =>
                                      item.ticker === holding.ticker
                                        ? {
                                            ...item,
                                            weight: Number(event.target.value),
                                          }
                                        : item,
                                    ),
                                  })
                                }
                              />
                              <span className="text-xs text-muted-foreground">
                                %
                              </span>
                            </div>
                          </TableCell>
                          <TableCell>
                            <Button
                              aria-label={'Remove ' + holding.ticker}
                              size="icon-sm"
                              variant="ghost"
                              className="text-muted-foreground hover:text-red-300"
                              onClick={() =>
                                configure({
                                  ...draft,
                                  holdings: draft.holdings.filter(
                                    (item) => item.ticker !== holding.ticker,
                                  ),
                                })
                              }
                            >
                              <Trash2 />
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  {draft.holdings.length === 0 && (
                    <p className="p-6 text-center text-sm text-muted-foreground">
                      Add your first equity to begin.
                    </p>
                  )}
                </div>
                <div className="rounded-lg border border-white/8 bg-black/15 p-3">
                  <div className="mb-2 flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">
                      Capital allocated
                    </span>
                    <span
                      className={
                        'font-mono ' +
                        (Math.abs(totalWeight - 100) < 0.000001
                          ? 'text-neutral-300'
                          : 'text-amber-300')
                      }
                    >
                      {number(totalWeight)} / 100%
                    </span>
                  </div>
                  <Progress value={Math.max(0, Math.min(totalWeight, 100))} />
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <p className="text-[11px] text-muted-foreground">
                      {validation || 'Fully allocated. Ready for analysis.'}
                    </p>
                    <Button
                      variant="ghost"
                      size="xs"
                      disabled={!draft.holdings.length}
                      onClick={() =>
                        configure({
                          ...draft,
                          holdings: equalWeights(draft.holdings),
                        })
                      }
                    >
                      Equal weight
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Research settings</CardTitle>
                <CardDescription>
                  Buy and hold · no rebalancing or transaction costs.
                </CardDescription>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-4">
                <label className="col-span-2 space-y-1.5 text-xs text-muted-foreground">Data source<NativeSelect aria-label="Allocation replay data source" value={draft.source??'yahoo'} onChange={e=>configure({...draft,source:e.target.value as PortfolioDraft['source'],...(e.target.value==='massive'&&draft.period==='5y'?{period:'2y' as const}:{})})}><NativeSelectOption value="yahoo">Yahoo Finance</NativeSelectOption><NativeSelectOption value="massive">Massive · US daily · up to 2 years</NativeSelectOption><NativeSelectOption value="synthetic">Synthetic · seed 42 · fixed end 2025-12-31</NativeSelectOption></NativeSelect></label>
                {draft.source==='synthetic'&&<p className="col-span-2 text-amber-200 text-xs">SYNTHETIC · artificial per-symbol prices for model mechanics. No observed market performance.</p>}
                <label
                  htmlFor="history-window"
                  className="space-y-1.5 text-xs text-muted-foreground"
                >
                  <span>History window</span>
                  <NativeSelect
                    id="history-window"
                    className="w-full"
                    value={draft.period}
                    onChange={(event) =>
                      configure({
                        ...draft,
                        period: event.target.value as PortfolioDraft['period'],
                      })
                    }
                  >
                    {(draft.source==='massive'?(['6mo','1y','2y'] as const):(['6mo', '1y', '2y', '5y'] as const)).map((period) => (
                      <NativeSelectOption key={period} value={period}>
                        {period}
                      </NativeSelectOption>
                    ))}
                  </NativeSelect>
                </label>
                <label
                  htmlFor="benchmark"
                  className="space-y-1.5 text-xs text-muted-foreground"
                >
                  <span>Benchmark ticker</span>
                  <Input
                    id="benchmark"
                    value={draft.benchmark}
                    maxLength={20}
                    className="font-mono uppercase"
                    onChange={(event) =>
                      configure({
                        ...draft,
                        benchmark: event.target.value.toUpperCase(),
                      })
                    }
                  />
                </label>
                <label
                  htmlFor="initial-capital"
                  className="space-y-1.5 text-xs text-muted-foreground"
                >
                  <span>Initial capital</span>
                  <Input
                    id="initial-capital"
                    type="number"
                    min="1"
                    max="1000000000"
                    step="any"
                    value={draft.initial_capital}
                    onChange={(event) =>
                      configure({
                        ...draft,
                        initial_capital: Number(event.target.value),
                      })
                    }
                  />
                </label>
                <label
                  htmlFor="risk-free-rate"
                  className="space-y-1.5 text-xs text-muted-foreground"
                >
                  <span>Risk-free rate (% / year)</span>
                  <Input
                    id="risk-free-rate"
                    type="number"
                    min="0"
                    max="25"
                    step="any"
                    value={draft.risk_free_rate}
                    onChange={(event) =>
                      configure({
                        ...draft,
                        risk_free_rate: Number(event.target.value),
                      })
                    }
                  />
                </label>
                <p className="col-span-2 text-[11px] leading-5 text-muted-foreground">
                  Capital uses the holdings’ quote currency. Keep all holdings
                  and the benchmark in one currency: SPY for USD, ^NSEI for INR.
                  No FX conversion.
                </p>
              </CardContent>
            </Card>
          </fieldset>

          <div className="min-w-0 space-y-5" aria-busy={busy}>
            {error && (
              <p
                role="alert"
                className="rounded-lg border border-red-400/25 bg-red-400/5 p-4 text-sm leading-6 text-red-200"
              >
                {error}
              </p>
            )}
            {message && (
              <output className="block rounded-lg border border-neutral-700 bg-black p-3 text-xs leading-5 text-neutral-300">
                {message}
              </output>
            )}
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {metricCards.map((item) => (
                <Card key={item.label}>
                  <CardContent>
                    <p className="text-xs text-muted-foreground">
                      {item.label}
                    </p>
                    <p
                      className={
                        'my-3 font-mono text-2xl ' +
                        (result ? 'text-foreground' : 'text-slate-500')
                      }
                    >
                      {item.value}
                    </p>
                    <p className="text-[10px] tracking-wide text-muted-foreground">
                      {item.note}
                    </p>
                  </CardContent>
                </Card>
              ))}
            </div>
            <Card className="min-h-[350px]">
              <CardHeader className="border-b border-white/8">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <CardTitle>Portfolio performance</CardTitle>
                    <CardDescription className="mt-1">
                      {result
                        ? result.start_date +
                          ' → ' +
                          result.end_date +
                          ' · ' +
                          result.observations +
                          ' daily prices · ' +
                          result.currency
                        : 'Growth of initial capital, compared with your benchmark.'}
                    </CardDescription>
                  </div>
                  {result && (
                    <Button variant="ghost" size="sm" onClick={downloadCsv}>
                      <Download />
                      CSV
                    </Button>
                  )}
                </div>
              </CardHeader>
              <CardContent
                className={
                  result ? 'pt-3' : 'grid flex-1 place-items-center py-12'
                }
              >
                {result ? (
                  <>
                    <div className="mb-4 flex flex-wrap items-center justify-between gap-2 text-xs">
                      <span className="font-mono text-lg">
                        {number(result.metrics.ending_value)}{' '}
                        <span className="text-xs text-muted-foreground">
                          {result.currency}
                        </span>
                      </span>
                      <span className="flex items-center gap-4">
                        <span className="text-neutral-300">● Portfolio</span>
                        <span className="text-muted-foreground">
                          ● {result.request.benchmark}
                        </span>
                      </span>
                    </div>
                    <ChartContainer
                      config={chartConfig}
                      className="h-[280px] w-full"
                    >
                      <ComposedChart
                        data={result.equity_curve}
                        margin={{ left: 0, right: 8 }}
                      >
                        <CartesianGrid vertical={false} stroke="#ffffff0c" />
                        <XAxis
                          dataKey="date"
                          minTickGap={45}
                          tickFormatter={(value) => String(value).slice(0, 7)}
                          tickLine={false}
                          axisLine={false}
                        />
                        <YAxis
                          width={60}
                          tickFormatter={(value) =>
                            Intl.NumberFormat(undefined, {
                              notation: 'compact',
                            }).format(value)
                          }
                          tickLine={false}
                          axisLine={false}
                          domain={['auto', 'auto']}
                        />
                        <ChartTooltip content={<ChartTooltipContent />} />
                        <Area
                          dataKey="portfolio"
                          stroke="var(--color-portfolio)"
                          fill="var(--color-portfolio)"
                          fillOpacity={0.08}
                          strokeWidth={2}
                          isAnimationActive={false}
                        />
                        <Line
                          dataKey="benchmark"
                          stroke="var(--color-benchmark)"
                          strokeDasharray="4 4"
                          dot={false}
                          strokeWidth={1.5}
                          isAnimationActive={false}
                        />
                      </ComposedChart>
                    </ChartContainer>
                    <div className="mt-4 grid grid-cols-3 gap-3 border-t border-white/8 pt-4 text-xs text-muted-foreground">
                      <span>
                        Annualized return
                        <br />
                        <strong className="mt-1 block font-mono text-foreground">
                          {percent(result.metrics.annualized_return)}
                        </strong>
                      </span>
                      <span>
                        Benchmark-relative
                        <br />
                        <strong className="mt-1 block font-mono text-foreground">
                          {percent(result.metrics.excess_return)}
                        </strong>
                      </span>
                      <span>
                        Beta to benchmark
                        <br />
                        <strong className="mt-1 block font-mono text-foreground">
                          {number(result.metrics.beta)}
                        </strong>
                      </span>
                    </div>
                  </>
                ) : (
                  <div
                    aria-live="polite"
                    aria-atomic="true"
                    className="max-w-sm text-center"
                  >
                    <div className="mx-auto mb-4 grid size-12 place-items-center rounded-xl border border-neutral-700 bg-black text-neutral-300">
                      {busy ? (
                        <Loader2 className="size-5 animate-spin" />
                      ) : (
                        <BarChart3 className="size-5" />
                      )}
                    </div>
                    <h3 className="text-base font-medium">
                      {busy
                        ? 'Building your portfolio history'
                        : 'Start with a portfolio, not a prediction.'}
                    </h3>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      {busy
                        ? 'Fetching adjusted closes and checking common dates and currency. This may take up to two minutes.'
                        : 'Set weights to 100%, then analyze. No fabricated performance is displayed when market data is unavailable.'}
                    </p>
                  </div>
                )}
              </CardContent>
            </Card>

            {result && (
              <>
                <Card>
                  <CardHeader>
                    <CardTitle>Holdings & attribution</CardTitle>
                    <CardDescription>
                      Target vs end-of-window weight. Contribution is in
                      percentage points of total portfolio return.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Ticker</TableHead>
                          <TableHead className="text-right">
                            Target → end
                          </TableHead>
                          <TableHead className="text-right">
                            Adj. close
                          </TableHead>
                          <TableHead className="text-right">Return</TableHead>
                          <TableHead className="text-right">
                            Contribution
                          </TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {result.holdings.map((holding) => (
                          <TableRow key={holding.ticker}>
                            <TableCell className="font-mono font-semibold">
                              {holding.ticker}
                            </TableCell>
                            <TableCell className="text-right font-mono text-xs">
                              {number(holding.target_weight, 1)} →{' '}
                              {number(holding.ending_weight, 1)}%
                            </TableCell>
                            <TableCell className="text-right font-mono">
                              {number(holding.latest_adjusted_close)}
                            </TableCell>
                            <TableCell className="text-right font-mono">
                              {percent(holding.total_return)}
                            </TableCell>
                            <TableCell
                              className={
                                'text-right font-mono ' +
                                (holding.return_contribution >= 0
                                  ? 'text-neutral-300'
                                  : 'text-red-300')
                              }
                            >
                              {number(holding.return_contribution * 100)} pp
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                    <p className="mt-3 text-[11px] text-muted-foreground">
                      All closes in {result.currency}, adjusted for
                      splits/dividends; not live execution prices.
                      Concentration-adjusted effective holdings:{' '}
                      {number(result.metrics.effective_holdings, 1)}.
                    </p>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle>Drawdown</CardTitle>
                    <CardDescription>
                      Distance below the portfolio’s previous high.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <ChartContainer
                      config={chartConfig}
                      className="h-[145px] w-full"
                    >
                      <AreaChart data={result.equity_curve}>
                        <XAxis dataKey="date" hide />
                        <YAxis
                          tickFormatter={(value) =>
                            (value * 100).toFixed(0) + '%'
                          }
                          width={45}
                          tickLine={false}
                          axisLine={false}
                        />
                        <ChartTooltip
                          content={
                            <ChartTooltipContent
                              formatter={(value) => (
                                <span>Drawdown {percent(Number(value))}</span>
                              )}
                            />
                          }
                        />
                        <Area
                          dataKey="drawdown"
                          stroke="var(--color-drawdown)"
                          fill="var(--color-drawdown)"
                          fillOpacity={0.12}
                          isAnimationActive={false}
                        />
                      </AreaChart>
                    </ChartContainer>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader>
                    <CardTitle>Methodology & data notes</CardTitle>
                    <CardDescription>
                      {result.source} · retrieved{' '}
                      {new Date(result.retrieved_at).toLocaleString()}
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <ul className="space-y-2 text-xs leading-5 text-muted-foreground">
                      {result.warnings.map((warning) => (
                        <li
                          key={warning}
                          className="border-l-2 border-neutral-700 pl-3"
                        >
                          {warning}
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              </>
            )}
            <div className="flex items-start gap-2 rounded-lg border border-white/8 bg-white/[0.02] p-3 text-xs leading-5 text-muted-foreground">
              <ShieldCheck className="mt-0.5 size-4 shrink-0 text-neutral-300" />
              <p>
                Research workspace only. No brokerage connection or order
                submission. Allocation replay analyzes your chosen weights.
                Use Strategy research for regime strategies and validation. Historical performance does not
                guarantee future results.
              </p>
              <button type="button" onClick={onOpenResearch} className="text-neutral-300 underline">Open strategy research</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
