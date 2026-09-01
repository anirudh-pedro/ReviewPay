import { useEffect, useState } from 'react';
import {
  Bot,
  ChevronDown,
  CircleAlert,
  Play,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { getScenarios, runAutopilot } from '@/api';
import type { AutopilotCase, AutopilotResponse } from '@/types/api';
import {
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  Skeleton,
  StatusBadge,
  cx,
} from '@/components/ui';
import { useToast } from '@/components/Toast';
import { useDemoData } from '@/contexts/DemoDataContext';
import { useApi, useAsyncAction } from '@/hooks/useApi';
import { formatDateTime, formatMoney, formatPercent, humanize } from '@/utils/format';
import {
  caseStateTone,
  executionStatusTone,
  policyOutcomeTone,
} from '@/utils/recoveryPresentation';

function Metric({ label, value, tone = 'text-slate-100' }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-white/[0.06] bg-ink-900/45 p-4">
      <p className="text-[0.64rem] font-semibold uppercase tracking-[0.12em] text-slate-500">{label}</p>
      <p className={cx('metric-value mt-2 text-metric-sm font-semibold', tone)}>{value}</p>
    </div>
  );
}

function AutopilotSkeleton() {
  return (
    <div aria-busy="true" className="space-y-5" role="status">
      <span className="sr-only">Loading Autopilot scenarios.</span>
      <Card className="surface-grid p-5 sm:p-6"><Skeleton className="h-4 w-32" /><Skeleton className="mt-4 h-8 w-[min(35rem,85%)]" /><Skeleton className="mt-3 h-4 w-full max-w-xl" /><Skeleton className="mt-7 h-24 w-full" /></Card>
      <div className="grid gap-4 lg:grid-cols-2">{[0, 1, 2, 3].map((item) => <Card key={item} className="p-5"><Skeleton className="h-4 w-44" /><Skeleton className="mt-3 h-3 w-full" /><Skeleton className="mt-5 h-16 w-full" /></Card>)}</div>
    </div>
  );
}

function ScenarioDeck({ scenarios }: { scenarios: Awaited<ReturnType<typeof getScenarios>> }) {
  return (
    <section>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3"><div><p className="text-sm font-semibold text-slate-100">Deterministic demo scenarios</p><p className="mt-1 text-xs leading-5 text-slate-500">The backend supplies the narrative, expected route, and current state for every demo case.</p></div><StatusBadge tone="info">{scenarios.scenarios.length} scenarios</StatusBadge></div>
      <div className="grid gap-4 lg:grid-cols-2">
        {scenarios.scenarios.map((scenario) => (
          <Card key={scenario.key} className="overflow-hidden p-5 transition-shadow hover:shadow-card-hover">
            <div className="flex items-start justify-between gap-4"><div className="flex min-w-0 gap-3"><span className="grid size-8 shrink-0 place-items-center rounded-lg border border-accent/25 bg-accent/10 font-mono text-sm font-bold text-accent">{scenario.key}</span><div><p className="text-sm font-semibold text-slate-100">{scenario.title}</p><p className="mt-1 font-mono text-[0.66rem] text-slate-600">{scenario.case_id}</p></div></div><StatusBadge tone={caseStateTone(scenario.current_state)}>{humanize(scenario.current_state)}</StatusBadge></div>
            <p className="mt-4 text-sm leading-6 text-slate-400">{scenario.narrative}</p>
            <div className="mt-4 grid gap-2 sm:grid-cols-3"><div><p className="text-[0.62rem] uppercase tracking-[0.1em] text-slate-600">At risk</p><p className="mt-1 font-mono text-xs text-amber-100">{formatMoney(scenario.amount)}</p></div><div><p className="text-[0.62rem] uppercase tracking-[0.1em] text-slate-600">Expected action</p><p className="mt-1 text-xs text-slate-200">{humanize(scenario.expected_action)}</p></div><div><p className="text-[0.62rem] uppercase tracking-[0.1em] text-slate-600">Expected final state</p><p className="mt-1 text-xs text-slate-200">{humanize(scenario.expected_final_state)}</p></div></div>
          </Card>
        ))}
      </div>
    </section>
  );
}

function ResultCard({ result, index }: { result: AutopilotCase; index: number }) {
  return (
    <article className="animate-fade-up overflow-hidden rounded-xl border border-white/[0.06] bg-ink-850 shadow-card" style={{ animationDelay: `${Math.min(index * 55, 330)}ms` }}>
      <div className="flex flex-col justify-between gap-4 border-b border-white/[0.055] px-5 py-4 sm:flex-row sm:items-start">
        <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><StatusBadge tone={caseStateTone(result.final_state)}>{humanize(result.final_state)}</StatusBadge>{result.policy_outcome ? <StatusBadge tone={policyOutcomeTone(result.policy_outcome)}>{humanize(result.policy_outcome)}</StatusBadge> : null}</div><p className="mt-3 font-mono text-sm font-semibold text-slate-100">{result.case_id}</p><p className="mt-1 text-xs text-slate-500">{humanize(result.failure_reason)} · {humanize(result.payment_method)}</p></div>
        <div className="text-left sm:text-right"><p className="font-mono text-lg font-semibold tabular-nums text-amber-100">{formatMoney(result.amount_at_risk)}</p><p className={cx('mt-1 font-mono text-xs tabular-nums', result.recovered ? 'text-green-300' : 'text-slate-500')}>Recovered {formatMoney(result.recovered_amount)}</p></div>
      </div>
      <div className="grid gap-3 p-5 sm:grid-cols-3"><div><p className="text-[0.62rem] uppercase tracking-[0.1em] text-slate-600">Selected action</p><p className="mt-1 text-sm font-medium text-slate-200">{result.selected_action ? humanize(result.selected_action) : 'None executed'}</p></div><div><p className="text-[0.62rem] uppercase tracking-[0.1em] text-slate-600">Expected recovery value</p><p className="mt-1 font-mono text-sm text-sky-200">{result.expected_recovery_value ? formatMoney(result.expected_recovery_value) : 'Not recorded'}</p></div><div><p className="text-[0.62rem] uppercase tracking-[0.1em] text-slate-600">Workflow runs</p><p className="mt-1 font-mono text-sm text-slate-200">{result.runs} run{result.runs === 1 ? '' : 's'} · {result.clock_advances} clock advances</p></div></div>
      {result.explanation ? <p className="border-t border-white/[0.055] px-5 py-3 text-sm leading-6 text-slate-400">{result.explanation}</p> : null}
      {result.policy_reason ? <p className="border-t border-white/[0.055] bg-ink-900/35 px-5 py-3 text-xs leading-5 text-slate-400"><span className="font-semibold text-slate-300">Policy · </span>{result.policy_reason}</p> : null}
      {result.error ? <p className="border-t border-blocked/20 bg-blocked/[0.045] px-5 py-3 text-xs leading-5 text-red-200">{result.error}</p> : null}
      {result.steps.length > 0 ? <details className="group border-t border-white/[0.055] px-5 py-3"><summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-xs font-semibold text-slate-300 marker:hidden">Workflow evidence ({result.steps.length} runs)<ChevronDown aria-hidden="true" className="size-3.5 text-slate-500 transition-transform group-open:rotate-180" /></summary><ol className="mt-4 space-y-3">{result.steps.map((step) => <li key={`${result.case_id}-${step.run_index}`} className="rounded-lg border border-white/[0.055] bg-ink-900/45 p-3"><div className="flex flex-wrap items-center justify-between gap-2"><div className="flex flex-wrap items-center gap-2"><span className="font-mono text-[0.68rem] text-slate-500">Run {step.run_index}</span><StatusBadge tone={caseStateTone(step.state)}>{humanize(step.state)}</StatusBadge>{step.policy_outcome ? <StatusBadge tone={policyOutcomeTone(step.policy_outcome)}>{humanize(step.policy_outcome)}</StatusBadge> : null}{step.execution_status ? <StatusBadge tone={executionStatusTone(step.execution_status)}>{humanize(step.execution_status)}</StatusBadge> : null}</div><span className="font-mono text-xs text-green-300">{formatMoney(step.recovered_amount)}</span></div><p className="mt-2 text-xs leading-5 text-slate-400">{step.message}</p>{step.stages.length ? <p className="mt-2 font-mono text-[0.65rem] text-slate-600">{step.stages.map(humanize).join(' → ')}</p> : null}</li>)}</ol></details> : null}
    </article>
  );
}

function BatchResult({ revealedCount, result }: { revealedCount: number; result: AutopilotResponse }) {
  const visibleResults = result.results.slice(0, revealedCount);
  const isReplaying = revealedCount < result.results.length;
  const revealProgress = result.results.length ? revealedCount / result.results.length : 1;

  return (
    <section className="space-y-5" aria-live="polite">
      <Card className="overflow-hidden border-accent/20 bg-accent/[0.035]">
        <CardHeader><div><div className="flex items-center gap-2"><Sparkles aria-hidden="true" className="size-4 text-accent" /><p className="text-sm font-semibold text-slate-100">Autopilot outcome</p></div><p className="mt-1 text-xs leading-5 text-slate-500">Results returned by the real recovery workflow at {formatDateTime(result.ended_at)}.</p></div><StatusBadge tone={isReplaying ? 'info' : 'success'}>{isReplaying ? `Replaying ${revealedCount}/${result.results.length}` : 'Complete'}</StatusBadge></CardHeader>
        <div className="p-5 pt-4"><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><Metric label="Processed cases" value={String(result.total_cases)} /><Metric label="Recovered" tone="text-green-300" value={String(result.cases_recovered)} /><Metric label="Stopped" value={String(result.cases_stopped)} /><Metric label="Escalated" tone="text-violet-300" value={String(result.cases_escalated)} /><Metric label="Revenue recovered" tone="text-green-300" value={formatMoney(result.total_recovered)} /><Metric label="Recovery rate" tone="text-sky-200" value={formatPercent(result.recovery_rate)} /><Metric label="Actions executed" value={String(result.actions_executed)} /><Metric label="Policy blocks" tone="text-red-300" value={String(result.actions_blocked)} /></div><div className="mt-5 h-1.5 overflow-hidden rounded-full bg-white/[0.06]"><div className="h-full bg-accent transition-[width] duration-300" style={{ width: `${revealProgress * 100}%` }} /></div></div>
      </Card>
      {visibleResults.length ? <div className="grid gap-4 xl:grid-cols-2">{visibleResults.map((caseResult, index) => <ResultCard key={caseResult.case_id} index={index} result={caseResult} />)}</div> : <Card><EmptyState compact description="The backend completed the batch but returned no eligible cases to display." icon={Bot} title="No batch cases returned" /></Card>}
    </section>
  );
}

export function AutopilotPage() {
  const { dataVersion, demoResetVersion, refreshLiveData } = useDemoData();
  const { notify } = useToast();
  const scenarios = useApi(getScenarios, [dataVersion]);
  const batch = useAsyncAction(runAutopilot);
  const [limitInput, setLimitInput] = useState('');
  const [revealedCount, setRevealedCount] = useState(0);
  const requestedLimit = limitInput.trim() ? Number(limitInput) : undefined;
  const validLimit = requestedLimit === undefined || (Number.isInteger(requestedLimit) && requestedLimit >= 1 && requestedLimit <= 200);

  useEffect(() => {
    batch.reset();
    setRevealedCount(0);
    // A demo reset invalidates prior batch evidence; leave only freshly reseeded scenarios visible.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [demoResetVersion]);

  useEffect(() => {
    setRevealedCount(0);
    if (!batch.data?.results.length) return;

    const timer = window.setInterval(() => {
      setRevealedCount((current) => {
        const next = Math.min(current + 1, batch.data?.results.length ?? 0);
        if (next === batch.data?.results.length) window.clearInterval(timer);
        return next;
      });
    }, 360);

    return () => window.clearInterval(timer);
  }, [batch.data]);

  async function handleRun() {
    if (!validLimit) return;
    try {
      const result = await batch.run(requestedLimit === undefined ? {} : { limit: requestedLimit });
      refreshLiveData();
      notify({ tone: 'success', message: `Autopilot processed ${result.total_cases} real synthetic recovery cases.` });
    } catch {
      // The structured API error is rendered below.
    }
  }

  if (scenarios.loading && !scenarios.data) return <AutopilotSkeleton />;
  if (scenarios.error && !scenarios.data) return <ErrorState error={scenarios.error} onRetry={scenarios.refetch} title="Autopilot scenarios are unavailable" />;

  return (
    <div className="space-y-6">
      <Card className="surface-grid overflow-hidden p-5 sm:p-6">
        <div className="flex flex-col justify-between gap-6 xl:flex-row xl:items-end"><div className="max-w-2xl"><div className="flex items-center gap-2"><span className="grid size-9 place-items-center rounded-xl border border-accent/25 bg-accent/10 text-accent"><Bot aria-hidden="true" className="size-5" /></span><StatusBadge tone="info">Deterministic batch</StatusBadge></div><h1 className="mt-4 text-xl font-semibold tracking-tight text-slate-50 sm:text-2xl">Run the full recovery system—not a scripted demo.</h1><p className="mt-2 text-sm leading-6 text-slate-400">Autopilot drives real pending cases through detection, diagnosis, expected-value selection, policy enforcement, execution, verification, and audit. Returned outcomes are revealed progressively for the demo, but never invented in the browser.</p></div><div className="w-full max-w-sm rounded-xl border border-white/[0.07] bg-ink-900/50 p-4"><label className="block"><span className="text-[0.64rem] font-semibold uppercase tracking-[0.12em] text-slate-500">Batch limit</span><input className="mt-2 h-10 w-full rounded-lg border border-white/[0.08] bg-ink-800 px-3 font-mono text-sm text-slate-100 outline-none focus:border-accent focus:ring-2 focus:ring-accent/20" min="1" max="200" placeholder="All pending cases" type="number" value={limitInput} onChange={(event) => setLimitInput(event.target.value)} /></label>{!validLimit ? <p className="mt-2 flex items-center gap-1.5 text-xs text-red-300"><CircleAlert aria-hidden="true" className="size-3.5" />Enter a whole number from 1 to 200.</p> : <p className="mt-2 text-xs leading-5 text-slate-500">Leave blank to process every pending synthetic case.</p>}<Button className="mt-4 w-full" disabled={!validLimit} loading={batch.loading} onClick={handleRun}><Play aria-hidden="true" className="size-4" />Run Autopilot</Button></div></div>
      </Card>
      {batch.error ? <ErrorState compact error={batch.error} title="Autopilot batch could not run" /> : null}
      {batch.data ? <BatchResult revealedCount={revealedCount} result={batch.data} /> : null}
      {scenarios.data ? <ScenarioDeck scenarios={scenarios.data} /> : null}
      {scenarios.error && scenarios.data ? <ErrorState compact error={scenarios.error} onRetry={scenarios.refetch} title="Scenario refresh failed" /> : null}
      <Card className="border-white/[0.06] bg-ink-900/40 p-5"><div className="flex gap-3"><div className="grid size-9 shrink-0 place-items-center rounded-lg border border-accent/20 bg-accent/10 text-accent"><ShieldCheck aria-hidden="true" className="size-4" /></div><div><p className="text-sm font-semibold text-slate-100">Automation is bounded by policy</p><p className="mt-1 text-sm leading-6 text-slate-400">A high-value case can escalate without execution, and exhausted recovery budget can stop a case without another automatic action. Those outcomes are surfaced as real policy evidence in every result card.</p></div></div></Card>
    </div>
  );
}
