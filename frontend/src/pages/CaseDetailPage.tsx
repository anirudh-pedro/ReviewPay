import { useMemo } from 'react';
import { ArrowLeft, Play, ShieldCheck } from 'lucide-react';
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

  return (
    <div className="space-y-6">
      {/* Navigation & Header */}
      <div>
        <Link className="inline-flex items-center gap-1.5 text-xs font-semibold text-sky-400 hover:text-sky-300" to="/cases">
          <ArrowLeft className="size-3.5" /> Back to Recovery Cases
        </Link>
      </div>

      <Card className="p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs font-bold text-sky-400">{recoveryCase.case_id}</span>
              <StatusBadge tone={stateTone(recoveryCase.state)}>{recoveryCase.state}</StatusBadge>
            </div>
            <h1 className="mt-2 text-2xl font-bold text-slate-50">
              {formatMoney(recoveryCase.amount_at_risk.amount, true)} INR at Risk
            </h1>
            <p className="mt-1 text-xs text-slate-400">
              Payment ID: <code className="font-mono text-slate-200">{payment.payment_id}</code> | Created: {formatDateTime(recoveryCase.created_at)}
            </p>
          </div>

          {!isTerminal ? (
            <Button loading={runAction.loading} onClick={() => void runAction.run()}>
              <Play aria-hidden="true" className="size-4" /> Run AI Recovery Cycle
            </Button>
          ) : (
            <StatusBadge tone={recoveryCase.state === 'RECOVERED' ? 'success' : 'neutral'}>
              TERMINAL CASE STATE
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
          tone="sky"
          value={humanize(recoveryCase.diagnosis?.failure_reason ?? 'UNKNOWN')}
        />

        <MetricCard
          subtext={latestAction ? `ERV: ${latestAction.expected_recovery_value} minor units` : 'No action yet'}
          title="Latest Selected Action"
          tone="indigo"
          value={latestAction ? latestAction.action_type : 'PENDING'}
        />

        <MetricCard
          subtext={latestPolicy ? `Rule: ${latestPolicy.rule_id}` : 'Gate pending'}
          title="Policy Verdict"
          tone={latestPolicy?.outcome === 'APPROVED' ? 'emerald' : latestPolicy?.outcome === 'BLOCKED' ? 'rose' : 'amber'}
          value={latestPolicy ? latestPolicy.outcome : 'APPROVED'}
        />
      </div>

      {/* Main Evidence Grid */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Left Column: Intelligence Panel (2 cols) */}
        <div className="lg:col-span-2 space-y-6">
          {intelQuery.data ? <RecoveryIntelligencePanel intelligence={intelQuery.data} /> : null}
        </div>

        {/* Right Column: Audit Trail (1 col) */}
        <div className="space-y-6">
          <Card className="p-6">
            <CardHeader className="px-0 pt-0 mb-4">
              <div>
                <h2 className="text-base font-semibold text-slate-100">Audit Trail</h2>
                <p className="text-xs text-slate-400">Append-only immutable record</p>
              </div>
              <ShieldCheck className="size-5 text-sky-400" />
            </CardHeader>
            <AuditTimeline events={audit.events} />
          </Card>

          <Accordion title="Technical Raw Details & Evidence Payload">
            <pre className="overflow-x-auto rounded bg-black/40 p-3 font-mono text-[0.7rem] text-slate-400">
              {JSON.stringify({ recoveryCase, payment }, null, 2)}
            </pre>
          </Accordion>
        </div>
      </div>
    </div>
  );
}
