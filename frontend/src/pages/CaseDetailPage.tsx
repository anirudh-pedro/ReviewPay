import { useMemo } from 'react';
import { ArrowLeft, Play, ShieldCheck, CreditCard, CheckCircle2, AlertCircle } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import { getCaseIntelligence, getRecoveryIntelligence, runCase } from '@/api';
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
import type { StatusTone } from '@/components/ui';
import { AuditTimeline } from '@/components/AuditTimeline';
import { RecoveryIntelligencePanel } from '@/components/RecoveryIntelligencePanel';
import { useApi, useAsyncAction } from '@/hooks/useApi';
import type { CaseState } from '@/types/api';
import { formatDateTime, formatMoney, humanize } from '@/utils/format';

function stateTone(state: CaseState): StatusTone {
  switch (state) {
    case 'RECOVERED':
      return 'success';
    case 'BLOCKED':
    case 'STOPPED':
      return 'danger';
    case 'ESCALATED':
      return 'violet';
    case 'EXECUTING':
    case 'VERIFYING':
      return 'info';
    default:
      return 'warning';
  }
}

export function CaseDetailPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const fetcher = useMemo(() => () => getCaseIntelligence(caseId!), [caseId]);
  const intelFetcher = useMemo(() => () => getRecoveryIntelligence(caseId!), [caseId]);

  const { data, loading, error, refetch } = useApi(fetcher, [caseId]);
  const intelQuery = useApi(intelFetcher, [caseId]);

  const runAction = useAsyncAction(async () => {
    if (!caseId) return;
    try {
      await runCase(caseId);
    } catch (cause) {
      const is409 = cause && typeof cause === 'object' && 'status' in cause && cause.status === 409;
      if (!is409) throw cause;
    }
    await refetch();
    await intelQuery.refetch();
  });

  if (loading || intelQuery.loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-48 rounded-xl" />
        <Skeleton className="h-32 w-full rounded-xl" />
        <Skeleton className="h-96 w-full rounded-xl" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <ErrorState
        error={error ?? new Error('Recovery case not found.')}
        onRetry={() => void refetch()}
      />
    );
  }

  const { recoveryCase, payment, audit } = data;
  const isTerminal = recoveryCase.is_terminal;
  const latestAction = recoveryCase.latest_action;
  const latestPolicy = recoveryCase.latest_policy;
  const latestOutcome = recoveryCase.latest_outcome;
  const gatewayOrderId = payment.gateway_order_id || recoveryCase.gateway_order_id;

  return (
    <div className="space-y-6">
      {/* Navigation & Header */}
      <div>
        <Link className="inline-flex items-center gap-1.5 text-xs font-semibold text-indigo-600 hover:text-indigo-800" to="/cases">
          <ArrowLeft className="size-3.5" /> Back to Recovery Cases
        </Link>
      </div>

      <Card className="p-6 bg-white border-slate-200">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs font-bold text-indigo-600">{recoveryCase.case_id}</span>
              <StatusBadge tone={stateTone(recoveryCase.state)}>{recoveryCase.state}</StatusBadge>
              {gatewayOrderId && (
                <StatusBadge tone="neutral" className="text-[10px] font-mono">
                  {gatewayOrderId}
                </StatusBadge>
              )}
            </div>
            <h1 className="mt-2 text-2xl font-bold text-slate-900">
              {formatMoney(recoveryCase.amount_at_risk.amount, true)} INR at Risk
            </h1>
            <p className="mt-1 text-xs text-slate-500">
              Payment ID: <code className="font-mono text-slate-700 font-semibold">{payment.payment_id}</code> | Created: {formatDateTime(recoveryCase.created_at)}
            </p>
          </div>

          {!isTerminal ? (
            <Button loading={runAction.loading} onClick={() => void runAction.run()}>
              <Play aria-hidden="true" className="size-4 mr-1.5" /> Run AI Recovery Cycle
            </Button>
          ) : (
            <StatusBadge tone={recoveryCase.state === 'RECOVERED' ? 'success' : 'neutral'}>
              {recoveryCase.state === 'RECOVERED' ? 'REVENUE RECOVERED' : 'TERMINAL CASE STATE'}
            </StatusBadge>
          )}
        </div>
      </Card>

      {/* 4 Primary Summary Cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          subtext={`Status: ${payment.status}`}
          title="Payment Amount"
          tone="amber"
          value={`${formatMoney(payment.money.amount, true)} INR`}
        />

        <MetricCard
          subtext={`Method: ${payment.payment_method}`}
          title="Failure Diagnosis"
          tone="default"
          value={humanize(recoveryCase.diagnosis?.failure_reason ?? payment.failure_reason ?? 'UNKNOWN')}
        />

        <MetricCard
          subtext={latestAction ? `ERV: ${latestAction.expected_recovery_value} minor units` : 'No action yet'}
          title="Recommended Action"
          tone="indigo"
          value={latestAction ? latestAction.action_type : 'PENDING'}
        />

        <MetricCard
          subtext={latestPolicy ? `Rule: ${latestPolicy.rule_id}` : 'Gate pending'}
          title="PolicyEngine Verdict"
          tone={latestPolicy?.outcome === 'APPROVED' ? 'success' : latestPolicy?.outcome === 'BLOCKED' ? 'rose' : 'amber'}
          value={latestPolicy ? latestPolicy.outcome : 'APPROVED'}
        />
      </div>

      {/* Razorpay Authentic Evidence Card */}
      <Card className="p-6 bg-white border-slate-200">
        <CardHeader className="px-0 pt-0 mb-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-bold text-indigo-600 uppercase tracking-wider">Gateway Evidence</span>
              <StatusBadge tone="info">RAZORPAY SANDBOX</StatusBadge>
            </div>
            <h2 className="text-base font-semibold text-slate-900 mt-0.5">Authoritative Checkout & Verification Evidence</h2>
            <p className="text-xs text-slate-500">Real transaction credentials, attempt records, and cryptographic verifications</p>
          </div>
          <CreditCard className="size-5 text-indigo-600" />
        </CardHeader>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 bg-slate-50 border border-slate-200/80 rounded-2xl p-4 text-xs">
          <div>
            <span className="text-slate-400 block text-[10px] font-medium uppercase">Razorpay Order ID</span>
            <span className="font-mono font-bold text-slate-800 mt-0.5 block break-all">
              {gatewayOrderId || 'Simulated Order'}
            </span>
          </div>

          <div>
            <span className="text-slate-400 block text-[10px] font-medium uppercase">Payment Method</span>
            <span className="font-semibold text-slate-800 mt-0.5 block">
              {payment.payment_method}
            </span>
          </div>

          <div>
            <span className="text-slate-400 block text-[10px] font-medium uppercase">Total Attempts</span>
            <span className="font-mono font-bold text-slate-800 mt-0.5 block">
              {payment.attempt_count} attempt(s)
            </span>
          </div>

          <div>
            <span className="text-slate-400 block text-[10px] font-medium uppercase">Outcome Verification</span>
            <span className="mt-0.5 block">
              {recoveryCase.state === 'RECOVERED' || latestOutcome?.recovered ? (
                <span className="inline-flex items-center gap-1 font-bold text-emerald-600">
                  <CheckCircle2 className="size-3.5" /> Verified Recovered
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 font-medium text-slate-600">
                  <AlertCircle className="size-3.5 text-amber-500" /> Unresolved
                </span>
              )}
            </span>
          </div>
        </div>

        {/* Attempt Log Snippet if attempts exist */}
        {payment.attempts && payment.attempts.length > 0 && (
          <div className="mt-4 border-t border-slate-100 pt-4">
            <h3 className="text-xs font-semibold text-slate-700 mb-2">Transaction Attempt History</h3>
            <div className="space-y-2">
              {payment.attempts.map((att) => (
                <div key={att.attempt_id} className="rounded-xl border border-slate-200 bg-white p-3 text-xs flex flex-col sm:flex-row sm:items-center justify-between gap-2 shadow-2xs">
                  <div>
                    <span className="font-mono font-semibold text-indigo-600">Attempt #{att.attempt_number}</span>
                    <span className="ml-2 font-medium text-slate-700">Status: {att.status}</span>
                    {att.failure_reason && (
                      <span className="ml-2 text-rose-600 font-medium">({humanize(att.failure_reason)})</span>
                    )}
                  </div>
                  <div className="font-mono text-[11px] text-slate-400">
                    {formatDateTime(att.attempted_at)}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </Card>

      {/* Main Evidence Grid */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Left Column: Intelligence Panel (2 cols) */}
        <div className="lg:col-span-2 space-y-6">
          {intelQuery.data ? <RecoveryIntelligencePanel intelligence={intelQuery.data} /> : null}
        </div>

        {/* Right Column: Audit Trail (1 col) */}
        <div className="space-y-6">
          <Card className="p-6 bg-white border-slate-200">
            <CardHeader className="px-0 pt-0 mb-4">
              <div>
                <h2 className="text-base font-semibold text-slate-900">Audit Trail</h2>
                <p className="text-xs text-slate-500">Append-only immutable record</p>
              </div>
              <ShieldCheck className="size-5 text-indigo-600" />
            </CardHeader>
            <AuditTimeline events={audit.events} />
          </Card>

          <Accordion title="Technical Raw Details & Evidence Payload">
            <pre className="overflow-x-auto rounded-lg bg-slate-50 border border-slate-200 p-3 font-mono text-[0.7rem] text-slate-700">
              {JSON.stringify({ recoveryCase, payment }, null, 2)}
            </pre>
          </Accordion>
        </div>
      </div>
    </div>
  );
}
