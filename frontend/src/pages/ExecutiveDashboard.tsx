import {
  Activity,
  Award,
  BarChart3,
  CheckCircle2,
  Clock3,
  DollarSign,
  ShieldAlert,
  ShieldCheck,
  TrendingUp,
  Zap,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { getOverview } from '@/api';
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
import { useApi } from '@/hooks/useApi';
import type { OverviewResponse } from '@/types/api';
import { formatMoney, formatPercent, humanize } from '@/utils/format';

export function ExecutiveDashboard() {
  const overviewQuery = useApi(getOverview, []);

  if (overviewQuery.loading) {
    return (
      <div className="space-y-6">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-28 w-full rounded-xl" />
          ))}
        </div>
        <Skeleton className="h-96 w-full rounded-xl" />
      </div>
    );
  }

  if (overviewQuery.error || !overviewQuery.data) {
    return (
      <ErrorState
        error={overviewQuery.error ?? new Error('Failed to load dashboard metrics.')}
        onRetry={() => void overviewQuery.refetch()}
      />
    );
  }

  const data: OverviewResponse = overviewQuery.data;

  // Chart data preparation
  const chartData = [
    {
      name: 'At Risk',
      amount: data.revenue_at_risk.amount,
      display: formatMoney(data.revenue_at_risk.amount, true),
      fill: '#f59e0b',
    },
    {
      name: 'Recovered',
      amount: data.revenue_recovered.amount,
      display: formatMoney(data.revenue_recovered.amount, true),
      fill: '#10b981',
    },
    {
      name: 'Expected Value',
      amount: data.expected_recovery_value_total.amount,
      display: formatMoney(data.expected_recovery_value_total.amount, true),
      fill: '#38bdf8',
    },
  ];

  return (
    <div className="space-y-6">
      {/* Top Welcome & Quick Action Header */}
      <Card className="p-6 bg-gradient-to-r from-slate-900/90 via-slate-900/60 to-sky-950/40 border-sky-500/20">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <StatusBadge tone="info">REVENUE RECOVERY OPERATIONS</StatusBadge>
              <StatusBadge tone="success">LIVE INTELLIGENCE</StatusBadge>
            </div>
            <h1 className="mt-2 text-2xl font-bold text-slate-50 tracking-tight">
              Executive Command Center
            </h1>
            <p className="mt-1 text-sm text-slate-300">
              Autonomous risk detection, ERV-ranked strategy decisioning, and policy-gated revenue recovery.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Link to="/judge-demo">
              <Button variant="primary">
                <Award aria-hidden="true" className="size-4" />
                Launch Judge Demo Flow
              </Button>
            </Link>
            <Link to="/autopilot">
              <Button variant="secondary">
                <Zap aria-hidden="true" className="size-4" />
                Run Autopilot Batch
              </Button>
            </Link>
          </div>
        </div>
      </Card>

      {/* 6 Core Executive KPIs */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <MetricCard
          icon={DollarSign}
          subtext={`${data.payments_at_risk} failed payment(s) total`}
          title="Revenue at Risk"
          tone="amber"
          value={`${formatMoney(data.revenue_at_risk.amount, true)} INR`}
        />

        <MetricCard
          icon={TrendingUp}
          subtext={`${data.cases_recovered} case(s) verified recovered`}
          title="Revenue Recovered"
          tone="emerald"
          value={`${formatMoney(data.revenue_recovered.amount, true)} INR`}
        />

        <MetricCard
          icon={BarChart3}
          subtext={`Avg. value: ${formatMoney(data.average_recovery_value.amount, true)} INR`}
          title="Recovery Rate"
          tone="sky"
          value={formatPercent(data.recovery_rate)}
        />

        <MetricCard
          icon={CheckCircle2}
          subtext={`${data.active_cases} active / ${data.cases_total} total cases`}
          title="Cases Recovered"
          tone="emerald"
          value={`${data.cases_recovered}`}
        />

        <MetricCard
          icon={ShieldAlert}
          subtext={`${data.policy_approvals} action(s) approved by policy`}
          title="Policy Blocks"
          tone="rose"
          value={`${data.policy_blocks}`}
        />

        <MetricCard
          icon={Clock3}
          subtext="High-value threshold exceeded"
          title="Escalations"
          tone="indigo"
          value={`${data.human_escalations}`}
        />
      </div>

      {/* Primary Visual Charts Row */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Revenue Performance Bar Chart */}
        <Card className="p-6">
          <CardHeader className="px-0 pt-0 mb-4">
            <div>
              <h2 className="text-base font-semibold text-slate-100">Revenue Performance</h2>
              <p className="text-xs text-slate-400">Total at risk vs verified recovered vs expected recovery value</p>
            </div>
            <TrendingUp className="size-5 text-emerald-400" />
          </CardHeader>

          <div className="h-64 w-full">
            <ResponsiveContainer height="100%" width="100%">
              <BarChart data={chartData} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
                <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="name" stroke="#64748b" fontSize={12} tickLine={false} />
                <YAxis stroke="#64748b" fontSize={11} tickFormatter={(val) => `₹${val / 100}`} tickLine={false} />
                <Tooltip
                  content={({ active, payload }) => {
                    if (active && payload && payload.length) {
                      const item = payload[0].payload;
                      return (
                        <div className="rounded-lg border border-slate-700 bg-slate-900 p-3 shadow-xl text-xs font-mono">
                          <p className="font-bold text-slate-200">{item.name}</p>
                          <p className="mt-1 text-sky-400">{item.display} INR</p>
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                <Bar dataKey="amount" radius={[6, 6, 0, 0]}>
                  {chartData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        {/* Failure Cause Breakdown Table */}
        <Card className="p-6">
          <CardHeader className="px-0 pt-0 mb-4">
            <div>
              <h2 className="text-base font-semibold text-slate-100">Failure Cause Performance</h2>
              <p className="text-xs text-slate-400">Recovery breakdown by root payment failure reason</p>
            </div>
            <Activity className="size-5 text-sky-400" />
          </CardHeader>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-white/10 text-[0.68rem] font-bold uppercase tracking-wider text-slate-400">
                <tr>
                  <th className="pb-3">Failure Reason</th>
                  <th className="pb-3 text-right">Cases</th>
                  <th className="pb-3 text-right">At Risk</th>
                  <th className="pb-3 text-right">Recovered</th>
                  <th className="pb-3 text-right">Rate</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.04]">
                {data.by_failure_reason.map((row) => (
                  <tr key={row.failure_reason} className="hover:bg-white/[0.02]">
                    <td className="py-2.5 font-medium text-slate-200">{humanize(row.failure_reason)}</td>
                    <td className="py-2.5 text-right font-mono text-slate-400">{row.cases}</td>
                    <td className="py-2.5 text-right font-mono text-amber-300">{formatMoney(row.amount_at_risk.amount, true)}</td>
                    <td className="py-2.5 text-right font-mono text-emerald-400">{formatMoney(row.amount_recovered.amount, true)}</td>
                    <td className="py-2.5 text-right font-mono text-slate-300">{formatPercent(row.recovery_rate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      {/* Action Type Performance */}
      <Card className="p-6">
        <CardHeader className="px-0 pt-0 mb-4">
          <div>
            <h2 className="text-base font-semibold text-slate-100">Recovery Action Performance</h2>
            <p className="text-xs text-slate-400">Selected strategy efficiency, policy gating, and success rates</p>
          </div>
        </CardHeader>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-white/10 text-[0.68rem] font-bold uppercase tracking-wider text-slate-400">
              <tr>
                <th className="pb-3">Action Type</th>
                <th className="pb-3 text-right">Selected</th>
                <th className="pb-3 text-right">Executed</th>
                <th className="pb-3 text-right">Policy Blocked</th>
                <th className="pb-3 text-right">Success Rate</th>
                <th className="pb-3 text-right">Recovered Amount</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {data.by_action.map((act) => (
                <tr key={act.action_type} className="hover:bg-white/[0.02]">
                  <td className="py-3 font-semibold text-slate-200">{act.action_type}</td>
                  <td className="py-3 text-right font-mono text-slate-400">{act.selected}</td>
                  <td className="py-3 text-right font-mono text-sky-400">{act.executed}</td>
                  <td className="py-3 text-right font-mono text-rose-400">{act.blocked}</td>
                  <td className="py-3 text-right font-mono text-emerald-400">{formatPercent(act.success_rate)}</td>
                  <td className="py-3 text-right font-mono text-slate-100">{formatMoney(act.amount_recovered.amount, true)} INR</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Expandable Technical Safety Checks */}
      <Accordion title="Technical Safety Posture & Audit Constraints">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 pt-2">
          <div className="flex items-center gap-2 text-xs">
            <ShieldCheck className="size-4 text-emerald-400" />
            <span>Budget Enforced: {String(data.safety.recovery_budget_enforced)}</span>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <ShieldCheck className="size-4 text-emerald-400" />
            <span>High-Value Escalation: {String(data.safety.high_value_escalation_enabled)}</span>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <ShieldCheck className="size-4 text-emerald-400" />
            <span>Blocked Never Executed: {String(data.safety.blocked_actions_never_executed)}</span>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <ShieldCheck className="size-4 text-emerald-400" />
            <span>Audit Immutability: {String(data.safety.complete_audit_trail)}</span>
          </div>
        </div>
      </Accordion>
    </div>
  );
}
