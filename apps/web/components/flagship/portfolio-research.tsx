'use client';

import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react';
import { ChartNoAxesCombined, FlaskConical } from 'lucide-react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

const StrategyResearch = lazy(() => import('./research-workspace'));
const AllocationReplay = lazy(() => import('./allocation-replay'));

export type PortfolioResearchView = 'strategies' | 'allocation';

function ResearchPane({ value, active, children }: {
  value: PortfolioResearchView;
  active: boolean;
  children: ReactNode;
}) {
  const [visited, setVisited] = useState(active);
  useEffect(() => { if (active) setVisited(true); }, [active]);

  return (
    <TabsContent value={value} forceMount className="min-w-0 data-[state=inactive]:hidden">
      {/* Keep visited workflows mounted: changing tabs must not abort a replay,
          stop job polling, or discard drafts, results and import previews. */}
      {(active || visited) && (
        <Suspense fallback={<div className="empty">Loading research workspace…</div>}>
          {children}
        </Suspense>
      )}
    </TabsContent>
  );
}

export default function PortfolioResearch({ view, onViewChange }: {
  view: PortfolioResearchView;
  onViewChange: (view: PortfolioResearchView) => void;
}) {
  return (
    <section className="min-w-0" aria-labelledby="portfolio-research-title">
      <div className="mb-5">
        <h1 id="portfolio-research-title" className="text-2xl font-semibold tracking-tight">Portfolio research</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Test strategy portfolios and replay custom allocations against historical data.
        </p>
      </div>
      <Tabs value={view} onValueChange={value => onViewChange(value as PortfolioResearchView)} className="gap-5">
        <TabsList aria-label="Portfolio research workflows" className="h-auto max-w-full flex-wrap">
          <TabsTrigger value="strategies"><FlaskConical />Strategy research</TabsTrigger>
          <TabsTrigger value="allocation"><ChartNoAxesCombined />Allocation replay</TabsTrigger>
        </TabsList>
        <ResearchPane value="strategies" active={view === 'strategies'}>
          <StrategyResearch />
        </ResearchPane>
        <ResearchPane value="allocation" active={view === 'allocation'}>
          <AllocationReplay onOpenResearch={() => onViewChange('strategies')} />
        </ResearchPane>
      </Tabs>
    </section>
  );
}
