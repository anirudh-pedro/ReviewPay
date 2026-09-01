import { useMemo } from 'react';
import {
  ArrowLeft,
  BadgeCheck,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Clock3,
  GitBranch,
  Play,
  ShieldCheck,
  Sparkles,
  WalletCards,
} from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { getCaseIntelligence, getRecoveryIntelligence, runCase } from '@/api';
import {
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  Skeleton,
  StatusBadge,
  buttonClassName,
  cx,
} from '@/components/ui';
import { AuditTimeline } from '@/components/AuditTimeline';
import { RecoveryIntelligencePanel } from '@/components/RecoveryIntelligencePanel';
import { useApi, useAsyncAction } from '@/hooks/useApi';
import { useDemoData } from '@/contexts/DemoDataContext';
import type {
  PolicyOutcome,
  RecoveryActionRead,
  RecoveryCaseDetail,
  WorkflowRunResponse,
} from '@/types/api';
import {
  formatDateTime,
  formatMoney,
  formatPercent,
  humanize,
} from '@/utils/format';
import {
  caseStateTone,
  executionStatusTone,
  policyOutcomeTone,
  riskLevelTone,
} from '@/utils/recoveryPresentation';

interface PolicyEvidence {
  outcome: PolicyOutcome | null;
  ruleId: string | null;
  reason: string | null;
}

function policyEvidence(recoveryCase: RecoveryCaseDetail): PolicyEvidence {
  if (recoveryCase.latest_policy) {
    return {
      outcome: recoveryCase.latest_policy.outcome,
      ruleId: recoveryCase.latest_policy.rule_id,
      reason: recoveryCase.latest_policy.reason,
    };
  }

  const action = recoveryCase.latest_action;
  return {
    outcome: action?.policy_outcome ?? null,
    ruleId: action?.policy_rule_id ?? null,
    reason: action?.policy_reason ?? null,
  };
}

function DetailSkeleton() {
  return (
    <div aria-busy="true" className="space-y-5" role="status">
      <span className="sr-only">Loading case intelligence.</span>
      <Card className="surface-grid p-5 sm:p-6">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="mt-5 h-8 w-[min(30rem,80%)]" />
        <Skeleton className="mt-3 h-4 w-full max-w-xl" />
        <div className="mt-6 grid gap-3 sm:grid-cols-3"><Skeleton className="h-20" /><Skeleton className="h-20" /><Skeleton className="h-20" /></div>
      </Card>
      <div className="grid gap-5 xl:grid-cols-[1.4fr_0.9fr]">
        <Card className="p-5"><Skeleton className="h-4 w-40" /><Skeleton className="mt-5 h-72 w-full" /></Card>
        <Card className="p-5"><Skeleton className="h-4 w-36" /><Skeleton className="mt-5 h-72 w-full" /></Card>
      </div>
    </div>
  );
}

function EvidenceMetric({ label, value, tone = 'text-slate-100' }: { label: string; value: React.ReactNode; tone?: string }) {
  return (
    <div className="rounded-lg border border-white/[0.06] bg-ink-900/45 p-3.5">
      <p className="text-[0.63rem] font-semibold uppercase tracking-[0.12em] text-slate-500">{label}</p>
      <div className={cx('mt-2 text-sm font-semibold', tone)}>{value}</div>
    </div>
  );
}

function ProcessSummary({ recoveryCase }: { recoveryCase: RecoveryCaseDetail }) {
  const action = recoveryCase.latest_action;
  const explanation = recoveryCase.latest_explanation;
  const policy = policyEvidence(recoveryCase);
  const candidateCount = explanation ? explanation.alternatives.length + 1 : null;
  const outcome = recoveryCase.latest_outcome;

  const stages = [
    {
      label: 'Failure',
      value: recoveryCase.diagnosis?.failure_reason ? humanize(recoveryCase.diagnosis.failure_reason) : 'Pending diagnosis',
      tone: 'text-amber-200',
    },
    {
      label: 'Diagnosis',
      value: recoveryCase.diagnosis ? humanize(recoveryCase.diagnosis.category) : 'Not recorded',
      tone: 'text-slate-100',
    },
    {
      label: 'Candidates',
      value: candidateCount === null ? 'Not evaluated' : `${candidateCount} evaluated`,
      tone: 'text-slate-100',
    },
    {
      label: 'Probability',
      value: explanation ? formatPercent(explanation.probability) : 'Not recorded',
      tone: 'text-sky-200',
    },
    {
      label: 'ERV',
      value: explanation ? formatMoney(explanation.expected_recovery_value) : 'Not recorded',
      tone: 'text-sky-200',
    },
    {
      label: 'Ranking',
      value: explanation ? humanize(explanation.selected_action) : 'Not selected',
      tone: 'text-slate-100',
    },
    {
      label: 'Policy',
      value: policy.outcome ? humanize(policy.outcome) : 'Pending',
      tone: policy.outcome === 'APPROVED' ? 'text-green-200' : policy.outcome === 'BLOCKED' ? 'text-red-200' : policy.outcome === 'ESCALATED' ? 'text-violet-200' : 'text-slate-500',
    },
    {
      label: 'Execution',
      value: action?.status ? humanize(action.status) : 'Not executed',
      tone: action?.status === 'EXECUTED' ? 'text-green-200' : 'text-slate-400',
    },
    {
      label: 'Verification',
      value: outcome ? (outcome.recovered ? 'Recovered' : humanize(outcome.new_payment_status)) : 'Awaiting proof',
      tone: outcome?.recovered ? 'text-green-200' : 'text-slate-400',
    },
  ];

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <div>
          <div className="flex items-center gap-2"><GitBranch aria-hidden="true" className="size-4 text-accent" /><p className="text-sm font-semibold text-slate-100">Decision chain</p></div>
          <p className="mt-1 text-xs leading-5 text-slate-500">The recorded path from payment failure to independently verified outcome.</p>
        </div>
        <StatusBadge tone="info">Backend evidence</StatusBadge>
      </CardHeader>
      <div className="overflow-x-auto px-5 pb-5 pt-5">
        <ol aria-label="Recovery decision chain" className="flex min-w-max gap-2">
          {stages.map((stage, index) => (
            <li key={stage.label} className="flex items-stretch gap-2">
              <div className="w-32 rounded-lg border border-white/[0.06] bg-ink-900/45 p-3">
                <p className="font-mono text-[0.62rem] text-slate-600">{String(index + 1).padStart(2, '0')}</p>
                <p className="mt-1 text-[0.67rem] font-semibold uppercase tracking-[0.1em] text-slate-500">{stage.label}</p>
                <p className={cx('mt-2 text-xs font-semibold leading-5', stage.tone)}>{stage.value}</p>
              </div>
              {index < stages.length - 1 ? <ChevronRight aria-hidden="true" className="mt-8 size-3.5 shrink-0 text-slate-600" /> : null}
            </li>
          ))}
        </ol>
      </div>
    </Card>
  );
}

function EconomicDecision({ recoveryCase }: { recoveryCase: RecoveryCaseDetail }) {
  const action = recoveryCase.latest_action;
  const explanation = recoveryCase.latest_explanation;
  const erv = action?.erv_breakdown;
  const ervRows = [
    ['Payment amount', erv?.payment_amount],
    ['Gross expected recovery', erv?.gross_expected_recovery],
    ['Intervention cost', erv?.intervention_cost],
    ['Customer friction', erv?.customer_friction_penalty],
    ['Expected recovery value', erv?.expected_recovery_value],
  ].filter((entry): entry is [string, number] => typeof entry[1] === 'number');

  if (!action && !explanation) {
    return (
      <Card>
        <CardHeader><div><p className="text-sm font-semibold text-slate-100">Economic decision evidence</p><p className="mt-1 text-xs text-slate-500">The decision engine has not recorded a selected strategy yet.</p></div></CardHeader>
        <EmptyState compact description="Run one recovery cycle when the case is ready to obtain backend-generated candidates, probability, ERV, and policy evidence." icon={Sparkles} title="No decision recorded" />
      </Card>
    );
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <div>
          <div className="flex items-center gap-2"><Sparkles aria-hidden="true" className="size-4 text-accent" /><p className="text-sm font-semibold text-slate-100">Why this strategy was selected</p></div>
          <p className="mt-1 text-xs leading-5 text-slate-500">Probability and ERV are computed by the backend; the browser only presents the recorded explanation.</p>
        </div>
        {action ? <StatusBadge tone={riskLevelTone(action.risk_level)}>{humanize(action.risk_level)} risk</StatusBadge> : null}
      </CardHeader>
      <div className="space-y-5 p-5">
        {explanation ? (
          <div className="rounded-xl border border-accent/20 bg-accent/[0.055] p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-[0.66rem] font-semibold uppercase tracking-[0.12em] text-sky-300">Selected strategy</p>
                <p className="mt-1 text-lg font-semibold text-slate-50">{humanize(explanation.selected_action)}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <StatusBadge tone="info">{formatPercent(explanation.probability)} probability</StatusBadge>
                <StatusBadge tone="info">{formatMoney(explanation.expected_recovery_value)} ERV</StatusBadge>
                <StatusBadge tone="neutral">{formatPercent(explanation.confidence)} confidence</StatusBadge>
              </div>
            </div>
            <p className="mt-4 text-sm leading-6 text-slate-300">{explanation.reason}</p>
          </div>
        ) : null}

        {ervRows.length > 0 ? (
          <section>
            <p className="text-[0.67rem] font-semibold uppercase tracking-[0.12em] text-slate-500">Recorded ERV breakdown</p>
            <dl className="mt-3 grid gap-2 sm:grid-cols-2">
              {ervRows.map(([label, amount]) => (
                <div key={label} className="flex items-center justify-between gap-3 rounded-lg border border-white/[0.055] bg-ink-900/45 px-3 py-2.5">
                  <dt className="text-xs text-slate-500">{label}</dt>
                  <dd className="font-mono text-xs font-semibold tabular-nums text-slate-200">{formatMoney(amount)}</dd>
                </div>
              ))}
            </dl>
          </section>
        ) : null}

        {explanation?.alternatives.length ? (
          <section>
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div><p className="text-[0.67rem] font-semibold uppercase tracking-[0.12em] text-slate-500">Evaluated alternatives</p><p className="mt-1 text-xs leading-5 text-slate-500">These server-evaluated options were not selected. The recorded selection reason above is the authoritative rationale; the backend does not fabricate a separate rejection narrative per row.</p></div>
            </div>
            <div className="mt-3 overflow-x-auto rounded-lg border border-white/[0.055]">
              <table className="w-full min-w-[420px] text-left text-xs"><thead className="bg-white/[0.025] text-[0.63rem] uppercase tracking-[0.1em] text-slate-500"><tr><th className="px-3 py-2.5">Strategy</th><th className="px-3 py-2.5">Probability</th><th className="px-3 py-2.5">ERV</th><th className="px-3 py-2.5">Decision</th></tr></thead><tbody className="divide-y divide-white/[0.05]">{explanation.alternatives.map((alternative) => <tr key={alternative.action}><td className="px-3 py-3 font-medium text-slate-200">{humanize(alternative.action)}</td><td className="px-3 py-3 font-mono tabular-nums text-slate-300">{formatPercent(alternative.probability)}</td><td className="px-3 py-3 font-mono tabular-nums text-slate-300">{formatMoney(alternative.expected_recovery_value)}</td><td className="px-3 py-3 text-slate-500">Not selected</td></tr>)}</tbody></table>
            </div>
          </section>
        ) : null}
      </div>
    </Card>
  );
}

function PolicyExecutionVerification({ recoveryCase }: { recoveryCase: RecoveryCaseDetail }) {
  const action = recoveryCase.latest_action;
  const policy = policyEvidence(recoveryCase);
  const outcome = recoveryCase.latest_outcome;

  return (
    <div className="grid gap-5 xl:grid-cols-3">
      <Card>
        <CardHeader><div><div className="flex items-center gap-2"><ShieldCheck aria-hidden="true" className="size-4 text-accent" /><p className="text-sm font-semibold text-slate-100">Policy gate</p></div><p className="mt-1 text-xs text-slate-500">The backend decides whether automation is permitted.</p></div></CardHeader>
        <div className="p-5 pt-4">
          {policy.outcome ? <StatusBadge tone={policyOutcomeTone(policy.outcome)}>{humanize(policy.outcome)}</StatusBadge> : <StatusBadge tone="neutral">Not evaluated</StatusBadge>}
          {policy.ruleId ? <p className="mt-4 font-mono text-xs text-sky-300">{policy.ruleId}</p> : null}
          <p className="mt-2 text-sm leading-6 text-slate-300">{policy.reason ?? 'No policy verdict has been persisted for the latest action.'}</p>
        </div>
      </Card>
      <Card>
        <CardHeader><div><div className="flex items-center gap-2"><Clock3 aria-hidden="true" className="size-4 text-accent" /><p className="text-sm font-semibold text-slate-100">Execution</p></div><p className="mt-1 text-xs text-slate-500">Executor reporting is separate from proof of recovery.</p></div></CardHeader>
        <div className="p-5 pt-4">
          {action ? <><StatusBadge tone={executionStatusTone(action.status)}>{humanize(action.status)}</StatusBadge><p className="mt-4 text-sm font-medium text-slate-200">{humanize(action.action_type)}</p><p className="mt-1 text-xs leading-5 text-slate-500">{action.executed_at ? `Executed ${formatDateTime(action.executed_at)}` : action.scheduled_at ? `Scheduled ${formatDateTime(action.scheduled_at)}` : 'No executor timestamp has been recorded.'}</p>{action.requires_human_approval ? <p className="mt-3 text-xs leading-5 text-violet-300">Human approval is required before this action can proceed.</p> : null}</> : <p className="text-sm leading-6 text-slate-500">No action record has been persisted.</p>}
        </div>
      </Card>
      <Card>
        <CardHeader><div><div className="flex items-center gap-2"><BadgeCheck aria-hidden="true" className="size-4 text-accent" /><p className="text-sm font-semibold text-slate-100">Independent verification</p></div><p className="mt-1 text-xs text-slate-500">Recovery is confirmed from persisted payment state.</p></div></CardHeader>
        <div className="p-5 pt-4">
          {outcome ? <><StatusBadge tone={outcome.recovered ? 'success' : 'neutral'}>{outcome.recovered ? 'Recovered' : humanize(outcome.new_payment_status)}</StatusBadge><p className={cx('mt-4 font-mono text-lg font-semibold tabular-nums', outcome.recovered ? 'text-green-300' : 'text-slate-300')}>{formatMoney(outcome.recovered_amount)}</p><p className="mt-1 text-xs leading-5 text-slate-500">{humanize(outcome.previous_payment_status)} → {humanize(outcome.new_payment_status)} · verified {formatDateTime(outcome.verification_timestamp)}</p></> : <p className="text-sm leading-6 text-slate-500">No independently verified payment outcome is available yet.</p>}
        </div>
      </Card>
    </div>
  );
}

function ActionHistory({ actions }: { actions: RecoveryActionRead[] }) {
  if (actions.length === 0) return null;

  return (
    <Card className="overflow-hidden">
      <CardHeader><div><p className="text-sm font-semibold text-slate-100">Persisted action history</p><p className="mt-1 text-xs text-slate-500">Every action record keeps its model, expected value, and policy outcome.</p></div><StatusBadge tone="neutral">{actions.length} actions</StatusBadge></CardHeader>
      <div className="overflow-x-auto px-5 pb-5 pt-5"><table className="w-full min-w-[720px] text-left text-xs"><thead className="border-y border-white/[0.055] bg-white/[0.018] uppercase tracking-[0.1em] text-slate-500"><tr><th className="px-3 py-2.5">Action</th><th className="px-3 py-2.5">Probability</th><th className="px-3 py-2.5">ERV</th><th className="px-3 py-2.5">Policy</th><th className="px-3 py-2.5">Record status</th><th className="px-3 py-2.5">Model</th></tr></thead><tbody className="divide-y divide-white/[0.05]">{actions.map((action) => <tr key={action.action_id}><td className="px-3 py-3 font-medium text-slate-200">{humanize(action.action_type)}</td><td className="px-3 py-3 font-mono tabular-nums text-slate-300">{formatPercent(action.estimated_probability)}</td><td className="px-3 py-3 font-mono tabular-nums text-slate-300">{formatMoney(action.expected_recovery_value)}</td><td className="px-3 py-3">{action.policy_outcome ? <StatusBadge tone={policyOutcomeTone(action.policy_outcome)}>{humanize(action.policy_outcome)}</StatusBadge> : <span className="text-slate-600">—</span>}</td><td className="px-3 py-3 text-slate-400">{humanize(action.status)}</td><td className="px-3 py-3 font-mono text-[0.67rem] text-slate-500">{action.model_version}</td></tr>)}</tbody></table></div>
    </Card>
  );
}

function WorkflowResult({ result }: { result: WorkflowRunResponse | null }) {
  if (!result) return null;

  const completed = new Set(result.stages);
  const liveStages = [
    ['DETECT', true, 'Case entered the existing workflow.'],
    ['DIAGNOSE', completed.has('diagnosis'), 'Structured failure diagnosis persisted.'],
    ['PREDICT', completed.has('decision'), 'Configured predictor scored the candidates.'],
    ['EVALUATE', completed.has('candidates'), 'Candidate actions were valued by ERV.'],
    ['DECIDE', completed.has('decision'), 'Highest ranked strategy was selected.'],
    ['POLICY', completed.has('policy'), 'Mandatory policy verdict was recorded.'],
    ['EXECUTE', completed.has('execution'), 'Executor was invoked only after approval.'],
    ['VERIFY', completed.has('verification'), 'Persisted payment state was independently checked.'],
  ] as const;

  return (
    <Card className="border-accent/20 bg-accent/[0.035]">
      <CardHeader><div><div className="flex items-center gap-2"><CheckCircle2 aria-hidden="true" className="size-4 text-accent" /><p className="text-sm font-semibold text-slate-100">Run AI Recovery — workflow evidence</p></div><p className="mt-1 text-xs text-slate-500">A visual presentation of the real, policy-gated workflow response. No stage is invented or executed by the browser.</p></div><StatusBadge tone={caseStateTone(result.final_status)}>{humanize(result.final_status)}</StatusBadge></CardHeader>
      <div className="overflow-x-auto px-5 pt-4"><ol aria-label="Run AI Recovery stages" className="flex min-w-max gap-2 pb-1">{liveStages.map(([label, complete, evidence], index) => <li key={label} className="flex items-stretch gap-2"><div className={cx('w-32 rounded-lg border p-3', complete ? 'border-accent/25 bg-accent/[0.055]' : 'border-white/[0.06] bg-ink-900/35')}><p className="font-mono text-[0.62rem] text-slate-600">{String(index + 1).padStart(2, '0')}</p><p className={cx('mt-1 text-xs font-semibold', complete ? 'text-sky-200' : 'text-slate-500')}>{label}</p><p className="mt-2 text-[0.65rem] leading-4 text-slate-500">{complete ? evidence : 'Not reached in this cycle.'}</p></div>{index < liveStages.length - 1 ? <ChevronRight aria-hidden="true" className="mt-8 size-3.5 shrink-0 text-slate-600" /> : null}</li>)}</ol></div>
      <div className="grid gap-3 p-5 pt-4 md:grid-cols-4"><EvidenceMetric label="Selected action" value={result.selected_action ? humanize(result.selected_action) : 'None'} /><EvidenceMetric label="Policy" value={result.policy ? humanize(result.policy.outcome) : 'Not recorded'} /><EvidenceMetric label="Recovered" tone={result.outcome?.recovered ? 'text-green-300' : 'text-slate-100'} value={formatMoney(result.recovered_amount)} /><EvidenceMetric label="Recorded stages" value={String(result.stages.length)} /></div>
      <p className="px-5 pb-5 text-sm leading-6 text-slate-300">{result.message}</p>
    </Card>
  );
}

function CaseDetailContent({ caseId }: { caseId: string }) {
  const { dataVersion, refreshLiveData } = useDemoData();
  const intelligence = useApi((signal) => getCaseIntelligence(caseId, signal), [caseId, dataVersion]);
  const recoveryIntelligence = useApi(
    (signal) => getRecoveryIntelligence(caseId, signal),
    [caseId, dataVersion],
  );
  const runWorkflow = useAsyncAction(runCase);
  const data = intelligence.data;

  const actionLabel = useMemo(() => {
    if (!data) return 'Run AI Recovery';
    if (data.recoveryCase.is_terminal) return 'Terminal case';
    if (data.recoveryCase.state === 'SCHEDULED') return 'Run AI Recovery (due cycle)';
    return 'Run AI Recovery';
  }, [data]);

  async function handleRun() {
    try {
      await runWorkflow.run(caseId);
      refreshLiveData();
    } catch {
      // The shared action state keeps the central ApiError for an explicit UI state below.
    }
  }

  if (intelligence.loading && !data) return <DetailSkeleton />;
  if (intelligence.error && !data) return <ErrorState error={intelligence.error} onRetry={intelligence.refetch} title="Case intelligence is unavailable" />;
  if (!data) return <ErrorState error="No valid case intelligence response was received." onRetry={intelligence.refetch} title="Case intelligence could not be read" />;

  const { recoveryCase, payment, audit } = data;
  const terminal = recoveryCase.is_terminal;

  return (
    <div className="space-y-5">
      <Link className={buttonClassName('ghost', 'sm', '-ml-2')} to="/cases"><ArrowLeft aria-hidden="true" className="size-3.5" />Back to Case Explorer</Link>

      <Card className="surface-grid overflow-hidden p-5 sm:p-6">
        <div className="flex flex-col justify-between gap-6 xl:flex-row xl:items-start">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2"><StatusBadge tone={caseStateTone(recoveryCase.state)}>{humanize(recoveryCase.state)}</StatusBadge>{recoveryCase.is_terminal ? <StatusBadge tone="neutral">Terminal</StatusBadge> : <StatusBadge tone="info">Workflow ready</StatusBadge>}</div>
            <h1 className="mt-4 font-mono text-xl font-semibold tracking-tight text-slate-50 sm:text-2xl">{recoveryCase.case_id}</h1>
            <p className="mt-2 text-sm text-slate-400">Payment <span className="font-mono text-slate-300">{recoveryCase.payment_id}</span> · customer <span className="font-mono text-slate-300">{payment.customer_id}</span></p>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">Inspect the exact backend evidence for diagnosis, economic selection, policy enforcement, execution, and independent verification.</p>
          </div>
          <div className="flex flex-col items-stretch gap-2 sm:flex-row xl:flex-col">
            <Button disabled={terminal} loading={runWorkflow.loading} onClick={handleRun}><Play aria-hidden="true" className="size-4" />{actionLabel}</Button>
            <p className="max-w-64 text-xs leading-5 text-slate-500">Runs one real synthetic workflow cycle. Terminal cases cannot be changed.</p>
          </div>
        </div>
        <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><EvidenceMetric label="Revenue at risk" tone="text-amber-100" value={formatMoney(recoveryCase.amount_at_risk)} /><EvidenceMetric label="Payment method" value={humanize(payment.payment_method)} /><EvidenceMetric label="Payment attempts" value={String(payment.attempt_count)} /><EvidenceMetric label="Updated" value={formatDateTime(recoveryCase.updated_at)} /></div>
      </Card>

      {intelligence.error ? <div className="rounded-xl border border-atrisk/20 bg-atrisk/[0.04] px-4 py-3 text-xs leading-5 text-amber-200">The latest refresh failed; previously loaded evidence remains visible. <button className="ml-1 font-semibold underline decoration-amber-300/40 underline-offset-2" type="button" onClick={intelligence.refetch}>Retry</button></div> : null}
      {runWorkflow.error ? <ErrorState compact error={runWorkflow.error} title="Recovery cycle could not run" /> : null}
      <WorkflowResult result={runWorkflow.data} />

      {recoveryIntelligence.loading && !recoveryIntelligence.data ? (
        <Card className="p-5" aria-busy="true">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="mt-4 h-28 w-full" />
        </Card>
      ) : null}
      {recoveryIntelligence.data ? <RecoveryIntelligencePanel intelligence={recoveryIntelligence.data} /> : null}
      {recoveryIntelligence.error && !recoveryIntelligence.data ? (
        <ErrorState
          compact
          error={recoveryIntelligence.error}
          onRetry={recoveryIntelligence.refetch}
          title="Recovery Intelligence is unavailable"
        />
      ) : null}
      {recoveryIntelligence.error && recoveryIntelligence.data ? (
        <div className="rounded-xl border border-atrisk/20 bg-atrisk/[0.04] px-4 py-3 text-xs leading-5 text-amber-200">
          The latest Recovery Intelligence refresh failed; previously loaded advisory evidence remains visible.
          <button className="ml-1 font-semibold underline decoration-amber-300/40 underline-offset-2" type="button" onClick={recoveryIntelligence.refetch}>Retry</button>
        </div>
      ) : null}

      <ProcessSummary recoveryCase={recoveryCase} />
      <div className="grid gap-5 xl:grid-cols-[1.35fr_0.9fr]"><EconomicDecision recoveryCase={recoveryCase} /><Card><CardHeader><div><div className="flex items-center gap-2"><WalletCards aria-hidden="true" className="size-4 text-accent" /><p className="text-sm font-semibold text-slate-100">Failure & customer payment context</p></div><p className="mt-1 text-xs text-slate-500">Persisted payment facts used by the recovery workflow.</p></div></CardHeader><div className="space-y-4 p-5 pt-4"><EvidenceMetric label="Failure reason" value={payment.failure_reason ? humanize(payment.failure_reason) : 'Not recorded'} /><EvidenceMetric label="Diagnosis" value={recoveryCase.diagnosis ? humanize(recoveryCase.diagnosis.category) : 'Not complete'} /><div className="rounded-lg border border-white/[0.06] bg-ink-900/45 p-3.5"><p className="text-[0.63rem] font-semibold uppercase tracking-[0.12em] text-slate-500">Diagnosis explanation</p><p className="mt-2 text-sm leading-6 text-slate-300">{recoveryCase.diagnosis?.explanation ?? 'The backend has not persisted a diagnosis for this case yet.'}</p></div></div></Card></div>
      <PolicyExecutionVerification recoveryCase={recoveryCase} />
      <ActionHistory actions={recoveryCase.actions} />
      <AuditTimeline key={recoveryCase.case_id} events={audit.events} />
    </div>
  );
}

export function CaseDetailPage() {
  const { caseId } = useParams<{ caseId: string }>();

  if (!caseId) {
    return <EmptyState description="A recovery case identifier is required to inspect decision evidence." icon={CircleAlert} title="Case not selected" />;
  }

  return <CaseDetailContent caseId={caseId} />;
}
