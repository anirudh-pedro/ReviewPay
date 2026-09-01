import { useEffect, useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  Beaker,
  CircleAlert,
  LineChart,
  SlidersHorizontal,
  Sparkles,
  Target,
} from 'lucide-react';
import { getBaselineComparison, getScenarios, simulateRecoveryIntelligence, simulateStrategies } from '@/api';
import type { ActionType, ScenarioOverrides, StrategyLabResponse, StrategyOption } from '@/types/api';
import { RecoveryIntelligencePanel } from '@/components/RecoveryIntelligencePanel';
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
import {
  formatMoney,
  formatMoneyCompact,
  formatPercent,
  formatPercentPoints,
  formatSignedPercent,
  humanize,
} from '@/utils/format';
import { policyOutcomeTone, riskLevelTone } from '@/utils/recoveryPresentation';

const OVERRIDABLE_ACTIONS: ActionType[] = [
  'RETRY_NOW',
  'RETRY_LATER',
  'SEND_PAYMENT_LINK',
  'CHANGE_PAYMENT_METHOD',
  'SEND_REMINDER',
];

interface OverrideForm {
  retryLaterDelay: string;
  maxAutomaticRetries: string;
  repeatedFailureLimit: string;
  highValueThreshold: string;
  action: ActionType;
  interventionCost: string;
  frictionPenalty: string;
}

const initialOverrides: OverrideForm = {
  retryLaterDelay: '',
  maxAutomaticRetries: '',
  repeatedFailureLimit: '',
  highValueThreshold: '',
  action: 'RETRY_LATER',
  interventionCost: '',
  frictionPenalty: '',
};

function parseOptionalInteger(value: string): number | undefined {
  const normalized = value.trim();
  return normalized ? Number(normalized) : undefined;
}

function isInvalidInteger(value: number | undefined): boolean {
  return value !== undefined && (!Number.isInteger(value) || value < 0);
}

function buildOverrides(form: OverrideForm): { invalid: boolean; overrides: ScenarioOverrides } {
  const retryLaterDelay = parseOptionalInteger(form.retryLaterDelay);
  const maxAutomaticRetries = parseOptionalInteger(form.maxAutomaticRetries);
  const repeatedFailureLimit = parseOptionalInteger(form.repeatedFailureLimit);
  const highValueThreshold = parseOptionalInteger(form.highValueThreshold);
  const interventionCost = parseOptionalInteger(form.interventionCost);
  const frictionPenalty = parseOptionalInteger(form.frictionPenalty);

  const values = [
    retryLaterDelay,
    maxAutomaticRetries,
    repeatedFailureLimit,
    highValueThreshold,
    interventionCost,
    frictionPenalty,
  ];

  if (values.some(isInvalidInteger)) return { invalid: true, overrides: {} };

  const overrides: ScenarioOverrides = {};
  if (retryLaterDelay !== undefined) overrides.retry_later_delay_minutes = retryLaterDelay;
  if (maxAutomaticRetries !== undefined) overrides.max_automatic_retries = maxAutomaticRetries;
  if (repeatedFailureLimit !== undefined) overrides.repeated_failure_limit = repeatedFailureLimit;
  if (highValueThreshold !== undefined) overrides.high_value_escalation_threshold = highValueThreshold;
  if (interventionCost !== undefined) overrides.intervention_cost_minor = { [form.action]: interventionCost };
  if (frictionPenalty !== undefined) overrides.friction_penalty_minor = { [form.action]: frictionPenalty };

  return { invalid: false, overrides };
}

function Metric({ label, value, tone = 'text-slate-100' }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-white/[0.06] bg-ink-900/45 p-3.5">
      <p className="text-[0.63rem] font-semibold uppercase tracking-[0.12em] text-slate-500">{label}</p>
      <p className={cx('metric-value mt-2 text-lg font-semibold', tone)}>{value}</p>
    </div>
  );
}

function LabSkeleton() {
  return (
    <div aria-busy="true" className="space-y-5" role="status">
      <span className="sr-only">Loading Strategy Lab data.</span>
      <Card className="surface-grid p-5 sm:p-6"><Skeleton className="h-4 w-32" /><Skeleton className="mt-4 h-8 w-[min(38rem,85%)]" /><Skeleton className="mt-3 h-4 w-full max-w-xl" /><div className="mt-6 grid gap-3 lg:grid-cols-3"><Skeleton className="h-10" /><Skeleton className="h-10" /><Skeleton className="h-10" /></div></Card>
      <div className="grid gap-5 xl:grid-cols-2"><Card className="p-5"><Skeleton className="h-5 w-40" /><Skeleton className="mt-5 h-60" /></Card><Card className="p-5"><Skeleton className="h-5 w-40" /><Skeleton className="mt-5 h-60" /></Card></div>
    </div>
  );
}

function NumberInput({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block min-w-0">
      <span className="block text-[0.64rem] font-semibold uppercase tracking-[0.11em] text-slate-500">{label}</span>
      <input
        className="mt-1.5 h-10 w-full rounded-lg border border-white/[0.08] bg-ink-900 px-3 font-mono text-sm text-slate-100 outline-none transition-colors placeholder:text-slate-600 focus:border-accent focus:ring-2 focus:ring-accent/20"
        min="0"
        placeholder="Use backend default"
        type="number"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
      <span className="mt-1 block text-[0.65rem] leading-4 text-slate-600">{hint}</span>
    </label>
  );
}

function StrategyOptionCard({ option }: { option: StrategyOption }) {
  return (
    <article
      className={cx(
        'relative overflow-hidden rounded-xl border bg-ink-850 p-5 shadow-card',
        option.is_recommended ? 'border-accent/35 bg-accent/[0.04]' : 'border-white/[0.06]',
      )}
    >
      {option.is_recommended ? <span aria-hidden="true" className="absolute inset-x-0 top-0 h-px bg-accent" /> : null}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-base font-semibold text-slate-50">{humanize(option.action)}</p>
            {option.is_recommended ? <StatusBadge tone="info">Recommended</StatusBadge> : null}
            {option.is_current ? <StatusBadge tone="neutral">Current</StatusBadge> : null}
          </div>
          <p className="mt-1 text-xs text-slate-500">{option.simulation_basis}</p>
        </div>
        <div className="flex flex-wrap gap-2"><StatusBadge tone={policyOutcomeTone(option.policy_outcome)}>{humanize(option.policy_outcome)}</StatusBadge><StatusBadge tone={riskLevelTone(option.risk_level)}>{humanize(option.risk_level)}</StatusBadge></div>
      </div>
      <div className="mt-5 grid gap-2 sm:grid-cols-2 xl:grid-cols-3"><Metric label="Success probability" tone="text-sky-200" value={formatPercent(option.probability)} /><Metric label="Expected recovery value" tone="text-green-300" value={formatMoney(option.expected_recovery_value)} /><Metric label="Gross expected recovery" value={formatMoney(option.gross_expected_recovery)} /><Metric label="Intervention cost" value={formatMoney(option.intervention_cost)} /><Metric label="Friction penalty" value={formatMoney(option.friction_penalty)} /><Metric label="Confidence" value={formatPercent(option.confidence)} /></div>
      <div className="mt-4 rounded-lg border border-white/[0.055] bg-ink-900/45 p-3"><p className="text-[0.63rem] font-semibold uppercase tracking-[0.1em] text-slate-500">Policy evidence</p><p className="mt-1 font-mono text-[0.67rem] text-sky-300">{option.policy_rule_id}</p><p className="mt-1.5 text-xs leading-5 text-slate-400">{option.policy_reason}</p></div>
      <div className="mt-4 flex flex-wrap gap-2 text-[0.68rem] text-slate-400"><span className={cx('rounded-full border px-2 py-1', option.eligible ? 'border-recovered/20 bg-recovered/[0.06] text-green-300' : 'border-white/[0.08] text-slate-500')}>{option.eligible ? 'Eligible' : 'Ineligible'}</span><span className={cx('rounded-full border px-2 py-1', option.is_candidate ? 'border-accent/20 bg-accent/[0.06] text-sky-300' : 'border-white/[0.08] text-slate-500')}>{option.is_candidate ? 'Candidate' : 'Not a candidate'}</span><span className={cx('rounded-full border px-2 py-1', option.simulated_would_succeed ? 'border-recovered/20 bg-recovered/[0.06] text-green-300' : 'border-blocked/20 bg-blocked/[0.04] text-red-300')}>{option.simulated_would_succeed ? 'Projected simulator success' : 'Projected simulator failure'}</span></div>
    </article>
  );
}

function StrategyResult({ result }: { result: StrategyLabResponse }) {
  return (
    <section className="space-y-5">
      <Card className="overflow-hidden border-accent/20 bg-accent/[0.035]">
        <CardHeader><div><div className="flex items-center gap-2"><Sparkles aria-hidden="true" className="size-4 text-accent" /><p className="text-sm font-semibold text-slate-100">Backend recommendation</p></div><p className="mt-1 text-xs leading-5 text-slate-500">The scorer, expected-value calculator, and policy engine all ran server-side for this read-only simulation.</p></div>{result.recommended_action ? <StatusBadge tone="info">{humanize(result.recommended_action)}</StatusBadge> : <StatusBadge tone="neutral">No recommendation</StatusBadge>}</CardHeader>
        <div className="grid gap-4 p-5 pt-4 lg:grid-cols-[1.2fr_0.8fr]"><div><p className="text-lg font-semibold text-slate-50">{result.recommendation_reason}</p><div className="mt-4 grid gap-3 sm:grid-cols-3"><Metric label="Payment amount" tone="text-amber-100" value={formatMoney(result.amount)} /><Metric label="Failure reason" value={humanize(result.failure_reason)} /><Metric label="Case state" value={humanize(result.case_state)} /></div></div><div className="rounded-xl border border-white/[0.06] bg-ink-900/45 p-4"><p className="text-[0.64rem] font-semibold uppercase tracking-[0.12em] text-slate-500">Customer context</p><dl className="mt-3 space-y-2 text-xs"><div className="flex justify-between gap-3"><dt className="text-slate-500">History</dt><dd className="text-slate-200">{result.customer.history_available ? 'Available' : 'Unavailable'}</dd></div><div className="flex justify-between gap-3"><dt className="text-slate-500">Success rate</dt><dd className="font-mono text-slate-200">{formatPercent(result.customer.success_rate)}</dd></div><div className="flex justify-between gap-3"><dt className="text-slate-500">Previous recovery attempts</dt><dd className="font-mono text-slate-200">{result.customer.previous_recovery_attempts}</dd></div><div className="flex justify-between gap-3"><dt className="text-slate-500">Subscription</dt><dd className="text-slate-200">{humanize(result.customer.subscription_status)}</dd></div></dl></div></div>
      </Card>
      <section><div className="mb-3 flex flex-wrap items-end justify-between gap-3"><div><p className="text-sm font-semibold text-slate-100">Server-evaluated strategies</p><p className="mt-1 text-xs leading-5 text-slate-500">Each option carries the backend’s probability, ERV, cost/friction, policy verdict, and deterministic simulator projection.</p></div><StatusBadge tone="info">{result.options.length} options</StatusBadge></div><div className="grid gap-4 xl:grid-cols-2">{result.options.map((option) => <StrategyOptionCard key={option.action} option={option} />)}</div></section>
      <Card><CardHeader><div><div className="flex items-center gap-2"><SlidersHorizontal aria-hidden="true" className="size-4 text-accent" /><p className="text-sm font-semibold text-slate-100">Effective server settings</p></div><p className="mt-1 text-xs text-slate-500">The backend returns the settings actually applied to this simulation.</p></div><StatusBadge tone={result.overrides_applied ? 'warning' : 'neutral'}>{result.overrides_applied ? 'Overrides applied' : 'Defaults used'}</StatusBadge></CardHeader><div className="flex flex-wrap gap-2 px-5 pb-5 pt-4">{Object.entries(result.effective_settings).map(([key, value]) => <span key={key} className="rounded-lg border border-white/[0.06] bg-ink-900/45 px-2.5 py-1.5 font-mono text-[0.67rem] text-slate-400">{key}: <span className="text-slate-200">{typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean' ? String(value) : JSON.stringify(value)}</span></span>)}</div></Card>
    </section>
  );
}

function ComparisonArm({
  arm,
  tone,
}: {
  arm: Awaited<ReturnType<typeof getBaselineComparison>>['baseline'];
  tone: 'baseline' | 'revivepay';
}) {
  const isRevivePay = tone === 'revivepay';
  return (
    <Card className={cx('overflow-hidden', isRevivePay ? 'border-accent/25 bg-accent/[0.03]' : '')}>
      <CardHeader><div><p className="text-sm font-semibold text-slate-100">{arm.strategy}</p><p className="mt-1 text-xs leading-5 text-slate-500">{arm.description}</p></div><StatusBadge tone={isRevivePay ? 'info' : 'neutral'}>{isRevivePay ? 'Intelligent selection' : 'Naive baseline'}</StatusBadge></CardHeader>
      <div className="grid gap-3 p-5 pt-4 sm:grid-cols-2"><Metric label="Projected recovered" tone={isRevivePay ? 'text-green-300' : 'text-slate-100'} value={formatMoney(arm.projected_recovered)} /><Metric label="Recovery rate" value={formatPercent(arm.projected_recovery_rate)} /><Metric label="Expected value" value={formatMoney(arm.expected_recovery_value)} /><Metric label="Projected recovered cases" value={String(arm.cases_projected_recovered)} /><Metric label="Policy-blocked cases" tone={isRevivePay ? 'text-red-300' : 'text-slate-100'} value={String(arm.cases_blocked)} /><Metric label="Escalated cases" tone="text-violet-300" value={String(arm.cases_escalated)} /></div>
      <div className="border-t border-white/[0.055] px-5 py-4"><p className="text-[0.63rem] font-semibold uppercase tracking-[0.1em] text-slate-500">Actions used by the backend simulation</p><div className="mt-2 flex flex-wrap gap-2">{Object.entries(arm.actions_used).map(([action, count]) => <StatusBadge key={action} tone="neutral">{humanize(action)} · {count}</StatusBadge>)}</div></div>
    </Card>
  );
}

function BaselineComparison() {
  const { dataVersion } = useDemoData();
  const comparison = useApi(getBaselineComparison, [dataVersion]);
  const chartData = useMemo(() => {
    if (!comparison.data) return [];
    return [
      { strategy: comparison.data.baseline.strategy, recovered: comparison.data.baseline.projected_recovered.amount },
      { strategy: comparison.data.revivepay.strategy, recovered: comparison.data.revivepay.projected_recovered.amount },
    ];
  }, [comparison.data]);

  if (comparison.loading && !comparison.data) {
    return <Card className="p-5"><Skeleton className="h-5 w-52" /><Skeleton className="mt-5 h-60 w-full" /></Card>;
  }
  if (comparison.error && !comparison.data) {
    return <ErrorState compact error={comparison.error} onRetry={comparison.refetch} title="Baseline comparison is unavailable" />;
  }
  if (!comparison.data) return null;

  const data = comparison.data;
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3"><div><div className="flex items-center gap-2"><LineChart aria-hidden="true" className="size-4 text-accent" /><p className="text-sm font-semibold text-slate-100">Baseline vs RevivePay</p></div><p className="mt-1 text-xs leading-5 text-slate-500">A deterministic benchmark on the same synthetic cases. Selection differs; recovery logic remains identical.</p></div><StatusBadge tone="info">{data.cases_evaluated} cases evaluated</StatusBadge></div>
      <Card className="overflow-hidden"><div className="grid gap-4 p-5 xl:grid-cols-[1.15fr_0.85fr]"><div className="grid gap-3 sm:grid-cols-2"><Metric label="Incremental recovered revenue" tone="text-green-300" value={formatMoney(data.recovered_uplift)} /><Metric label="Recovery-rate improvement" tone="text-sky-200" value={formatPercentPoints(data.recovery_rate_uplift_pct)} /><Metric label="Recovered revenue uplift" tone="text-green-300" value={formatSignedPercent(data.recovered_uplift_pct)} /><Metric label="Expected-value uplift" tone="text-sky-200" value={formatMoney(data.expected_value_uplift)} /></div><div className="h-52 min-w-0"><ResponsiveContainer height="100%" width="100%"><BarChart data={chartData} margin={{ top: 6, right: 0, bottom: 0, left: 0 }}><CartesianGrid stroke="rgba(148,163,184,0.09)" strokeDasharray="3 3" vertical={false} /><XAxis axisLine={false} dataKey="strategy" tick={{ fill: '#8b98ad', fontSize: 11 }} tickLine={false} /><YAxis axisLine={false} tick={{ fill: '#8b98ad', fontSize: 10 }} tickFormatter={(value: number) => formatMoneyCompact(value)} tickLine={false} width={58} /><Tooltip formatter={(value: number) => formatMoney(value)} cursor={{ fill: 'rgba(148,163,184,0.05)' }} /><Bar dataKey="recovered" fill="#38bdf8" name="Projected recovered" radius={[5, 5, 0, 0]} /></BarChart></ResponsiveContainer></div></div></Card>
      <div className="grid gap-5 xl:grid-cols-2"><ComparisonArm arm={data.baseline} tone="baseline" /><ComparisonArm arm={data.revivepay} tone="revivepay" /></div>
      {comparison.error ? <ErrorState compact error={comparison.error} onRetry={comparison.refetch} title="Baseline refresh failed" /> : null}
    </section>
  );
}

export function StrategyLabPage() {
  const { dataVersion, demoResetVersion } = useDemoData();
  const { notify } = useToast();
  const scenarios = useApi(getScenarios, [dataVersion]);
  const simulation = useAsyncAction(simulateStrategies);
  const intelligenceSimulation = useAsyncAction(simulateRecoveryIntelligence);
  const [selectedCaseId, setSelectedCaseId] = useState('');
  const [form, setForm] = useState<OverrideForm>(initialOverrides);
  const builtOverrides = useMemo(() => buildOverrides(form), [form]);
  const selectedScenario = scenarios.data?.scenarios.find((scenario) => scenario.case_id === selectedCaseId) ?? null;

  useEffect(() => {
    const firstScenario = scenarios.data?.scenarios[0];
    if (firstScenario && !scenarios.data?.scenarios.some((scenario) => scenario.case_id === selectedCaseId)) {
      setSelectedCaseId(firstScenario.case_id);
    }
  }, [scenarios.data, selectedCaseId]);

  useEffect(() => {
    simulation.reset();
    intelligenceSimulation.reset();
    // A reset replaces the deterministic data beneath the selected scenario.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [demoResetVersion]);

  async function handleEvaluate() {
    if (!selectedCaseId || builtOverrides.invalid) return;

    const [strategyResult, advisoryResult] = await Promise.allSettled([
      simulation.run(selectedCaseId, builtOverrides.overrides),
      intelligenceSimulation.run(selectedCaseId, builtOverrides.overrides),
    ]);

    if (strategyResult.status === 'fulfilled' && advisoryResult.status === 'fulfilled') {
      notify({
        tone: 'success',
        message: `Evaluated ${strategyResult.value.options.length} strategies and bounded intelligence evidence using the backend.`,
      });
    } else if (strategyResult.status === 'fulfilled') {
      notify({
        tone: 'success',
        message: `Evaluated ${strategyResult.value.options.length} strategies using the backend decision engine.`,
      });
    } else if (advisoryResult.status === 'fulfilled') {
      notify({ tone: 'success', message: 'Evaluated bounded Recovery Intelligence evidence using the backend.' });
    }
  }

  if (scenarios.loading && !scenarios.data) return <LabSkeleton />;
  if (scenarios.error && !scenarios.data) return <ErrorState error={scenarios.error} onRetry={scenarios.refetch} title="Strategy Lab scenarios are unavailable" />;

  return (
    <div className="space-y-6">
      <Card className="surface-grid overflow-hidden p-5 sm:p-6">
        <div className="flex flex-col justify-between gap-5 xl:flex-row xl:items-end"><div className="max-w-2xl"><div className="flex items-center gap-2"><span className="grid size-9 place-items-center rounded-xl border border-accent/25 bg-accent/10 text-accent"><Beaker aria-hidden="true" className="size-5" /></span><StatusBadge tone="info">Read-only what-if</StatusBadge></div><h1 className="mt-4 text-xl font-semibold tracking-tight text-slate-50 sm:text-2xl">Ask what would happen before you recover.</h1><p className="mt-2 text-sm leading-6 text-slate-400">Strategy Lab reuses the real scorer, ERV calculator, policy engine, and deterministic payment simulator. Override inputs are sent to the backend; this page does not calculate a recommendation.</p></div><div className="flex items-center gap-2 text-xs text-slate-500"><Target aria-hidden="true" className="size-3.5 text-accent" />No payment or case state is changed.</div></div>
        <div className="mt-7 grid gap-4 xl:grid-cols-[1.15fr_0.85fr]"><div className="rounded-xl border border-white/[0.06] bg-ink-900/45 p-4"><label className="block"><span className="text-[0.64rem] font-semibold uppercase tracking-[0.12em] text-slate-500">Demo case</span><select className="mt-2 h-10 w-full rounded-lg border border-white/[0.08] bg-ink-800 px-3 text-sm text-slate-100 outline-none focus:border-accent focus:ring-2 focus:ring-accent/20" value={selectedCaseId} onChange={(event) => setSelectedCaseId(event.target.value)}>{scenarios.data?.scenarios.map((scenario) => <option key={scenario.case_id} value={scenario.case_id}>{scenario.key} · {scenario.title} · {formatMoney(scenario.amount)}</option>)}</select></label>{selectedScenario ? <div className="mt-3 rounded-lg border border-white/[0.055] bg-ink-900/50 p-3"><div className="flex flex-wrap gap-2"><StatusBadge tone="neutral">{humanize(selectedScenario.failure_reason)}</StatusBadge><StatusBadge tone="info">Expected {humanize(selectedScenario.expected_action)}</StatusBadge></div><p className="mt-2 text-xs leading-5 text-slate-400">{selectedScenario.narrative}</p></div> : <p className="mt-3 text-xs text-slate-500">No demo case is currently available.</p>}</div><div className="rounded-xl border border-accent/20 bg-accent/[0.04] p-4"><p className="text-sm font-semibold text-slate-100">Evaluate the server’s real options</p><p className="mt-1 text-xs leading-5 text-slate-500">The backend applies any override only to this read-only simulation and returns the effective settings with the result.</p><Button className="mt-4 w-full" disabled={!selectedCaseId || builtOverrides.invalid} loading={simulation.loading || intelligenceSimulation.loading} onClick={handleEvaluate}><Sparkles aria-hidden="true" className="size-4" />Evaluate strategies & intelligence</Button>{builtOverrides.invalid ? <p className="mt-2 flex items-center gap-1.5 text-xs text-red-300"><CircleAlert aria-hidden="true" className="size-3.5" />Overrides must be non-negative whole numbers.</p> : null}</div></div>
      </Card>

      <Card className="overflow-hidden"><CardHeader><div><div className="flex items-center gap-2"><SlidersHorizontal aria-hidden="true" className="size-4 text-accent" /><p className="text-sm font-semibold text-slate-100">What-if settings</p></div><p className="mt-1 text-xs leading-5 text-slate-500">Blank fields preserve the backend configuration. Currency values are minor units (paise), exactly as the API expects.</p></div><button className="text-xs font-semibold text-sky-300 hover:text-sky-200" type="button" onClick={() => setForm(initialOverrides)}>Clear overrides</button></CardHeader><div className="grid gap-4 p-5 pt-4 md:grid-cols-2 xl:grid-cols-3"><NumberInput hint="Minutes before RETRY_LATER." label="Retry-later delay" value={form.retryLaterDelay} onChange={(value) => setForm((current) => ({ ...current, retryLaterDelay: value }))} /><NumberInput hint="Automatic recovery attempts." label="Max automatic retries" value={form.maxAutomaticRetries} onChange={(value) => setForm((current) => ({ ...current, maxAutomaticRetries: value }))} /><NumberInput hint="Repeated failures before policy acts." label="Repeated failure limit" value={form.repeatedFailureLimit} onChange={(value) => setForm((current) => ({ ...current, repeatedFailureLimit: value }))} /><NumberInput hint="Minor units / paise." label="High-value escalation threshold" value={form.highValueThreshold} onChange={(value) => setForm((current) => ({ ...current, highValueThreshold: value }))} /><label className="block min-w-0"><span className="block text-[0.64rem] font-semibold uppercase tracking-[0.11em] text-slate-500">Cost/friction action</span><select className="mt-1.5 h-10 w-full rounded-lg border border-white/[0.08] bg-ink-900 px-3 text-sm text-slate-100 outline-none focus:border-accent focus:ring-2 focus:ring-accent/20" value={form.action} onChange={(event) => setForm((current) => ({ ...current, action: event.target.value as ActionType }))}>{OVERRIDABLE_ACTIONS.map((action) => <option key={action} value={action}>{humanize(action)}</option>)}</select><span className="mt-1 block text-[0.65rem] leading-4 text-slate-600">One action per simulation pass.</span></label><div className="grid grid-cols-2 gap-3"><NumberInput hint="Minor units." label="Intervention cost" value={form.interventionCost} onChange={(value) => setForm((current) => ({ ...current, interventionCost: value }))} /><NumberInput hint="Minor units." label="Friction penalty" value={form.frictionPenalty} onChange={(value) => setForm((current) => ({ ...current, frictionPenalty: value }))} /></div></div></Card>

      {simulation.error ? <ErrorState compact error={simulation.error} onRetry={() => void handleEvaluate()} title="Strategy simulation could not complete" /> : null}
      {intelligenceSimulation.error ? <ErrorState compact error={intelligenceSimulation.error} onRetry={() => void handleEvaluate()} title="Recovery Intelligence simulation could not complete" /> : null}
      {simulation.data ? <StrategyResult result={simulation.data} /> : <Card><EmptyState compact description="Choose a deterministic case and run a read-only backend evaluation to compare all eligible recovery options." icon={Beaker} title="No strategy evaluation yet" /></Card>}
      {intelligenceSimulation.data ? <RecoveryIntelligencePanel intelligence={intelligenceSimulation.data} /> : null}
      <BaselineComparison />
    </div>
  );
}
