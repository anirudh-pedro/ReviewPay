import {
  Activity,
  BarChart3,
  CheckCircle2,
  Clock3,
  DollarSign,
  ShieldAlert,
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

  // Chart data for revenue performance
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
      name: 'Expected ERV',
      amount: data.expected_recovery_value_total.amount,
      display: formatMoney(data.expected_recovery_value_total.amount, true),
      fill: '#4f46e5',
    },
  ];

  return (
    <div className="space-y-6">
      {/* Top Banner */}
      <Card className="p-6 bg-white border-slate-200">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <StatusBadge tone="info">REVENUE RECOVERY OPERATIONS</StatusBadge>
              <StatusBadge tone="success">LIVE RECOVERY METRICS</StatusBadge>
            </div>
            <h1 className="mt-2 text-2xl font-bold text-slate-900 tracking-tight">
              Executive Recovery Dashboard
            </h1>
            <p className="mt-1 text-xs text-slate-500">
              Autonomous risk detection, ERV-ranked strategy decisioning, and policy-gated revenue recovery.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            <Link to="/simulator">
              <Button variant="primary">
                <Zap aria-hidden="true" className="size-4 mr-1.5" />
                Launch Recovery Simulator
              </Button>
            </Link>
            <Link to="/cases">
              <Button variant="secondary">
                <Activity aria-hidden="true" className="size-4 mr-1.5" />
                View Cases Queue
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
          tone="success"
          value={`${formatMoney(data.revenue_recovered.amount, true)} INR`}
        />

        <MetricCard
          icon={BarChart3}
          subtext={`Avg. value: ${formatMoney(data.average_recovery_value.amount, true)} INR`}
          title="Recovery Rate"
          tone="indigo"
          value={formatPercent(data.recovery_rate)}
        />

        <MetricCard
          icon={CheckCircle2}
          subtext={`${data.active_cases} active / ${data.cases_total} total cases`}
          title="Cases Recovered"
          tone="success"
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
              <h2 className="text-base font-semibold text-slate-900">Revenue Performance</h2>
              <p className="text-xs text-slate-500">Total at risk vs verified recovered vs expected recovery value</p>
            </div>
            <TrendingUp className="size-5 text-emerald-600" />
          </CardHeader>

          <div className="h-64 w-full">
            <ResponsiveContainer height="100%" width="100%">
              <BarChart data={chartData} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
                <CartesianGrid stroke="#f1f5f9" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="name" stroke="#94a3b8" fontSize={12} tickLine={false} />
                <YAxis stroke="#94a3b8" fontSize={11} tickFormatter={(val) => `₹${val / 100}`} tickLine={false} />
                <Tooltip
                  content={({ active, payload }) => {
                    if (active && payload && payload.length) {
                      const item = payload[0].payload;
                      return (
                        <div className="rounded-xl border border-slate-200 bg-white p-3 shadow-md text-xs font-mono">
                          <p className="font-bold text-slate-800">{item.name}</p>
                          <p className="mt-1 text-indigo-600 font-bold">{item.display} INR</p>
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
              <h2 className="text-base font-semibold text-slate-900">Failure Cause Performance</h2>
              <p className="text-xs text-slate-500">Recovery breakdown by root payment failure reason</p>
            </div>
            <BarChart3 className="size-5 text-indigo-600" />
          </CardHeader>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-slate-100 text-slate-400 font-semibold text-[11px] uppercase">
                <tr>
                  <th className="pb-2">Failure Cause</th>
                  <th className="pb-2 text-right">Total Cases</th>
                  <th className="pb-2 text-right">Recovered</th>
                  <th className="pb-2 text-right">Rate</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-700">
                {data.by_failure_reason.map((f) => (
                  <tr key={f.failure_reason} className="hover:bg-slate-50/70">
                    <td className="py-2.5 font-medium text-slate-900">{humanize(f.failure_reason)}</td>
                    <td className="py-2.5 text-right font-mono text-slate-600">{f.cases}</td>
                    <td className="py-2.5 text-right font-mono font-semibold text-emerald-600">
                      {f.recovered_cases}
                    </td>
                    <td className="py-2.5 text-right font-mono font-bold text-slate-800">
                      {formatPercent(f.recovery_rate)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      {/* Action Breakdown Row */}
      <Card className="p-6">
        <CardHeader className="px-0 pt-0 mb-4">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Action Type Distribution</h2>
            <p className="text-xs text-slate-500">Intervention breakdown and execution rates across candidate actions</p>
          </div>
          <Activity className="size-5 text-indigo-600" />
        </CardHeader>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {data.by_action.map((a) => (
            <div key={a.action_type} className="rounded-xl border border-slate-200 bg-slate-50/50 p-3.5">
              <div className="text-xs font-semibold text-slate-800">{humanize(a.action_type)}</div>
              <div className="mt-2 flex items-baseline justify-between">
                <span className="font-mono text-lg font-bold text-slate-900">{a.selected}</span>
                <span className="text-[11px] font-semibold text-emerald-600">
                  {formatPercent(a.success_rate)}
                </span>
              </div>
              <div className="mt-1 text-[11px] text-slate-500">
                Recovered: <span className="font-mono font-medium text-slate-700">{formatMoney(a.amount_recovered.amount, true)} INR</span>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Expandable Technical Telemetry */}
      <Accordion title="Executive Telemetry & Technical Raw Breakdown">
        <pre className="overflow-x-auto rounded-lg bg-slate-50 border border-slate-200 p-3 font-mono text-[0.7rem] text-slate-700">
          {JSON.stringify(data, null, 2)}
        </pre>
      </Accordion>
    </div>
  );
}
