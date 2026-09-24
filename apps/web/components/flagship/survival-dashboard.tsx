'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowRight, Download, Loader2, Play, RefreshCw, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { DataTable, Panel } from '@/components/flagship/research-primitives';
import { researchApi, type ResearchJob } from '@/lib/flagship/research';
import { diagnosticValue, survivalBase, validateSurvivalConfig, type LayerMethod, type SurvivalBookEntry, type SurvivalLayer, type SurvivalRun, type SurvivalStatus } from '@/lib/flagship/survival';

type Catalog = { layers: LayerMethod[]; defaults: Record<string, unknown> };
type PaperRecord = { id: string; created_at: string; events?: Record<string, unknown>[]; observations?: number; strategy_version: string };
const label = (value: string) => value.replaceAll('_', ' ');

export function SurvivalBadge({ status }: { status: SurvivalStatus | 'queued' | 'running' | 'failed' }) {
  const color = status === 'FAIL' || status === 'failed' ? 'border-red-400/30 text-red-300' : status === 'PASS' ? 'border-blue-400/30 text-blue-300' : status === 'WARN' ? 'border-amber-400/30 text-amber-200' : 'text-muted-foreground';
  return <Badge variant="outline" className={color}>{status}</Badge>;
}

function Diagnostics({ value, name = 'Diagnostics', depth = 0 }: { value: unknown; name?: string; depth?: number }) {
  if (Array.isArray(value)) {
    if (!value.length) return <p className="text-xs text-muted-foreground">No {label(name).toLowerCase()}.</p>;
    if (value.every(item => item && typeof item === 'object' && !Array.isArray(item))) {
      const table = value as Record<string, unknown>[];
      const keys = [...new Set(table.flatMap(Object.keys))];
      return <div className="overflow-auto"><DataTable rows={table.slice(0, 100)} columns={keys.map(key => ({ label: label(key), value: (row: Record<string, unknown>) => <span className="font-mono text-xs break-all">{diagnosticValue(row[key])}</span> }))} />{table.length > 100 && <p className="mt-2 text-xs text-muted-foreground">First 100 of {table.length} rows. Complete observations are in the export.</p>}</div>;
    }
    return <pre className="max-h-64 overflow-auto whitespace-pre-wrap font-mono text-xs">{JSON.stringify(value.slice(0, 100), null, 2)}{value.length > 100 ? `\n… ${value.length} values in export` : ''}</pre>;
  }
  if (value && typeof value === 'object') {
    return <div className="space-y-3">{Object.entries(value).map(([key, item]) => item !== null && typeof item === 'object' ? <details key={key} open={depth < 1} className="rounded-md border border-white/10 p-3"><summary className="cursor-pointer text-xs font-medium">{label(key)}</summary><div className="mt-3"><Diagnostics name={key} value={item} depth={depth + 1} /></div></details> : <div key={key} className="flex flex-wrap justify-between gap-3 text-xs"><span className="text-muted-foreground">{label(key)}</span><span className="font-mono break-all">{diagnosticValue(item)}</span></div>)}</div>;
  }
  return <span className="font-mono text-xs">{diagnosticValue(value)}</span>;
}

function Layer({ definition, result }: { definition: LayerMethod; result?: SurvivalLayer }) {
  const scalarMetrics = Object.entries(result?.metrics ?? {}).filter(([, value]) => value === null || typeof value !== 'object');
  return <details className={`rounded-lg border bg-card ${result?.hard_failure ? 'border-red-500/50' : 'border-white/10'}`}>
    <summary className="flex cursor-pointer list-none flex-wrap items-start gap-3 p-4 hover:bg-white/[.02]">
      <span className="mt-0.5 font-mono text-xs text-blue-300">{String(definition.id).padStart(2, '0')}</span>
      <div className="min-w-0 flex-1"><h3 className="text-sm font-medium">{definition.name}</h3><p className="mt-1 text-xs leading-5 text-muted-foreground">{result?.reasons[0] ?? (result ? 'Diagnostics computed. Expand to inspect assumptions and configured gates.' : 'Awaiting this layer’s calculation.')}</p>
        {!!scalarMetrics.length && <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1">{scalarMetrics.slice(0, 4).map(([key, value]) => <span key={key} className="text-xs text-muted-foreground">{label(key)} <strong className="ml-1 font-mono font-normal text-foreground">{diagnosticValue(value)}</strong></span>)}</div>}
      </div>{result ? <SurvivalBadge status={result.status} /> : <Badge variant="outline">Pending</Badge>}
    </summary>
    <div className="space-y-5 border-t border-white/10 p-4">
      {result?.hard_failure && <p className="text-sm text-red-300">Hard integrity failure. Downstream financial diagnostics are blocked.</p>}
      {result && <><Diagnostics value={result.metrics} name="Metrics and confidence intervals" /><div className="space-y-1">{result.reasons.map((reason, i) => <p key={i} className="text-xs text-muted-foreground">• {reason}</p>)}</div>{!!result.gate_results.length && <Diagnostics value={result.gate_results} name="Configured gates" />}<Diagnostics value={result.diagnostics} /></>}
      <div className="grid gap-3 rounded-md border border-blue-500/20 bg-blue-500/[.03] p-3 text-xs leading-5 md:grid-cols-3"><p><strong className="block text-blue-200">Method</strong>{definition.methodology}</p><p><strong className="block text-blue-200">Assumptions & limitations</strong>{definition.assumptions}</p><p><strong className="block text-blue-200">Minimum data</strong>{definition.minimum_data}</p></div>
    </div>
  </details>;
}

export default function SurvivalDashboard({ job, jobs, openExperiment }: { job: ResearchJob; jobs: ResearchJob[]; openExperiment: () => void }) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [book, setBook] = useState<SurvivalBookEntry[]>([]);
  const [active, setActive] = useState<SurvivalRun | null>(null);
  const [configText, setConfigText] = useState('');
  const [peers, setPeers] = useState<string[]>([]);
  const [papers, setPapers] = useState<PaperRecord[]>([]);
  const [paperId, setPaperId] = useState('');
  const [paper, setPaper] = useState<PaperRecord | null>(null);
  const [paperText, setPaperText] = useState('');
  const [initialNav, setInitialNav] = useState(job.request.initial_capital);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const inFlight = useRef(false);
  const running = active?.status === 'queued' || active?.status === 'running';

  const refresh = useCallback(async () => {
    const [runs, forward] = await Promise.all([
      researchApi<{ runs: SurvivalBookEntry[] }>(`/survival/runs?experiment_id=${job.run_id}`),
      researchApi<{ records: PaperRecord[] }>(`/survival/paper?experiment_id=${job.run_id}`),
    ]);
    setBook(runs.runs);
    setPapers(forward.records);
    return runs.runs;
  }, [job.run_id]);

  useEffect(() => {
    let disposed = false;
    const timer = setTimeout(() => { void Promise.all([researchApi<Catalog>('/survival/catalog'), refresh()]).then(async ([next, runs]) => {
      if (disposed) return;
      setCatalog(next);
      setConfigText(JSON.stringify(next.defaults, null, 2));
      if (runs.length) {
        const saved = await researchApi<SurvivalRun>(`/survival/runs/${runs[0].id}`);
        if (!disposed && generation.current === 0) setActive(saved);
      }
    }).catch(cause => { if (!disposed) setError((cause as Error).message); }); }, 0);
    return () => { disposed = true; clearTimeout(timer); };
  }, [refresh]);

  useEffect(() => {
    if (!active?.id || !running) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const id = active.id;
    async function poll() {
      try {
        const run = await researchApi<SurvivalRun>(`/survival/runs/${id}`);
        if (disposed) return;
        setActive(current => current?.id === id ? run : current);
        if (run.status === 'queued' || run.status === 'running') timer = setTimeout(poll, 1500);
        else await refresh();
      } catch (cause) {
        if (!disposed) { setError((cause as Error).message); timer = setTimeout(poll, 5000); }
      }
    }
    timer = setTimeout(poll, 700);
    return () => { disposed = true; clearTimeout(timer); };
  }, [active?.id, running, refresh]);

  async function launch() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true); setError(''); setNotice('');
    try {
      const config = validateSurvivalConfig(configText);
      const run = await researchApi<SurvivalRun>('/survival/runs', { experiment_id: job.run_id, config, peer_experiment_ids: peers, forward_record_id: paperId || null });
      ++generation.current;
      setActive(run);
      setNotice(run.cached ? 'Reusing the saved run for identical inputs, code, configuration and trial history.' : 'Queued on Q’s shared research worker. Layer results appear as they complete.');
      await refresh();
    } catch (cause) { setError((cause as Error).message); }
    finally { inFlight.current = false; setBusy(false); }
  }

  async function selectRun(id: string) {
    const token = ++generation.current;
    try { const run = await researchApi<SurvivalRun>(`/survival/runs/${id}`); if (token === generation.current) setActive(run); }
    catch (cause) { setError((cause as Error).message); }
  }

  async function registerPaper() {
    setBusy(true); setError('');
    try {
      const record = await researchApi<PaperRecord>('/survival/paper', { experiment_id: job.run_id, initial_nav: initialNav });
      setPaperId(record.id); setPaper(record); await refresh();
      setNotice('Frozen forward record registered now. Only subsequent paper observations are eligible.');
    } catch (cause) { setError((cause as Error).message); }
    finally { setBusy(false); }
  }

  async function selectPaper(id: string) {
    setPaperId(id); setPaper(null);
    if (!id) return;
    try { setPaper(await researchApi<PaperRecord>(`/survival/paper/${id}`)); }
    catch (cause) { setError((cause as Error).message); }
  }

  async function appendPaper() {
    setBusy(true); setError('');
    try {
      await researchApi(`/survival/paper/${paperId}/events`, validateSurvivalConfig(paperText));
      setPaper(await researchApi<PaperRecord>(`/survival/paper/${paperId}`));
      setNotice('Forward paper event saved immutably. Run Survival again to include the new evidence.');
    } catch (cause) { setError((cause as Error).message); }
    finally { setBusy(false); }
  }

  const results = active?.result?.layers ?? active?.layers ?? [];
  const summary = active?.result?.summary;
  return <div className="space-y-4">
    <Panel title="Strategy Survival Pipeline" detail="18 layers of evidence · explicit gates · no composite score">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="font-medium">{job.name}</p><p className="mt-1 font-mono text-xs text-muted-foreground">Experiment {job.run_id}</p></div><Button variant="outline" onClick={openExperiment}>Underlying experiment<ArrowRight className="size-4" /></Button></div>
      <p className="mt-3 text-xs leading-5 text-muted-foreground">Archived experiments have already examined their historical dates. A chronological test segment remains retrospective. True forward evidence belongs in the separately registered paper record. Live execution is disabled.</p>
      {['demo', 'synthetic'].includes(job.request.data_mode) && <p className="mt-3 text-xs text-amber-200">SYNTHETIC SCENARIO · Tests mechanics and assumptions; no empirical investment inference.</p>}
      <div className="mt-4 flex flex-wrap items-center gap-2"><Button onClick={() => void launch()} disabled={busy || running || !catalog || job.status !== 'completed'}>{busy || running ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />}Run survival pipeline</Button><Button variant="outline" onClick={() => void refresh().catch(cause => setError(cause.message))}><RefreshCw className="size-4" />Refresh</Button>{active && <a className="inline-flex items-center gap-2 rounded-md border px-3 py-2 text-xs" href={`${survivalBase}/runs/${active.id}/export`}><Download className="size-4" />Export run, inputs & source</a>}</div>
      {job.status !== 'completed' && <p className="mt-3 text-sm text-muted-foreground">Complete a research experiment with an archived dataset before running survival validation. Failed experiments remain in the book.</p>}
      {error && <p role="alert" className="mt-3 rounded-md border border-red-400/30 p-3 text-sm text-red-200">{error}</p>}{notice && <p role="status" className="mt-3 text-xs text-blue-200">{notice}</p>}
    </Panel>

    <details className="rounded-lg border bg-card p-4"><summary className="cursor-pointer text-sm font-medium">Validation protocol & configurable research gates</summary><p className="my-3 text-xs leading-5 text-muted-foreground">Defaults are bounded research choices, not institutional standards. Missing evidence is N-A. Integrity failures cannot be waived. Gates use layer ID, metric path, operator, threshold and WARN/FAIL severity. Required N-A layers block gate satisfaction. Legacy mandate gates still apply to paper-candidate decisions.</p>
      <p className="mb-3 font-mono text-xs text-muted-foreground">Example gate: {JSON.stringify({ layer: 2, metric: 'test_sharpe', operator: '>=', threshold: job.request.min_oos_sharpe, severity: 'WARN' })}</p>
      <label className="block text-xs">Next-run configuration<textarea aria-label="Survival configuration JSON" className="mt-2 h-80 w-full rounded-md border bg-background p-3 font-mono text-xs" spellCheck={false} value={configText} onChange={e => setConfigText(e.target.value)} /></label>
      <p className="mt-2 text-xs text-muted-foreground">DSR needs effective_trials and a documented dsr_assumptions statement; its default is N-A. Parameters, seeds, folds, scope limits and gates are saved with every run.</p>
      <div className="mt-4"><p className="mb-2 text-xs font-medium">Existing strategies for portfolio interaction (up to 8)</p>{jobs.filter(other => other.run_id !== job.run_id && other.status === 'completed').slice(0, 40).map(other => <label key={other.run_id} className="mr-4 inline-flex items-center gap-2 text-xs"><input type="checkbox" checked={peers.includes(other.run_id)} disabled={!peers.includes(other.run_id) && peers.length >= 8} onChange={e => setPeers(current => e.target.checked ? [...current, other.run_id] : current.filter(id => id !== other.run_id))} />{other.name} · {other.run_id.slice(-8)}</label>)}</div>
    </details>

    {!!book.length && <div className="flex flex-wrap items-center gap-3"><label className="text-xs text-muted-foreground" htmlFor="survival-history">Saved validation runs</label><NativeSelect id="survival-history" value={active?.id ?? ''} onChange={e => void selectRun(e.target.value)}><NativeSelectOption value="" disabled>Select run</NativeSelectOption>{book.map(run => <NativeSelectOption key={run.id} value={run.id}>{run.created_at.replace('T', ' ').slice(0,19)} UTC · {run.summary?.status ?? run.status} · {run.id.slice(0,8)}</NativeSelectOption>)}</NativeSelect><span className="text-xs text-muted-foreground">All outcomes retained</span></div>}
    {active?.error && <p role="alert" className="rounded-lg border border-red-400/30 p-4 text-sm text-red-200">Run failed: {active.error}. Inputs and completed layers remain exportable.</p>}
    {summary ? <Panel title="Survival summary" detail={summary.interpretation}><div className="grid grid-cols-2 gap-3 md:grid-cols-4">{(['PASS', 'WARN', 'FAIL', 'N-A'] as const).map(status => <div key={status} className="rounded-lg border bg-background/40 p-3"><SurvivalBadge status={status} /><p className="mt-2 font-mono text-2xl">{summary.counts[status]}</p><p className="text-xs text-muted-foreground">layers</p></div>)}</div><p className="mt-4 flex items-center gap-2 text-sm"><ShieldCheck className="size-4 text-blue-300" />{summary.research_gates_satisfied ? 'Configured research gates satisfied; warnings and unavailable coverage still require review.' : 'Research gates unresolved. Review failed gates and required unavailable layers.'}</p>{!!summary.unresolved_required_layers.length && <p className="mt-2 text-xs text-amber-200">Required N-A layers: {summary.unresolved_required_layers.join(', ')}</p>}</Panel> : active && <p role="status" className="flex items-center gap-2 text-sm text-blue-200">{running && <Loader2 className="size-4 animate-spin" />}{active.status} · {results.length}/18 layer results saved</p>}
    <div className="space-y-2">{catalog?.layers.map(definition => <Layer key={definition.id} definition={definition} result={results.find(result => result.id === definition.id)} />)}</div>
    {active?.result && <details className="rounded-lg border bg-card p-4"><summary className="cursor-pointer text-sm">Frozen run configuration & provenance</summary><div className="mt-4"><Diagnostics value={{ strategy_version: active.result.strategy_version, input_hash: active.input_hash, config: active.result.config, provenance: active.result.provenance }} /></div><Button className="mt-3" variant="outline" onClick={() => { setConfigText(JSON.stringify(active.config, null, 2)); setNotice('Saved configuration loaded for a new validation run.'); }}>Use this configuration for next run</Button></details>}

    <details className="rounded-lg border bg-card p-4"><summary className="cursor-pointer text-sm font-medium">Forward paper evidence · separate from historical research</summary><p className="my-3 text-xs leading-5 text-muted-foreground">Register a frozen strategy now, then record subsequent signals and later fills/marks. This is a user-recorded paper ledger; Q does not execute orders or claim broker verification. Backdated events are rejected. Saved events cannot be edited.</p>
      <div className="flex flex-wrap items-end gap-3"><label className="text-xs">Initial paper NAV<Input type="number" min={1} value={initialNav} onChange={e => setInitialNav(Number(e.target.value))} /></label><Button variant="outline" disabled={busy || job.status !== 'completed'} onClick={() => void registerPaper()}>Register forward record now</Button></div>
      <label className="mt-4 block text-xs">Record to include in next survival run<NativeSelect className="mt-2" value={paperId} onChange={e => void selectPaper(e.target.value)}><NativeSelectOption value="">No forward record selected</NativeSelectOption>{papers.map(record => <NativeSelectOption key={record.id} value={record.id}>{record.created_at.slice(0,19)} UTC · {record.id.slice(0,12)}</NativeSelectOption>)}</NativeSelect></label>
      {paperId && <><p className="my-3 text-xs text-muted-foreground">Signal: kind, observed_at (UTC), weights, expected_return (optional), cost_bps, regime. Observation: kind, observed_at, signal_id from a previously saved signal, nav, weights, cost_bps, fills (symbol, integer quantity, price), regime. observed_at must be after registration; fills must follow the signal’s recorded timestamp.</p><label className="text-xs">Paper event JSON<textarea aria-label="Forward paper event JSON" className="mt-2 h-40 w-full rounded-md border bg-background p-3 font-mono text-xs" value={paperText} onChange={e => setPaperText(e.target.value)} /></label><Button variant="outline" disabled={busy || !paperText.trim()} onClick={() => void appendPaper()}>Record paper event</Button>{paper && <div className="mt-4"><Diagnostics value={paper} /></div>}</>}
    </details>
  </div>;
}
