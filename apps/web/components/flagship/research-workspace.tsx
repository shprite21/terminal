'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Copy,
  FlaskConical,
  Loader2,
  RefreshCw,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  NativeSelect,
  NativeSelectOption,
} from '@/components/ui/native-select';
import { Mandate } from '@/components/flagship/research-mandate';
import { ResearchEvidence } from '@/components/flagship/research-evidence';
import SurvivalDashboard, { SurvivalBadge } from '@/components/flagship/survival-dashboard';
import type { SurvivalBookEntry } from '@/lib/flagship/survival';
import { DataTable, Panel, Status } from '@/components/flagship/research-primitives';
import {
  comparableRuns,
  defaults,
  num,
  pct,
  researchApi,
  validateResearch,
  type Catalog,
  type Decision,
  type Evidence,
  type ResearchJob,
  type ResearchRequest,
} from '@/lib/flagship/research';

type View = 'overview' | 'validation' | 'survival' | 'portfolio' | 'experiments';
const views: { id: View; label: string }[] = [
  { id: 'overview', label: 'Research overview' },
  { id: 'validation', label: 'Validation' },
  { id: 'survival', label: 'Strategy Survival' },
  { id: 'portfolio', label: 'Portfolio & risk' },
  { id: 'experiments', label: 'Experiment book' },
];

export default function ResearchWorkspace() {
  const [draft, setDraft] = useState<ResearchRequest>(defaults);
  const [draftVersion, setDraftVersion] = useState(0);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [jobs, setJobs] = useState<ResearchJob[]>([]);
  const [active, setActive] = useState<ResearchJob | null>(null);
  const [view, setView] = useState<View>('overview');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [connected, setConnected] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [loading, setLoading] = useState(false);
  const [compare, setCompare] = useState<string[]>([]);
  const [survivalBook, setSurvivalBook] = useState<SurvivalBookEntry[]>([]);
  useEffect(() => {
    if (view !== 'experiments') return;
    let disposed = false;
    void researchApi<{ runs: SurvivalBookEntry[] }>('/survival/runs').then(book => {
      if (!disposed) setSurvivalBook(book.runs);
    }).catch(() => { /* Research book remains available if survival is offline. */ });
    return () => { disposed = true; };
  }, [view]);
  const selection = useRef(0);
  const launching = useRef(false);
  const running = active?.status === 'queued' || active?.status === 'running';
  const activeRunId = active?.run_id;
  // Canonical ordering avoids treating server key ordering as an edited mandate.
  const fingerprint = (request: ResearchRequest) =>
    JSON.stringify(
      Object.fromEntries(
        Object.entries(request).sort(([a], [b]) => a.localeCompare(b)),
      ),
    );
  const changed = active && fingerprint(active.request) !== fingerprint(draft);

  const connect = useCallback(async () => {
    try {
      const [nextCatalog, book] = await Promise.all([
        researchApi<Catalog>('/catalog'),
        researchApi<{ runs: ResearchJob[] }>('/runs'),
      ]);
      setCatalog(nextCatalog);
      setJobs(book.runs);
      setConnected(true);
      setError('');
      const latest = book.runs.find(job => job.status !== 'failed');
      if (selection.current === 0 && latest) {
        const evidence = await researchApi<ResearchJob>(`/runs/${latest.run_id}`);
        if (selection.current === 0) setActive(evidence);
      }
    } catch (cause) {
      setConnected(false);
      setError((cause as Error).message);
    }
  }, []);
  useEffect(() => {
    const timer = setTimeout(() => void connect(), 0);
    return () => clearTimeout(timer);
  }, [connect]);

  async function selectRun(runId: string) {
    const token = ++selection.current;
    setLoading(true);
    setError('');
    setNotice('');
    try {
      const job = await researchApi<ResearchJob>(`/runs/${runId}`);
      if (token === selection.current) setActive(job);
    } catch (cause) {
      if (token === selection.current) setError((cause as Error).message);
    } finally {
      if (token === selection.current) setLoading(false);
    }
  }
  useEffect(() => {
    if (!activeRunId || !running) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const runId = activeRunId;
    async function poll() {
      try {
        const job = await researchApi<ResearchJob>(`/runs/${runId}`);
        if (disposed) return;
        setActive((current) => (current?.run_id === runId ? job : current));
        setConnected(true);
        setError('');
        setJobs((current) =>
          current.map((row) =>
            row.run_id === runId ? { ...job, result: undefined } : row,
          ),
        );
        if (job.status === 'running' || job.status === 'queued')
          timer = setTimeout(poll, 1800);
      } catch (cause) {
        if (!disposed) {
          setError((cause as Error).message);
          setConnected(false);
          timer = setTimeout(poll, 5000);
        }
      }
    }
    timer = setTimeout(poll, 1000);
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [activeRunId, running]);

  async function launch() {
    if (launching.current) return;
    setError('');
    setNotice('');
    try {
      const request = validateResearch(draft);
      launching.current = true;
      setSubmitting(true);
      const job = await researchApi<ResearchJob>('/runs', request);
      ++selection.current;
      setLoading(false);
      setActive(job);
      setJobs((current) => [job, ...current]);
      setDraft(current => fingerprint(current) === fingerprint(draft) ? request : current);
      setView('overview');
      setConnected(true);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      launching.current = false;
      setSubmitting(false);
    }
  }
  function clone() {
    if (!active) return;
    setDraft({
      ...active.request,
      name: `${active.request.name.slice(0, 69)} — variant`,
      snapshot_run_id: active.status === 'completed' ? active.run_id : null,
    });
    setDraftVersion((value) => value + 1);
    setNotice(
      'Configuration loaded. Edit the variant and run a new experiment.',
    );
  }
  async function decide(status: Decision['status'], rationale: string) {
    if (!active) return;
    const runId = active.run_id;
    setError('');
    try {
      const job = await researchApi<ResearchJob>(`/runs/${runId}/decision`, {
        status,
        rationale,
      });
      setActive((current) => (current?.run_id === runId ? job : current));
      setJobs((current) =>
        current.map((row) =>
          row.run_id === runId ? { ...job, result: undefined } : row,
        ),
      );
      setNotice('Research decision recorded in the evidence memo.');
    } catch (cause) {
      setError((cause as Error).message);
      throw cause;
    }
  }
  const compared = jobs.filter((job) => compare.includes(job.run_id));

  return (
    <div className="min-h-0">
      <div className="flex items-center justify-end gap-3 mb-4"><span>{connected ? "Research engine connected" : "Research engine offline"}</span><Button variant="outline" onClick={() => void connect()}><RefreshCw className="size-4" />Reconnect</Button></div>
      <div className="mx-auto max-w-full py-2">
        <div className="mb-5 flex flex-wrap items-center justify-end gap-3">
          <div className="flex items-center gap-3">
            <Badge variant="outline">Local research · no order routing</Badge>
            <Button disabled={submitting || !connected} onClick={() => void launch()}>
              {submitting ? <Loader2 className="size-4 animate-spin" /> : <FlaskConical className="size-4" />}
              Run research
            </Button>
          </div>
        </div>
        {error && (
          <div
            role="alert"
            className="mb-4 rounded-lg border border-red-400/35 bg-red-400/10 p-4 text-sm text-red-200"
          >
            {error}
          </div>
        )}
        {notice && (
          <output className="block mb-4 rounded-lg border border-neutral-700 p-3 text-sm text-neutral-300">
            {notice}
          </output>
        )}
        <div className="grid items-start gap-6 xl:grid-cols-[350px_minmax(0,1fr)]">
          <Mandate
            key={draftVersion}
            draft={draft}
            change={setDraft}
            catalog={catalog}
            connected={connected}
            submitting={submitting}
            launch={() => void launch()}
          />
          <section className="min-w-0 space-y-5" aria-label="Research evidence">
            <div className="rounded-xl border bg-card p-4">
              <div className="flex flex-wrap items-center gap-3">
                <FlaskConical className="size-5 text-neutral-300" />
                <div className="min-w-0 flex-1">
                  <h2 className="font-semibold">
                    {active?.name ?? 'Select or run an experiment'}
                  </h2>
                  <p className="mt-1 break-all font-mono text-xs text-muted-foreground">
                    {active?.run_id ??
                      'Evidence is generated by the Python research system.'}
                  </p>
                </div>
                {active && <Status value={active.status} />}
                {active && (
                  <Button variant="outline" size="sm" onClick={clone}>
                    <Copy className="size-4" />
                    Clone configuration
                  </Button>
                )}
              </div>
              <div className="mt-4 flex flex-wrap gap-3">
                <NativeSelect
                  className="min-w-0 flex-1"
                  aria-label="Open experiment"
                  value={active?.run_id ?? ''}
                  onChange={(e) => {
                    if (e.target.value) void selectRun(e.target.value);
                  }}
                >
                  <NativeSelectOption value="">
                    Open saved experiment…
                  </NativeSelectOption>
                  {jobs.map((job) => (
                    <NativeSelectOption key={job.run_id} value={job.run_id}>
                      {job.name} · {job.request.data_mode} · {job.status} ·{' '}
                      {job.created_at.slice(0, 16)}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => void connect()}
                >
                  <RefreshCw className="size-4" />
                  Refresh book
                </Button>
              </div>
              {changed && (
                <p className="mt-3 text-sm text-amber-200">
                  The mandate differs from this saved run. Displayed evidence
                  belongs to the frozen configuration.
                </p>
              )}
              {loading && (
                <output className="mt-3 flex items-center gap-2 text-sm">
                  <Loader2 className="size-4 animate-spin" />
                  Loading evidence…
                </output>
              )}
            </div>
            <nav
              aria-label="Research views"
              className="flex flex-wrap gap-1 border-b pb-2"
            >
              {views.map((item) => (
                <Button
                  key={item.id}
                  variant={view === item.id ? 'secondary' : 'ghost'}
                  aria-current={view === item.id ? 'page' : undefined}
                  onClick={() => setView(item.id)}
                >
                  {item.label}
                </Button>
              ))}
            </nav>
            {running && (
              <output className="flex items-start gap-3 rounded-xl border border-neutral-700 bg-black p-5">
                <Loader2 className="mt-1 size-5 animate-spin text-neutral-300" />
                <div>
                  <p className="font-medium">{active.stage}</p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Calculating signals, constraints and diagnostics from one
                    snapshot. You can keep editing the next study.
                  </p>
                </div>
              </output>
            )}
            {active?.status === 'failed' && (
              <div
                role="alert"
                className="rounded-xl border border-red-300/30 p-5"
              >
                <p className="font-medium text-red-200">Experiment failed</p>
                <p className="mt-2 text-sm">{active.error}</p>
                <Button onClick={clone} variant="outline" className="mt-4">
                  Load configuration to retry
                </Button>
              </div>
            )}
            {view === 'experiments' ? (
              <>
                <Panel
                  title="Experiment book"
                  detail="Persistent configurations, outcomes and PM decisions. Select up to three completed runs to compare."
                >
                  {!jobs.length ? (
                    <p className="text-sm text-muted-foreground">
                      No experiments yet. Configure the mandate and run your
                      first study.
                    </p>
                  ) : (
                    <DataTable
                      rows={jobs}
                      columns={[
                        {
                          label: 'Compare',
                          value: (job) => (
                            <input
                              aria-label={`Compare ${job.name}`}
                              type="checkbox"
                              className="size-4 accent-blue-400"
                              disabled={
                                job.status !== 'completed' ||
                                (compare.length >= 3 &&
                                  !compare.includes(job.run_id))
                              }
                              checked={compare.includes(job.run_id)}
                              onChange={(e) =>
                                setCompare((current) =>
                                  e.target.checked
                                    ? [...current, job.run_id]
                                    : current.filter((id) => id !== job.run_id),
                                )
                              }
                            />
                          ),
                        },
                        {
                          label: 'Study',
                          value: (job) => (
                            <>
                              <button
                                className="text-left text-neutral-300 underline-offset-4 hover:underline"
                                onClick={() => {
                                  void selectRun(job.run_id);
                                  setView('overview');
                                }}
                              >
                                {job.name}
                              </button>
                              <p className="mt-1 text-xs text-muted-foreground">
                                {job.request.data_mode} ·{' '}
                                {job.created_at.slice(0, 10)} ·{' '}
                                {job.run_id.slice(-8)}
                              </p>
                            </>
                          ),
                        },
                        {
                          label: 'State',
                          value: (job) => <Status value={job.status} />,
                        },
                        {
                          label: 'OOS Sharpe',
                          value: (job) => num(job.validation_metrics?.sharpe),
                        },
                        {
                          label: 'Survival',
                          value: (job) => {
                            const saved = survivalBook.find(run => run.experiment_id === job.run_id);
                            return <button className="text-left text-xs text-blue-200" onClick={() => { void selectRun(job.run_id); setView('survival'); }}>
                              {saved?.summary ? <SurvivalBadge status={saved.summary.status} /> : saved ? saved.status : 'Open pipeline'}
                              {saved?.summary && <span className="mt-1 block text-muted-foreground">{saved.summary.counts.FAIL} fail · {saved.summary.counts.WARN} warn · {saved.summary.counts['N-A']} N/A</span>}
                            </button>;
                          },
                        },
                        {
                          label: 'Decision',
                          value: (job) =>
                            job.decision?.status.replaceAll('_', ' ') ??
                            'Unreviewed',
                        },
                      ]}
                    />
                  )}
                </Panel>
                {compared.length > 0 && (
                  <Panel title="Compare evidence">
                    {!comparableRuns(compared) && (
                      <p className="mb-4 rounded-lg border border-amber-300/30 p-3 text-sm text-amber-100">
                        Different data snapshots, evaluation dates or validation
                        windows. These metrics are not a controlled comparison;
                        align the studies before drawing conclusions.
                      </p>
                    )}
                    <DataTable
                      rows={[
                        'sharpe',
                        'total_return',
                        'max_drawdown',
                        'annualized_volatility',
                      ]}
                      columns={[
                        {
                          label: 'Measure',
                          value: (key) => `OOS ${key.replaceAll('_', ' ')}`,
                        },
                        ...compared.map((job) => ({
                          label: `${job.name} · ${job.run_id.slice(-8)}`,
                          value: (key: string) =>
                            key === 'sharpe'
                              ? num(job.validation_metrics?.[key])
                              : pct(job.validation_metrics?.[key]),
                        })),
                      ]}
                    />
                    <div className="mt-4 grid gap-3 md:grid-cols-3">
                      {compared.map((job) => (
                        <div
                          className="rounded-md border p-3 text-xs text-muted-foreground"
                          key={job.run_id}
                        >
                          <strong className="text-foreground">
                            {job.name}
                          </strong>
                          <br />
                          {job.request.data_mode} · {job.request.rebalance}
                          <br />
                          {job.request.sleeves
                            .map(
                              (s) =>
                                `${s.strategy}: ${s.budget}% / ${s.lookback}d`,
                            )
                            .join('; ')}
                          <br />
                          Evaluation: {job.evaluation_start} → {job.end_date}
                        </div>
                      ))}
                    </div>
                  </Panel>
                )}
              </>
            ) : view === 'survival' && active ? (
              <SurvivalDashboard key={active.run_id} job={active} jobs={jobs} openExperiment={() => setView('overview')} />
            ) : active?.result && view !== 'survival' ? (
              <ResearchEvidence
                key={active.run_id}
                job={active as ResearchJob & { result: Evidence }}
                view={view}
                onDecision={decide}
              />
            ) : (
              !running &&
              active?.status !== 'failed' && (
                <Panel
                  title="Build an evidence-backed investment decision"
                  detail="The workspace calls the research modules used by the Python platform."
                >
                  <div className="grid gap-4 md:grid-cols-2">
                    {[
                      [
                        'Test the hypothesis',
                        'Select strategy sleeves, signal lookbacks and portfolio constraints. Every run uses one archived market snapshot.',
                      ],
                      [
                        'Challenge the result',
                        'Inspect chronological test windows, cost stress and parameter sensitivity before accepting a headline return.',
                      ],
                      [
                        'Explain portfolio risk',
                        'Trace targets to signals. Review benchmark beta, concentration, drawdown, attribution and indicative rebalances.',
                      ],
                      [
                        'Keep a research record',
                        'Compare saved experiments, record a rationale and export the memo with data and code provenance.',
                      ],
                    ].map(([title, text], i) => (
                      <div
                        className="rounded-lg border bg-background/40 p-5"
                        key={title}
                      >
                        <p className="mb-4 font-mono text-sm text-neutral-300">
                          0{i + 1}
                        </p>
                        <h3 className="font-medium">{title}</h3>
                        <p className="mt-2 text-sm leading-6 text-muted-foreground">
                          {text}
                        </p>
                      </div>
                    ))}
                  </div>
                  <p className="mt-5 text-sm text-muted-foreground">
                    Choose Synthetic to exercise the complete workflow offline,
                    or Yahoo / Massive for market observations. Results appear after a run
                    completes.
                  </p>
                  {!connected && (
                    <div className="mt-4 rounded-lg border border-amber-300/30 p-4 text-sm">
                      <p>
                        Start the API from the repository root, then reconnect:
                      </p>
                      <code className="mt-2 block overflow-x-auto text-xs">
                        .\.venv\Scripts\python.exe -m uvicorn
                        apps.portfolio_api:app --host 127.0.0.1 --port 8000
                      </code>
                    </div>
                  )}
                </Panel>
              )
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
