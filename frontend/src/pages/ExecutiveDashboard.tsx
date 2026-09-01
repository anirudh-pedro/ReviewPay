import {
  Activity,
  ArrowRight,
  BarChart3,
  Beaker,
  Bot,
  CheckCircle2,
  CircleDollarSign,
  ExternalLink,
  Gauge,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Workflow,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { Link } from 'react-router-dom';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { getOverview, listCases } from '@/api';
import {
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  InlineLinkArrow,
  Skeleton,
  StatusBadge,
  buttonClassName,
  cx,
} from '@/components/ui';
import type { StatusTone } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { useDemoData } from '@/contexts/DemoDataContext';
import type { CaseState, OverviewResponse, RecoveryCaseSummary } from '@/types/api';
import {
  formatDateTime,
  formatMoney,
  formatMoneyCompact,
  formatPercent,
  humanize,
} from '@/utils/format';

const RECENT_CASE_LIMIT = 7;

const PIPELINE_STEPS = [
  'Payment Failure',
  'Revenue Risk',
  'Diagnosis',
  'Options',
  'ERV',
  'Policy Gate',
  'Execute',
  'Verify',
  'Recover',
] as const;

const RECOVERY_OVERVIEW_COLORS = ['#f59e0b', '#22c55e', '#38bdf8'] as const;

type MetricTone = 'risk' | 'recovered' | 'accent' | 'escalated' | 'blocked';

interface MetricCardProps {
  label: string;
  value: string;
  detail: string;
  icon: LucideIcon;
  tone: MetricTone;
  featured?: boolean;
}

interface RevenueOverviewDatum {
  label: string;
  amount: number;
  detail: string;
  color: string;
}

interface FailurePerformanceDatum {
  label: string;
  amountAtRisk: number;
  amountRecovered: number;
  cases: number;
  recoveredCases: number;
  recoveryRate: number;
}

interface ActionPerformanceDatum {
  label: string;
  selected: number;
  executed: number;
  successes: number;
  failures: number;
  blocked: number;
  escalated: number;
  successRate: number;
  amountRecovered: number;
}

interface ChartTooltipPayload {
  payload?: unknown;
}

interface ChartTooltipProps {
  active?: boolean;
  payload?: ChartTooltipPayload[];
}

function metricToneClasses(tone: MetricTone): { icon: string; rule: string; value: string } {
  switch (tone) {
    case 'risk':
      return {
        icon: 'border-atrisk/25 bg-atrisk/10 text-atrisk',
        rule: 'bg-atrisk',
        value: 'text-amber-100',
      };
    case 'recovered':
      return {
        icon: 'border-recovered/25 bg-recovered/10 text-recovered',
        rule: 'bg-recovered',
        value: 'text-green-100',
      };
    case 'escalated':
      return {
        icon: 'border-escalated/25 bg-escalated/10 text-escalated',
        rule: 'bg-escalated',
        value: 'text-violet-100',
      };
    case 'blocked':
      return {
        icon: 'border-blocked/25 bg-blocked/10 text-blocked',
        rule: 'bg-blocked',
        value: 'text-red-100',
      };
    case 'accent':
    default:
      return {
        icon: 'border-accent/25 bg-accent/10 text-accent',
        rule: 'bg-accent',
        value: 'text-sky-100',
      };
  }
}

function MetricCard({ label, value, detail, icon: Icon, tone, featured = false }: MetricCardProps) {
  const styles = metricToneClasses(tone);

  return (
    <Card className={cx('relative overflow-hidden p-5', featured && 'bg-ink-850/95')}>
      <div className={cx('absolute inset-x-0 top-0 h-px opacity-75', styles.rule)} />
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[0.68rem] font-semibold uppercase tracking-[0.13em] text-slate-500">{label}</p>
          <p className={cx('metric-value mt-3 font-semibold', featured ? 'text-metric-lg' : 'text-metric', styles.value)}>
            {value}
          </p>
        </div>
        <div className={cx('grid size-9 shrink-0 place-items-center rounded-xl border', styles.icon)}>
          <Icon aria-hidden="true" className="size-[18px]" />
        </div>
      </div>
      <p className="mt-4 text-xs leading-5 text-slate-500">{detail}</p>
    </Card>
  );
}

function TooltipSurface({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="min-w-40 rounded-lg border border-white/10 bg-ink-900/95 px-3 py-2.5 shadow-xl shadow-black/30 backdrop-blur">
      <p className="text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-slate-400">{title}</p>
      <div className="mt-2 space-y-1.5">{children}</div>
    </div>
  );
}

function TooltipMetric({ label, value, tone = 'text-slate-100' }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex items-center justify-between gap-5 text-xs">
      <span className="text-slate-500">{label}</span>
      <span className={cx('font-mono font-medium tabular-nums', tone)}>{value}</span>
    </div>
  );
}

function RecoveryOverviewTooltip({ active, payload }: ChartTooltipProps) {
  const point = payload?.[0]?.payload as RevenueOverviewDatum | undefined;
  if (!active || !point) return null;

  return (
    <TooltipSurface title={point.label}>
      <TooltipMetric label="Amount" tone="text-slate-100" value={formatMoney(point.amount)} />
      <p className="pt-0.5 text-[0.68rem] leading-4 text-slate-500">{point.detail}</p>
    </TooltipSurface>
  );
}

function FailurePerformanceTooltip({ active, payload }: ChartTooltipProps) {
  const point = payload?.[0]?.payload as FailurePerformanceDatum | undefined;
  if (!active || !point) return null;

  return (
    <TooltipSurface title={point.label}>
      <TooltipMetric label="At risk" tone="text-amber-200" value={formatMoney(point.amountAtRisk)} />
      <TooltipMetric label="Recovered" tone="text-green-200" value={formatMoney(point.amountRecovered)} />
      <TooltipMetric label="Recovery rate" value={formatPercent(point.recoveryRate)} />
      <TooltipMetric label="Cases" value={String(point.cases)} />
      <TooltipMetric label="Recovered cases" value={String(point.recoveredCases)} />
    </TooltipSurface>
  );
}

function ActionPerformanceTooltip({ active, payload }: ChartTooltipProps) {
  const point = payload?.[0]?.payload as ActionPerformanceDatum | undefined;
  if (!active || !point) return null;

  return (
    <TooltipSurface title={point.label}>
      <TooltipMetric label="Selected" value={String(point.selected)} />
      <TooltipMetric label="Executed" tone="text-sky-200" value={String(point.executed)} />
      <TooltipMetric label="Successful" tone="text-green-200" value={String(point.successes)} />
      <TooltipMetric label="Blocked" tone="text-red-200" value={String(point.blocked)} />
      <TooltipMetric label="Escalated" tone="text-violet-200" value={String(point.escalated)} />
      <TooltipMetric label="Success rate" value={formatPercent(point.successRate)} />
      <TooltipMetric label="Recovered" tone="text-green-200" value={formatMoney(point.amountRecovered)} />
    </TooltipSurface>
  );
}

function formatAxisMoney(value: unknown): string {
  return typeof value === 'number' ? formatMoneyCompact(value) : '';
}

function caseStateTone(state: CaseState): StatusTone {
  switch (state) {
    case 'RECOVERED':
      return 'success';
    case 'BLOCKED':
    case 'FAILED':
      return 'danger';
    case 'ESCALATED':
      return 'violet';
    case 'DETECTED':
    case 'DIAGNOSING':
    case 'DIAGNOSED':
    case 'EVALUATING':
    case 'DECISION_READY':
    case 'POLICY_CHECK':
      return 'warning';
    case 'APPROVED':
    case 'SCHEDULED':
    case 'EXECUTING':
    case 'VERIFYING':
      return 'info';
    case 'STOPPED':
    default:
      return 'neutral';
  }
}

function DashboardSkeleton() {
  return (
    <div aria-busy="true" className="space-y-5" role="status">
      <span className="sr-only">Loading Command Center data.</span>
      <Card className="surface-grid overflow-hidden p-5 sm:p-6">
        <Skeleton className="h-3 w-28" />
        <Skeleton className="mt-4 h-8 w-[min(28rem,85%)]" />
        <Skeleton className="mt-3 h-4 w-full max-w-2xl" />
        <div className="mt-7 flex flex-wrap gap-2">
          <Skeleton className="h-9 w-32" />
          <Skeleton className="h-9 w-36" />
          <Skeleton className="h-9 w-28" />
        </div>
      </Card>
      <div className="grid gap-4 md:grid-cols-3">
        {[0, 1, 2].map((index) => (
          <Card key={index} className="p-5">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="mt-4 h-10 w-3/4" />
            <Skeleton className="mt-5 h-3 w-2/3" />
          </Card>
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((index) => (
          <Card key={index} className="p-5">
            <Skeleton className="h-3 w-28" />
            <Skeleton className="mt-4 h-8 w-1/2" />
            <Skeleton className="mt-5 h-3 w-3/4" />
          </Card>
        ))}
      </div>
      <div className="grid gap-5 xl:grid-cols-2">
        {[0, 1].map((index) => (
          <Card key={index} className="p-5">
            <Skeleton className="h-4 w-44" />
            <Skeleton className="mt-2 h-3 w-2/3" />
            <Skeleton className="mt-6 h-60 w-full" />
          </Card>
        ))}
      </div>
    </div>
  );
}

function ChartEmpty({ description, title }: { description: string; title: string }) {
  return <EmptyState compact description={description} icon={BarChart3} title={title} />;
}

function RecoveryPipeline() {
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <div>
          <div className="flex items-center gap-2">
            <Workflow aria-hidden="true" className="size-4 text-accent" />
            <p className="text-sm font-semibold text-slate-100">Recovery pipeline</p>
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            The operational handoff from failed payment to verified recovery.
          </p>
        </div>
        <StatusBadge tone="info">Backend governed</StatusBadge>
      </CardHeader>
      <div className="overflow-x-auto px-5 pb-5 pt-5">
        <ol aria-label="Recovery pipeline stages" className="flex min-w-max items-center gap-2">
          {PIPELINE_STEPS.map((step, index) => {
            const isFinalStage = index === PIPELINE_STEPS.length - 1;
            return (
              <li key={step} className="flex items-center gap-2">
                <div
                  className={cx(
                    'flex min-h-16 w-28 flex-col justify-center rounded-lg border px-3',
                    isFinalStage
                      ? 'border-recovered/30 bg-recovered/10'
                      : 'border-white/[0.07] bg-ink-800/65',
                  )}
                >
                  <span
                    className={cx(
                      'font-mono text-[0.63rem] font-semibold tabular-nums',
                      isFinalStage ? 'text-recovered' : 'text-slate-500',
                    )}
                  >
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  <span className={cx('mt-1 text-xs font-semibold', isFinalStage ? 'text-green-200' : 'text-slate-200')}>
                    {step}
                  </span>
                </div>
                {isFinalStage ? null : <ArrowRight aria-hidden="true" className="size-3.5 shrink-0 text-slate-600" />}
              </li>
            );
          })}
        </ol>
      </div>
    </Card>
  );
}

function RecentActivity({
  cases,
  error,
  loading,
  onRetry,
}: {
  cases: RecoveryCaseSummary[] | null;
  error: Error | null;
  loading: boolean;
  onRetry: () => void;
}) {
  return (
    <Card className="overflow-hidden">
      <CardHeader className="items-center">
        <div>
          <div className="flex items-center gap-2">
            <Activity aria-hidden="true" className="size-4 text-accent" />
            <p className="text-sm font-semibold text-slate-100">Recent recovery activity</p>
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            Lightweight case-list results. Open any case to inspect the full decision and audit trail.
          </p>
        </div>
        <Link className={buttonClassName('ghost', 'sm', 'shrink-0')} to="/cases">
          View cases
          <InlineLinkArrow />
        </Link>
      </CardHeader>

      {loading ? (
        <div aria-busy="true" className="space-y-3 p-5" role="status">
          <span className="sr-only">Loading recovery activity.</span>
          {[0, 1, 2, 3].map((index) => (
            <div key={index} className="flex items-center justify-between gap-4 border-b border-white/[0.05] pb-3 last:border-0">
              <div className="min-w-0 flex-1">
                <Skeleton className="h-3 w-28" />
                <Skeleton className="mt-2 h-3 w-20" />
              </div>
              <Skeleton className="h-7 w-20" />
              <Skeleton className="hidden h-7 w-24 sm:block" />
              <Skeleton className="hidden h-7 w-24 md:block" />
            </div>
          ))}
        </div>
      ) : error ? (
        <ErrorState compact error={error} onRetry={onRetry} title="Recovery activity is unavailable" />
      ) : !cases ? (
        <ErrorState
          compact
          error="No valid case-list response was received. No activity values are being shown."
          onRetry={onRetry}
          title="Recovery activity could not be read"
        />
      ) : cases.length === 0 ? (
        <ChartEmpty
          description="The case-list response does not currently contain recovery activity. New cases will appear here when the API returns them."
          title="No recovery activity yet"
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[960px] text-left">
            <caption className="sr-only">
              Recent recovery case summaries from the API. Failure reason, current action, and policy are not included in the list response.
            </caption>
            <thead className="border-y border-white/[0.055] bg-white/[0.018]">
              <tr className="text-[0.64rem] font-semibold uppercase tracking-[0.12em] text-slate-500">
                <th className="px-5 py-3 font-semibold" scope="col">Case</th>
                <th className="px-4 py-3 font-semibold" scope="col">Amount at risk</th>
                <th className="px-4 py-3 font-semibold" scope="col">Failure reason</th>
                <th className="px-4 py-3 font-semibold" scope="col">Current action</th>
                <th className="px-4 py-3 font-semibold" scope="col">Policy</th>
                <th className="px-4 py-3 font-semibold" scope="col">Outcome / state</th>
                <th className="px-5 py-3 text-right font-semibold" scope="col">Updated</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.05]">
              {cases.map((item) => (
                <tr key={item.case_id} className="group transition-colors hover:bg-white/[0.022]">
                  <td className="px-5 py-3.5 align-middle">
                    <Link
                      className="inline-flex items-center gap-1.5 font-mono text-xs font-semibold text-sky-300 transition-colors hover:text-sky-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                      title="Open this case in Case Explorer"
                      to={`/cases/${encodeURIComponent(item.case_id)}`}
                    >
                      {item.case_id}
                      <ExternalLink aria-hidden="true" className="size-3" />
                    </Link>
                    <p className="mt-1 font-mono text-[0.66rem] text-slate-500">Payment {item.payment_id}</p>
                  </td>
                  <td className="px-4 py-3.5 align-middle font-mono text-sm font-medium tabular-nums text-amber-100">
                    {formatMoney(item.amount_at_risk)}
                  </td>
                  <td className="px-4 py-3.5 align-middle">
                    <span className="text-xs text-slate-500">Not in list response</span>
                  </td>
                  <td className="px-4 py-3.5 align-middle">
                    <span className="text-xs text-slate-500">Not in list response</span>
                  </td>
                  <td className="px-4 py-3.5 align-middle">
                    <span className="text-xs text-slate-500">Not in list response</span>
                  </td>
                  <td className="px-4 py-3.5 align-middle">
                    <StatusBadge tone={caseStateTone(item.state)}>{humanize(item.state)}</StatusBadge>
                  </td>
                  <td className="px-5 py-3.5 text-right align-middle font-mono text-[0.68rem] tabular-nums text-slate-400">
                    <time dateTime={item.updated_at}>{formatDateTime(item.updated_at)}</time>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function DashboardContent({ overview }: { overview: OverviewResponse }) {
  const recoveryOverviewData: RevenueOverviewDatum[] = [
    {
      label: 'Revenue at risk',
      amount: overview.revenue_at_risk.amount,
      detail: 'Server-reported revenue exposed to payment failure.',
      color: RECOVERY_OVERVIEW_COLORS[0],
    },
    {
      label: 'Recovered revenue',
      amount: overview.revenue_recovered.amount,
      detail: 'Server-reported revenue with a verified recovery outcome.',
      color: RECOVERY_OVERVIEW_COLORS[1],
    },
    {
      label: 'Opportunity (ERV)',
      amount: overview.expected_recovery_value_total.amount,
      detail: 'Backend-calculated expected recovery value; not recomputed in the browser.',
      color: RECOVERY_OVERVIEW_COLORS[2],
    },
  ];

  const failurePerformanceData: FailurePerformanceDatum[] = overview.by_failure_reason.map((item) => ({
    label: humanize(item.failure_reason),
    amountAtRisk: item.amount_at_risk.amount,
    amountRecovered: item.amount_recovered.amount,
    cases: item.cases,
    recoveredCases: item.recovered_cases,
    recoveryRate: item.recovery_rate,
  }));

  const actionPerformanceData: ActionPerformanceDatum[] = overview.by_action.map((item) => ({
    label: humanize(item.action_type),
    selected: item.selected,
    executed: item.executed,
    successes: item.successes,
    failures: item.failures,
    blocked: item.blocked,
    escalated: item.escalated,
    successRate: item.success_rate,
    amountRecovered: item.amount_recovered.amount,
  }));

  return (
    <>
      <Card className="surface-grid relative overflow-hidden">
        <div className="absolute -right-16 -top-20 size-56 rounded-full bg-accent/10 blur-3xl" />
        <div className="absolute -bottom-20 left-1/3 size-44 rounded-full bg-escalated/5 blur-3xl" />
        <div className="relative p-5 sm:p-6 lg:p-7">
          <div className="flex flex-col justify-between gap-5 xl:flex-row xl:items-start">
            <div className="max-w-3xl">
              <div className="flex flex-wrap items-center gap-2">
                <StatusBadge tone="info">
                  <span aria-hidden="true" className="size-1.5 rounded-full bg-accent shadow-[0_0_8px_#38bdf8]" />
                  Live recovery overview
                </StatusBadge>
                <span className="text-[0.68rem] font-semibold uppercase tracking-[0.12em] text-slate-500">
                  {overview.data_source}
                </span>
              </div>
              <h1 className="mt-4 text-2xl font-semibold tracking-tight text-slate-50 sm:text-3xl">
                Revenue recovery, decision-ready.
              </h1>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">
                A real-time executive view of revenue risk, backend-calculated recovery opportunity, policy controls, and verified outcomes.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2 xl:justify-end">
              <button
                aria-label="Refresh Command Center data"
                className={buttonClassName('ghost', 'sm')}
                title="Refresh Command Center data"
                type="button"
                onClick={() => window.location.reload()}
              >
                <RefreshCw aria-hidden="true" className="size-3.5" />
                Refresh
              </button>
              <Link className={buttonClassName('primary', 'sm')} to="/autopilot">
                <Bot aria-hidden="true" className="size-3.5" />
                Open Autopilot
                <InlineLinkArrow />
              </Link>
              <Link className={buttonClassName('secondary', 'sm')} to="/strategy-lab">
                <Beaker aria-hidden="true" className="size-3.5" />
                Strategy Lab
                <InlineLinkArrow />
              </Link>
            </div>
          </div>
          <div className="mt-6 grid gap-3 border-t border-white/[0.06] pt-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
            <p className="text-xs leading-5 text-slate-400">{overview.notice}</p>
            <time
              className="justify-self-start rounded-md border border-white/[0.07] bg-ink-900/60 px-2.5 py-1.5 font-mono text-[0.68rem] tabular-nums text-slate-400 sm:justify-self-end"
              dateTime={overview.virtual_clock_time}
            >
              Data as of {formatDateTime(overview.virtual_clock_time)}
            </time>
          </div>
        </div>
      </Card>

      <section aria-label="Primary revenue metrics" className="grid gap-4 md:grid-cols-3">
        <MetricCard
          detail={`${overview.payments_at_risk} payment${overview.payments_at_risk === 1 ? '' : 's'} currently at risk`}
          featured
          icon={CircleDollarSign}
          label="Revenue at risk"
          tone="risk"
          value={formatMoney(overview.revenue_at_risk)}
        />
        <MetricCard
          detail={`${overview.verified_outcomes} verified outcome${overview.verified_outcomes === 1 ? '' : 's'}`}
          featured
          icon={CheckCircle2}
          label="Recovered revenue"
          tone="recovered"
          value={formatMoney(overview.revenue_recovered)}
        />
        <MetricCard
          detail={`${overview.cases_recovered} recovered of ${overview.cases_total} total cases`}
          featured
          icon={TrendingUp}
          label="Recovery rate"
          tone="accent"
          value={formatPercent(overview.recovery_rate)}
        />
      </section>

      <section aria-label="Operational recovery metrics" className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          detail={`Policy-approved ERV: ${formatMoney(overview.expected_recovery_value_approved)}`}
          icon={Sparkles}
          label="Expected recovery value"
          tone="accent"
          value={formatMoney(overview.expected_recovery_value_total)}
        />
        <MetricCard
          detail={`${overview.scheduled_cases} case${overview.scheduled_cases === 1 ? '' : 's'} scheduled for action`}
          icon={Activity}
          label="Active cases"
          tone="risk"
          value={String(overview.active_cases)}
        />
        <MetricCard
          detail="Cases requiring human escalation"
          icon={Gauge}
          label="Escalated cases"
          tone="escalated"
          value={String(overview.human_escalations)}
        />
        <MetricCard
          detail={`${overview.policy_approvals} policy approval${overview.policy_approvals === 1 ? '' : 's'} recorded`}
          icon={ShieldCheck}
          label="Policy-blocked cases"
          tone="blocked"
          value={String(overview.policy_blocks)}
        />
      </section>

      <RecoveryPipeline />

      <section aria-label="Recovery performance charts" className="grid gap-5 xl:grid-cols-2">
        <Card className="overflow-hidden">
          <CardHeader>
            <div>
              <div className="flex items-center gap-2">
                <CircleDollarSign aria-hidden="true" className="size-4 text-accent" />
                <p className="text-sm font-semibold text-slate-100">Recovery overview</p>
              </div>
              <p className="mt-1 text-xs leading-5 text-slate-500">
                At-risk, recovered, and expected recovery value from the overview response.
              </p>
            </div>
            <StatusBadge tone="info">INR</StatusBadge>
          </CardHeader>
          <div className="px-3 pb-4 pt-2 sm:px-5">
            <div aria-label="Recovery overview chart" className="h-64" role="img">
              <span className="sr-only">
                Revenue at risk {formatMoney(overview.revenue_at_risk)}, recovered revenue {formatMoney(overview.revenue_recovered)}, and expected recovery value {formatMoney(overview.expected_recovery_value_total)}.
              </span>
              <ResponsiveContainer height="100%" width="100%">
                <BarChart data={recoveryOverviewData} layout="vertical" margin={{ bottom: 2, left: 0, right: 20, top: 2 }}>
                  <CartesianGrid horizontal={false} stroke="rgba(148, 163, 184, 0.12)" strokeDasharray="3 3" />
                  <XAxis
                    axisLine={false}
                    tickFormatter={formatAxisMoney}
                    tickLine={false}
                    tick={{ fill: '#8b98ad', fontSize: 11 }}
                    type="number"
                  />
                  <YAxis
                    axisLine={false}
                    dataKey="label"
                    tick={{ fill: '#cbd5e1', fontSize: 11 }}
                    tickLine={false}
                    type="category"
                    width={112}
                  />
                  <Tooltip content={<RecoveryOverviewTooltip />} cursor={{ fill: 'rgba(148, 163, 184, 0.06)' }} />
                  <Bar dataKey="amount" radius={[0, 6, 6, 0]}>
                    {recoveryOverviewData.map((item) => (
                      <Cell fill={item.color} key={item.label} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </Card>

        <Card className="overflow-hidden">
          <CardHeader>
            <div>
              <div className="flex items-center gap-2">
                <BarChart3 aria-hidden="true" className="size-4 text-atrisk" />
                <p className="text-sm font-semibold text-slate-100">Failure-reason performance</p>
              </div>
              <p className="mt-1 text-xs leading-5 text-slate-500">
                Compare revenue at risk and recovered revenue by API-reported failure reason.
              </p>
            </div>
          </CardHeader>
          {failurePerformanceData.length === 0 ? (
            <ChartEmpty
              description="The overview response has no failure-reason breakdown yet. This chart will populate as the API reports it."
              title="No failure-reason performance available"
            />
          ) : (
            <div className="px-3 pb-4 pt-2 sm:px-5">
              <div aria-label="Failure-reason performance chart" className="h-72" role="img">
                <span className="sr-only">Failure-reason performance is shown as server-reported at-risk and recovered revenue.</span>
                <ResponsiveContainer height="100%" width="100%">
                  <BarChart data={failurePerformanceData} layout="vertical" margin={{ bottom: 2, left: 0, right: 10, top: 2 }}>
                    <CartesianGrid horizontal={false} stroke="rgba(148, 163, 184, 0.12)" strokeDasharray="3 3" />
                    <XAxis
                      axisLine={false}
                      tickFormatter={formatAxisMoney}
                      tickLine={false}
                      tick={{ fill: '#8b98ad', fontSize: 11 }}
                      type="number"
                    />
                    <YAxis
                      axisLine={false}
                      dataKey="label"
                      tick={{ fill: '#cbd5e1', fontSize: 10 }}
                      tickLine={false}
                      type="category"
                      width={118}
                    />
                    <Tooltip content={<FailurePerformanceTooltip />} cursor={{ fill: 'rgba(148, 163, 184, 0.06)' }} />
                    <Legend iconSize={8} wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
                    <Bar dataKey="amountAtRisk" fill="#f59e0b" name="At risk" radius={[0, 4, 4, 0]} />
                    <Bar dataKey="amountRecovered" fill="#22c55e" name="Recovered" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </Card>

        <Card className="overflow-hidden xl:col-span-2">
          <CardHeader>
            <div>
              <div className="flex items-center gap-2">
                <Gauge aria-hidden="true" className="size-4 text-escalated" />
                <p className="text-sm font-semibold text-slate-100">Action performance</p>
              </div>
              <p className="mt-1 text-xs leading-5 text-slate-500">
                Selected, executed, successful, and policy-blocked action counts from the backend.
              </p>
            </div>
          </CardHeader>
          {actionPerformanceData.length === 0 ? (
            <ChartEmpty
              description="The overview response has no action breakdown yet. This chart will populate as server-evaluated actions are returned."
              title="No action performance available"
            />
          ) : (
            <div className="px-3 pb-4 pt-2 sm:px-5">
              <div aria-label="Action performance chart" className="h-72" role="img">
                <span className="sr-only">Action performance is shown as selected, executed, successful, and policy-blocked counts reported by the API.</span>
                <ResponsiveContainer height="100%" width="100%">
                  <BarChart data={actionPerformanceData} layout="vertical" margin={{ bottom: 2, left: 0, right: 10, top: 2 }}>
                    <CartesianGrid horizontal={false} stroke="rgba(148, 163, 184, 0.12)" strokeDasharray="3 3" />
                    <XAxis
                      allowDecimals={false}
                      axisLine={false}
                      tick={{ fill: '#8b98ad', fontSize: 11 }}
                      tickLine={false}
                      type="number"
                    />
                    <YAxis
                      axisLine={false}
                      dataKey="label"
                      tick={{ fill: '#cbd5e1', fontSize: 10 }}
                      tickLine={false}
                      type="category"
                      width={132}
                    />
                    <Tooltip content={<ActionPerformanceTooltip />} cursor={{ fill: 'rgba(148, 163, 184, 0.06)' }} />
                    <Legend iconSize={8} wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
                    <Bar dataKey="executed" fill="#38bdf8" name="Executed" radius={[0, 4, 4, 0]} />
                    <Bar dataKey="successes" fill="#22c55e" name="Successful" radius={[0, 4, 4, 0]} />
                    <Bar dataKey="blocked" fill="#f87171" name="Blocked" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </Card>
      </section>
    </>
  );
}

/**
 * Executive command center backed exclusively by the typed overview and case-list APIs.
 * Recovery calculations, policy decisions, and expected recovery values remain backend-owned.
 */
export function ExecutiveDashboard() {
  const { dataVersion } = useDemoData();
  const overview = useApi(getOverview, [dataVersion]);
  const caseList = useApi(
    (signal) => listCases({ limit: RECENT_CASE_LIMIT }, signal),
    [dataVersion],
  );

  const refetchAll = () => {
    overview.refetch();
    caseList.refetch();
  };

  if (overview.loading) return <DashboardSkeleton />;

  if (overview.error) {
    return (
      <Card className="surface-grid overflow-hidden">
        <ErrorState
          error={overview.error}
          onRetry={refetchAll}
          title="Command Center data is unavailable"
        />
      </Card>
    );
  }

  if (!overview.data) {
    return (
      <Card className="surface-grid overflow-hidden">
        <ErrorState
          error="No valid overview response was received. No dashboard values are being shown."
          onRetry={refetchAll}
          title="Command Center data could not be read"
        />
      </Card>
    );
  }

  return (
    <div className="space-y-5 animate-fade-up">
      <DashboardContent overview={overview.data} />
      <RecentActivity
        cases={caseList.data?.items ?? null}
        error={caseList.error}
        loading={caseList.loading}
        onRetry={caseList.refetch}
      />
    </div>
  );
}
