import { useState } from 'react';
import { Bot, ShieldCheck, Zap } from 'lucide-react';
import { getScenarios, runAutopilot } from '@/api';
import type { AutopilotResponse } from '@/types/api';
import {
  Accordion,
  Button,
  Card,
  CardHeader,
  ErrorState,
  MetricCard,
  Skeleton,
  StatusBadge,
} from '@/components/ui';
import { useApi, useAsyncAction } from '@/hooks/useApi';
import { formatMoney, formatPercent, humanize } from '@/utils/format';

export function AutopilotPage() {
  const scenariosQuery = useApi(getScenarios, []);
  const [batchResult, setBatchResult] = useState<AutopilotResponse | null>(null);

  const autopilotAction = useAsyncAction(async () => {
    const res = await runAutopilot({ limit: 12 });
    setBatchResult(res);
    await scenariosQuery.refetch();
  });

  if (scenariosQuery.loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-28 w-full rounded-xl" />
        <Skeleton className="h-96 w-full rounded-xl" />
      </div>
    );
  }

  if (scenariosQuery.error) {
    return (
      <ErrorState
        error={scenariosQuery.error}
        onRetry={() => void scenariosQuery.refetch()}
      />
    );
  }

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <Card className="p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <StatusBadge tone="info">AUTONOMOUS BATCH WORKFLOW</StatusBadge>
              <StatusBadge tone="success">VIRTUAL CLOCK CONTROLLED</StatusBadge>
            </div>
            <h1 className="mt-2 text-2xl font-bold text-slate-50">Autopilot Batch Engine</h1>
            <p className="mt-1 text-sm text-slate-300">
              Drives pending cases to terminal states by advancing simulation time and processing eligible retries.
            </p>
          </div>
          <Button
            loading={autopilotAction.loading}
            onClick={() => void autopilotAction.run()}
          >
            <Zap aria-hidden="true" className="size-4" /> Run Autopilot Batch
          </Button>
        </div>
      </Card>

      {/* Batch Results Summary (if executed) */}
      {batchResult ? (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard
              subtext={`${batchResult.cases_recovered} case(s) recovered`}
              title="Processed Cases"
              tone="sky"
              value={`${batchResult.total_cases}`}
            />

            <MetricCard
              subtext={`Recovery rate: ${formatPercent(batchResult.recovery_rate)}`}
              title="Total Recovered"
              tone="emerald"
              value={`${formatMoney(batchResult.total_recovered.amount, true)} INR`}
            />

            <MetricCard
              subtext="Gated by PolicyEngine"
              title="Policy Blocks"
              tone="rose"
              value={`${batchResult.actions_blocked}`}
            />

            <MetricCard
              subtext="Required human intervention"
              title="Escalations"
              tone="indigo"
              value={`${batchResult.cases_escalated}`}
            />
          </div>

          {/* Batch Case Results */}
          <Card className="p-6">
            <CardHeader className="px-0 pt-0 mb-4">
              <div>
                <h2 className="text-base font-semibold text-slate-100">Batch Case Execution Results</h2>
                <p className="text-xs text-slate-400">Detailed workflow outcomes for each processed case</p>
              </div>
              <ShieldCheck className="size-5 text-emerald-400" />
            </CardHeader>

            <div className="space-y-4">
              {batchResult.results.map((res) => (
                <div key={res.case_id} className="rounded-xl border border-white/[0.06] bg-slate-900/60 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-bold text-sky-400">{res.case_id}</span>
                      <StatusBadge tone={res.recovered ? 'success' : 'neutral'}>{res.final_state}</StatusBadge>
                      <StatusBadge tone={res.policy_outcome === 'APPROVED' ? 'info' : 'danger'}>
                        {res.policy_outcome || 'PENDING'}
                      </StatusBadge>
                    </div>
                    <span className="font-mono text-sm font-bold text-emerald-400">
                      {formatMoney(res.recovered_amount.amount, true)} INR
                    </span>
                  </div>

                  <p className="mt-2 text-xs text-slate-300">{res.explanation}</p>

                  <div className="mt-3 flex flex-wrap items-center gap-4 text-[0.7rem] font-mono text-slate-400">
                    <span>Cause: {humanize(res.failure_reason)}</span>
                    <span>Method: {humanize(res.payment_method)}</span>
                    <span>Action: {res.selected_action ?? 'NONE'}</span>
                    <span>Runs: {res.runs}</span>
                  </div>

                  <Accordion title="View Detailed Step Progression">
                    <ol className="space-y-2 font-mono text-[0.68rem]">
                      {res.steps.map((st) => (
                        <li key={st.run_index} className="rounded bg-black/40 p-2">
                          Run {st.run_index}: {st.state} → Action: {st.selected_action} | Verdict: {st.policy_outcome} | Status: {st.execution_status}
                        </li>
                      ))}
                    </ol>
                  </Accordion>
                </div>
              ))}
            </div>
          </Card>
        </div>
      ) : null}

      {/* Scenarios Listing */}
      {scenariosQuery.data ? (
        <Card className="p-6">
          <CardHeader className="px-0 pt-0 mb-4">
            <div>
              <h2 className="text-base font-semibold text-slate-100">Seeded Demo Scenarios</h2>
              <p className="text-xs text-slate-400">Deterministic scenarios A–D available for batch execution</p>
            </div>
            <Bot className="size-5 text-sky-400" />
          </CardHeader>

          <div className="grid gap-4 sm:grid-cols-2">
            {scenariosQuery.data.scenarios.map((sc) => (
              <div key={sc.key} className="rounded-xl border border-white/[0.06] bg-slate-900/60 p-4">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs font-bold text-sky-400">Scenario {sc.key}</span>
                  <StatusBadge tone={sc.current_state === 'RECOVERED' ? 'success' : 'neutral'}>
                    {sc.current_state}
                  </StatusBadge>
                </div>
                <h3 className="mt-2 text-sm font-semibold text-slate-100">{sc.title}</h3>
                <p className="mt-1 text-xs text-slate-400">{sc.narrative}</p>
                <div className="mt-3 flex items-center justify-between text-xs font-mono text-slate-300">
                  <span>At Risk: {formatMoney(sc.amount.amount, true)} INR</span>
                  <span>Expected: {sc.expected_action}</span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      ) : null}
    </div>
  );
}
