import { useEffect, useState } from 'react';
import { Award, Play, ShieldCheck } from 'lucide-react';
import { getJudgeDemo, getScenarios } from '@/api';
import type { DemoScenario, JudgeDemoResponse } from '@/types/api';
import { Button, Card, CardHeader, ErrorState, StatusBadge } from '@/components/ui';
import { formatMoney, humanize } from '@/utils/format';

export function JudgeDemoPage() {
  const [scenarios, setScenarios] = useState<DemoScenario[]>([]);
  const [selectedCaseId, setSelectedCaseId] = useState<string>('case_demo_a');
  const [demoData, setDemoData] = useState<JudgeDemoResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let ignore = false;
    async function loadScenarios() {
      try {
        const res = await getScenarios();
        if (!ignore && res.scenarios.length > 0) {
          setScenarios(res.scenarios);
        }
      } catch (err) {
        if (!ignore) setError(err instanceof Error ? err : new Error('Failed to load scenarios.'));
      }
    }
    void loadScenarios();
    return () => {
      ignore = true;
    };
  }, []);

  const loadJudgeDemoData = async (caseId: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await getJudgeDemo(caseId);
      setDemoData(res);
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Failed to load Judge Demo evaluation data.'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (selectedCaseId) {
      void loadJudgeDemoData(selectedCaseId);
    }
  }, [selectedCaseId]);

  const handleRunWorkflow = async () => {
    if (!selectedCaseId) return;
    await loadJudgeDemoData(selectedCaseId);
  };

  return (
    <div className="space-y-6">
      {/* Top Banner */}
      <Card className="overflow-hidden border-sky-400/30 bg-sky-500/[0.045] p-5 sm:p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge tone="success">BUILDATHON EVALUATION MODE</StatusBadge>
              <StatusBadge tone="info">8-STAGE PROOF PIPELINE</StatusBadge>
            </div>
            <div className="mt-3 flex items-start gap-3">
              <span className="grid size-10 shrink-0 place-items-center rounded-xl border border-sky-400/25 bg-sky-400/10 text-sky-300">
                <Award aria-hidden="true" className="size-5" />
              </span>
              <div>
                <h1 className="text-xl font-semibold tracking-tight text-slate-50 sm:text-2xl">
                  RevivePay Judge Demo Flow
                </h1>
                <p className="mt-1.5 text-sm leading-6 text-slate-300">
                  Step-by-step verification of real Razorpay Sandbox evidence, AI Copilot advisory recommendation,
                  mandatory PolicyEngine safety gating, simulated execution, and independent verification.
                </p>
              </div>
            </div>
          </div>
          <Button
            className="self-start xl:self-center"
            loading={loading}
            onClick={() => void handleRunWorkflow()}
          >
            <Play aria-hidden="true" className="size-4" />
            Run One Recovery Cycle
          </Button>
        </div>
      </Card>

      {/* Scenario Selector */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {scenarios.map((sc) => {
          const isSelected = sc.case_id === selectedCaseId;
          return (
            <button
              key={sc.case_id}
              className={`flex flex-col justify-between rounded-xl border p-4 text-left transition-all ${
                isSelected
                  ? 'border-sky-400/60 bg-sky-400/10 ring-2 ring-sky-400/30'
                  : 'border-white/[0.08] bg-ink-900/60 hover:border-white/20'
              }`}
              type="button"
              onClick={() => setSelectedCaseId(sc.case_id)}
            >
              <div>
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs font-bold uppercase tracking-wider text-sky-400">
                    Scenario {sc.key}
                  </span>
                  <StatusBadge tone={sc.current_state === 'RECOVERED' ? 'success' : 'neutral'}>
                    {sc.current_state}
                  </StatusBadge>
                </div>
                <h3 className="mt-2 text-sm font-semibold text-slate-100">{sc.title}</h3>
                <p className="mt-1 text-xs text-slate-400 line-clamp-2">{sc.narrative}</p>
              </div>
              <div className="mt-3 flex items-center justify-between text-xs font-mono text-slate-300">
                <span>{formatMoney(sc.amount.amount, true)} INR</span>
                <span className="text-slate-500">{humanize(sc.failure_reason)}</span>
              </div>
            </button>
          );
        })}
      </div>

      {error ? <ErrorState error={error.message} title="Judge Demo Evaluation Error" /> : null}

      {/* 8-Stage Pipeline Detail */}
      {demoData ? (
        <div className="space-y-6">
          {/* Summary Metric Cards */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Card className="p-4">
              <span className="text-[0.68rem] font-bold uppercase tracking-wider text-slate-400">
                Evidence Source
              </span>
              <div className="mt-2 flex items-center gap-2">
                <StatusBadge tone={demoData.is_real_razorpay ? 'warning' : 'neutral'}>
                  {demoData.is_real_razorpay ? 'REAL RAZORPAY SANDBOX' : 'SYNTHETIC SIMULATION'}
                </StatusBadge>
              </div>
              <p className="mt-2 text-xs truncate text-slate-400">{demoData.evidence_source}</p>
            </Card>

            <Card className="p-4">
              <span className="text-[0.68rem] font-bold uppercase tracking-wider text-slate-400">
                AI Copilot Advisory
              </span>
              <p className="mt-1 font-mono text-sm font-semibold text-sky-300">
                {demoData.ai_recommended_action}
              </p>
              <p className="mt-1 text-xs text-slate-400">
                Confidence: {(demoData.ai_confidence * 100).toFixed(0)}%
              </p>
            </Card>

            <Card className="p-4">
              <span className="text-[0.68rem] font-bold uppercase tracking-wider text-slate-400">
                PolicyEngine Verdict
              </span>
              <div className="mt-1">
                <StatusBadge
                  tone={
                    demoData.policy_outcome === 'APPROVED'
                      ? 'success'
                      : demoData.policy_outcome === 'BLOCKED'
                        ? 'danger'
                        : 'warning'
                  }
                >
                  {demoData.policy_outcome || 'PENDING'}
                </StatusBadge>
              </div>
              <p className="mt-1 text-xs truncate text-slate-400">
                Rule: {demoData.policy_rule_id || 'N/A'}
              </p>
            </Card>

            <Card className="p-4">
              <span className="text-[0.68rem] font-bold uppercase tracking-wider text-slate-400">
                Verified Recovered
              </span>
              <p className="mt-1 font-mono text-lg font-bold text-emerald-400">
                {formatMoney(demoData.recovered_amount.amount, true)} INR
              </p>
              <p className="mt-1 text-xs text-slate-400">State: {demoData.final_case_state}</p>
            </Card>
          </div>

          {/* 8-Stage Timeline Cards */}
          <Card className="p-6">
            <CardHeader className="mb-4">
              <div>
                <h2 className="text-base font-semibold text-slate-100">
                  8-Stage Proof Verification Trail
                </h2>
                <p className="mt-1 text-xs text-slate-400">
                  Detailed inspection of each stage from initial gateway risk detection to verified revenue recovery.
                </p>
              </div>
              <ShieldCheck className="size-5 text-sky-400" />
            </CardHeader>

            <div className="relative space-y-6 before:absolute before:left-4 before:top-3 before:bottom-3 before:w-0.5 before:bg-white/10">
              {demoData.stages.map((st) => {
                const isPassed = st.status === 'PASSED';
                const isBlocked = st.status === 'BLOCKED';
                const isEscalated = st.status === 'ESCALATED';

                return (
                  <div key={st.stage_number} className="relative pl-10">
                    <div
                      className={`absolute left-0 top-1.5 grid size-8 place-items-center rounded-full border text-xs font-bold ${
                        isPassed
                          ? 'border-emerald-400/40 bg-emerald-400/10 text-emerald-300'
                          : isBlocked
                            ? 'border-red-400/40 bg-red-400/10 text-red-300'
                            : isEscalated
                              ? 'border-amber-400/40 bg-amber-400/10 text-amber-300'
                              : 'border-slate-500/40 bg-slate-500/10 text-slate-300'
                      }`}
                    >
                      {st.stage_number}
                    </div>

                    <div className="rounded-xl border border-white/[0.08] bg-ink-900/60 p-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <h3 className="text-sm font-semibold text-slate-100">{st.name}</h3>
                          <span
                            className={`rounded px-2 py-0.5 font-mono text-[0.625rem] font-bold uppercase tracking-wider ${
                              st.label.includes('REAL RAZORPAY')
                                ? 'border border-amber-400/30 bg-amber-400/15 text-amber-300'
                                : st.label.includes('POLICY')
                                  ? 'border border-sky-400/30 bg-sky-400/15 text-sky-300'
                                  : st.label.includes('AI COPILOT')
                                    ? 'border border-purple-400/30 bg-purple-400/15 text-purple-300'
                                    : 'border border-slate-600 bg-slate-700/50 text-slate-300'
                            }`}
                          >
                            {st.label}
                          </span>
                        </div>
                        <StatusBadge
                          tone={isPassed ? 'success' : isBlocked ? 'danger' : isEscalated ? 'warning' : 'neutral'}
                        >
                          {st.status}
                        </StatusBadge>
                      </div>

                      <p className="mt-2 text-xs leading-5 text-slate-300">{st.detail}</p>

                      {st.payload && Object.keys(st.payload).length > 0 ? (
                        <div className="mt-3 overflow-x-auto rounded-lg bg-black/40 p-3 font-mono text-[0.725rem] text-slate-400">
                          <pre>{JSON.stringify(st.payload, null, 2)}</pre>
                        </div>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>
        </div>
      ) : null}
    </div>
  );
}
