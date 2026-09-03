import {
  ChevronRight,
  GitBranch,
  ShieldCheck,
  Sparkles,
  Target,
} from 'lucide-react';
import {
  Card,
  CardHeader,
  StatusBadge,
  cx,
} from '@/components/ui';
import type {
  RecoveryIntelligenceCandidate,
  RecoveryIntelligenceCounterfactualArm,
  RecoveryIntelligenceResponse,
} from '@/types/api';
import {
  formatMoney,
  formatPercent,
  formatSignedPercent,
  humanize,
} from '@/utils/format';
import { policyOutcomeTone, riskLevelTone } from '@/utils/recoveryPresentation';

function Metric({
  label,
  value,
  tone = 'text-slate-900',
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-2.5">
      <p className="text-[0.62rem] font-semibold uppercase tracking-[0.08em] text-slate-500">{label}</p>
      <p className={cx('mt-1 text-xs font-bold tabular-nums', tone)}>{value}</p>
    </div>
  );
}

function probabilityDelta(value: number): string {
  return `${value > 0 ? '+' : ''}${formatPercent(value)}`;
}

function DiagnosisChain({ intelligence }: { intelligence: RecoveryIntelligenceResponse }) {
  const { diagnosis } = intelligence;
  const stages = [
    {
      label: 'Failure detected',
      value: humanize(intelligence.failure_detected),
      tone: 'text-amber-800',
    },
    {
      label: 'Root cause',
      value: humanize(diagnosis.root_cause),
      tone: 'text-slate-900',
    },
    {
      label: 'Strategies evaluated',
      value: `${intelligence.candidates.length} checked`,
      tone: 'text-indigo-700',
    },
    {
      label: 'Advisory approach',
      value: intelligence.adaptive_recommended_action
        ? humanize(intelligence.adaptive_recommended_action)
        : 'No approved action',
      tone: 'text-emerald-700',
    },
  ];

  return (
    <section>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <GitBranch aria-hidden="true" className="size-4 text-indigo-600" />
            <p className="text-sm font-semibold text-slate-900">Structured diagnosis chain</p>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-slate-500">Read-only explanation from failure evidence through the policy-eligible advisory recommendation.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <StatusBadge tone={diagnosis.fallback_used ? 'warning' : 'info'}>
            {diagnosis.fallback_used ? 'Deterministic fallback' : 'Structured agent'}
          </StatusBadge>
          <StatusBadge tone={diagnosis.severity === 'HIGH' ? 'warning' : 'neutral'}>
            {humanize(diagnosis.severity)} severity
          </StatusBadge>
        </div>
      </div>
      <ol aria-label="Recovery intelligence diagnosis chain" className="mt-3 flex min-w-max gap-2 overflow-x-auto pb-1">
        {stages.map((stage, index) => (
          <li key={stage.label} className="flex items-stretch gap-2">
            <div className="w-40 rounded-xl border border-slate-200 bg-slate-50 p-3">
              <p className="font-mono text-[0.62rem] text-slate-400">{String(index + 1).padStart(2, '0')}</p>
              <p className="mt-0.5 text-[0.63rem] font-semibold uppercase tracking-[0.08em] text-slate-500">{stage.label}</p>
              <p className={cx('mt-1.5 text-xs font-semibold leading-tight', stage.tone)}>{stage.value}</p>
            </div>
            {index < stages.length - 1 ? <ChevronRight aria-hidden="true" className="mt-7 size-3.5 shrink-0 text-slate-400" /> : null}
          </li>
        ))}
      </ol>
      <div className="mt-3 grid gap-3 lg:grid-cols-[1.15fr_0.85fr]">
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5">
          <p className="text-[0.63rem] font-semibold uppercase tracking-[0.08em] text-slate-500">Agent reasoning</p>
          <p className="mt-1.5 text-xs leading-relaxed text-slate-700">{diagnosis.reasoning}</p>
          {diagnosis.fallback_reason ? <p className="mt-2 text-xs leading-relaxed text-amber-700">{diagnosis.fallback_reason}</p> : null}
        </div>
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5">
          <p className="text-[0.63rem] font-semibold uppercase tracking-[0.08em] text-slate-500">Customer context</p>
          <p className="mt-1.5 text-xs leading-relaxed text-slate-700">{diagnosis.customer_context.summary}</p>
          <div className="mt-2.5 flex flex-wrap gap-1.5 text-[0.68rem]">
            <StatusBadge tone="neutral">{diagnosis.customer_context.total_payments} prior payments</StatusBadge>
            <StatusBadge tone="neutral">{formatPercent(diagnosis.customer_context.success_rate)} history</StatusBadge>
            <StatusBadge tone="neutral">{humanize(diagnosis.customer_context.subscription_status)}</StatusBadge>
          </div>
        </div>
      </div>
    </section>
  );
}

function CandidateCard({ candidate }: { candidate: RecoveryIntelligenceCandidate }) {
  const evidence = candidate.historical_evidence;
  return (
    <article className={cx(
      'rounded-xl border p-4 bg-white shadow-2xs',
      candidate.is_adaptive_recommended ? 'border-indigo-300 ring-2 ring-indigo-50' : 'border-slate-200',
    )}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold text-slate-900">{humanize(candidate.action)}</p>
            {candidate.is_adaptive_recommended ? <StatusBadge tone="info">Advisory recommendation</StatusBadge> : null}
            {candidate.is_production_selected ? <StatusBadge tone="neutral">Live selection</StatusBadge> : null}
          </div>
          <p className="mt-1 text-xs leading-relaxed text-slate-500">{candidate.rejected_reason}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <StatusBadge tone={policyOutcomeTone(candidate.policy_outcome)}>{humanize(candidate.policy_outcome)}</StatusBadge>
          <StatusBadge tone={riskLevelTone(candidate.risk_level)}>{humanize(candidate.risk_level)} risk</StatusBadge>
        </div>
      </div>

      <div className="mt-3.5 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        <Metric label="Deterministic probability" value={formatPercent(candidate.deterministic_probability)} />
        <Metric label="Bounded learned probability" tone="text-indigo-600" value={formatPercent(candidate.learned_probability)} />
        <Metric label="Model delta" tone={candidate.probability_delta >= 0 ? 'text-emerald-700' : 'text-amber-800'} value={probabilityDelta(candidate.probability_delta)} />
        <Metric label="Adaptive expected recovery" tone="text-emerald-700" value={formatMoney(candidate.adaptive_expected_recovery_value)} />
        <Metric label="Intervention + friction" value={`${formatMoney(candidate.intervention_cost)} + ${formatMoney(candidate.friction_penalty)}`} />
        <Metric label="Model confidence" value={formatPercent(candidate.model_confidence)} />
      </div>

      <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-2.5">
        <p className="text-[0.63rem] font-semibold uppercase tracking-[0.08em] text-slate-500">Policy evidence</p>
        <p className="mt-0.5 font-mono text-[0.67rem] text-indigo-600 font-semibold">{candidate.policy_rule_id}</p>
        <p className="mt-1 text-xs leading-relaxed text-slate-600">{candidate.policy_reason}</p>
      </div>

      <details className="mt-2.5 rounded-lg border border-slate-200 bg-slate-50 p-2.5" open={candidate.is_adaptive_recommended}>
        <summary className="cursor-pointer text-xs font-semibold text-slate-700">Prediction factors and evidence</summary>
        <p className="mt-2 text-xs leading-relaxed text-slate-600">{evidence.statement}</p>
        <div className="mt-2.5 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          <Metric label="Synthetic samples" value={`${evidence.synthetic_successes}/${evidence.synthetic_samples}`} />
          <Metric label="Verified outcomes" value={`${evidence.verified_successes}/${evidence.verified_samples}`} />
          <Metric label="Comparable total" value={String(evidence.total_samples)} />
          <Metric label="Observed success rate" value={evidence.success_rate === null ? 'No result' : formatPercent(evidence.success_rate)} />
        </div>
        <div className="mt-2.5 space-y-1.5">
          {candidate.learning_factors.map((factor) => (
            <div key={factor.name} className="rounded-md border border-slate-200 bg-white p-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-mono text-[0.67rem] text-indigo-600 font-medium">{humanize(factor.name)}</p>
                <span className="font-mono text-[0.67rem] text-slate-600">{factor.value} · influence {formatPercent(factor.influence)}</span>
              </div>
              <p className="mt-0.5 text-xs text-slate-500">{factor.description}</p>
            </div>
          ))}
        </div>
      </details>
    </article>
  );
}

function CounterfactualArm({
  arm,
  tone,
}: {
  arm: RecoveryIntelligenceCounterfactualArm;
  tone: 'baseline' | 'revivepay';
}) {
  const advisory = tone === 'revivepay';
  return (
    <div className={cx('rounded-xl border p-4 bg-white shadow-2xs', advisory ? 'border-indigo-200 ring-2 ring-indigo-50' : 'border-slate-200')}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-slate-900">{arm.label}</p>
          <p className="mt-0.5 text-xs text-slate-500">{arm.action ? humanize(arm.action) : 'No policy-approved action'}</p>
        </div>
        {arm.policy_outcome ? <StatusBadge tone={policyOutcomeTone(arm.policy_outcome)}>{humanize(arm.policy_outcome)}</StatusBadge> : <StatusBadge tone="neutral">No action</StatusBadge>}
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        <Metric label="Recovery probability" value={formatPercent(arm.probability)} />
        <Metric label="Expected recovery" value={formatMoney(arm.expected_recovery_value)} />
        <Metric label="Projected recovered" tone={arm.simulated_would_recover ? 'text-emerald-700' : 'text-slate-700'} value={formatMoney(arm.projected_recovered)} />
      </div>
      <p className="mt-2.5 text-xs leading-relaxed text-slate-500">{arm.simulation_basis}</p>
    </div>
  );
}

function Counterfactual({ intelligence }: { intelligence: RecoveryIntelligenceResponse }) {
  const counterfactual = intelligence.counterfactual;
  return (
    <section>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Target aria-hidden="true" className="size-4 text-indigo-600" />
            <p className="text-sm font-semibold text-slate-900">Per-case counterfactual</p>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-slate-500">Baseline RETRY_NOW and the advisory action are evaluated on the same detection-time context.</p>
        </div>
        <StatusBadge tone="warning">Synthetic projection</StatusBadge>
      </div>
      <div className="mt-3.5 grid gap-3 xl:grid-cols-2">
        <CounterfactualArm arm={counterfactual.baseline} tone="baseline" />
        <CounterfactualArm arm={counterfactual.revivepay} tone="revivepay" />
      </div>
      <div className="mt-3.5 grid gap-2 sm:grid-cols-3">
        <Metric label="Projected recovery improvement" tone="text-emerald-700" value={formatMoney(counterfactual.projected_recovered_uplift)} />
        <Metric label="Projected recovery uplift" tone="text-indigo-600" value={counterfactual.projected_recovered_uplift_pct === null ? 'Not defined' : formatSignedPercent(counterfactual.projected_recovered_uplift_pct)} />
        <Metric label="Expected-value improvement" tone="text-indigo-600" value={formatMoney(counterfactual.expected_recovery_value_uplift)} />
      </div>
      <p className="mt-2.5 rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-xs text-amber-800">{counterfactual.notice}</p>
    </section>
  );
}

export function RecoveryIntelligencePanel({
  intelligence,
}: {
  intelligence: RecoveryIntelligenceResponse;
}) {
  const { model } = intelligence;

  return (
    <Card className="overflow-hidden border-slate-200 bg-white">
      <CardHeader>
        <div>
          <div className="flex items-center gap-2">
            <Sparkles aria-hidden="true" className="size-4 text-indigo-600" />
            <p className="text-sm font-semibold text-slate-900">Recovery Intelligence</p>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-slate-500">Bounded advisory evidence. The deterministic workflow and policy gate still control live execution.</p>
        </div>
        <StatusBadge tone="info">Advisory only</StatusBadge>
      </CardHeader>

      <div className="space-y-6 p-5 pt-3">
        <DiagnosisChain intelligence={intelligence} />

        <section className="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <ShieldCheck aria-hidden="true" className="size-4 text-indigo-600" />
                <p className="text-sm font-semibold text-slate-900">Bounded model provenance</p>
              </div>
              <p className="mt-1 text-xs leading-relaxed text-slate-500">The deterministic scorer is retained as the prior; verified outcomes calibrate advisory probability.</p>
            </div>
            <StatusBadge tone={model.fallback_used ? 'warning' : 'info'}>{model.fallback_used ? 'Deterministic fallback' : 'Bounded empirical Bayes'}</StatusBadge>
          </div>
          <div className="mt-3.5 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <Metric label="Training samples" value={String(model.training_samples)} />
            <Metric label="Synthetic projections" value={String(model.synthetic_samples)} />
            <Metric label="Verified outcomes" tone="text-emerald-700" value={String(model.verified_outcome_samples)} />
            <Metric label="Model version" value={model.model_version} />
          </div>
          <p className="mt-2 text-xs leading-relaxed text-slate-500">{model.bounded_window}</p>
          {model.fallback_reason ? <p className="mt-1.5 text-xs text-amber-800">{model.fallback_reason}</p> : null}
        </section>

        <section>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-sm font-semibold text-slate-900">Deterministic vs bounded learned candidates</p>
              <p className="mt-1 text-xs leading-relaxed text-slate-500">Advisory score is probability × recoverable amount − friction − action cost, after passing policy gate.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <StatusBadge tone="neutral">Live: {intelligence.production_selected_action ? humanize(intelligence.production_selected_action) : 'None'}</StatusBadge>
              <StatusBadge tone="info">Advisory: {intelligence.adaptive_recommended_action ? humanize(intelligence.adaptive_recommended_action) : 'None'}</StatusBadge>
            </div>
          </div>
          <p className="mt-2.5 rounded-lg border border-slate-200 bg-slate-50 p-2.5 text-xs leading-relaxed text-slate-700">{intelligence.adaptive_reasoning}</p>
          <div className="mt-3.5 grid gap-3 xl:grid-cols-2">
            {intelligence.candidates.map((candidate) => <CandidateCard key={candidate.action} candidate={candidate} />)}
          </div>
        </section>

        <Counterfactual intelligence={intelligence} />
        <p className="border-t border-slate-100 pt-3 text-[0.68rem] leading-relaxed text-slate-400">{intelligence.notice}</p>
      </div>
    </Card>
  );
}
