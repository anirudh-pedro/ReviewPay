import { useEffect, useState } from 'react';
import { Beaker, SlidersHorizontal } from 'lucide-react';
import { getBaselineComparison, getScenarios, simulateStrategies } from '@/api';
import type { BaselineComparisonResponse, ScenarioOverrides, StrategyLabResponse } from '@/types/api';
import {
  Accordion,
  Card,
  CardHeader,
  ErrorState,
  MetricCard,
  Skeleton,
  StatusBadge,
} from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { formatMoney, formatPercent } from '@/utils/format';

export function StrategyLabPage() {
  const scenariosQuery = useApi(getScenarios, []);
  const baselineQuery = useApi(getBaselineComparison, []);
  const [selectedCaseId, setSelectedCaseId] = useState<string>('case_demo_a');
  const [labResult, setLabResult] = useState<StrategyLabResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);

  // Overrides form state
  const [retryDelay, setRetryDelay] = useState<number>(15);
  const [maxRetries, setMaxRetries] = useState<number>(2);

  const runSimulation = async (caseId: string, overrides: ScenarioOverrides = {}) => {
    setError(null);
    try {
      const res = await simulateStrategies(caseId, overrides);
      setLabResult(res);
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Strategy Lab simulation failed.'));
    }
  };

  useEffect(() => {
    if (selectedCaseId) {
      void runSimulation(selectedCaseId, {
        retry_later_delay_minutes: retryDelay,
        max_automatic_retries: maxRetries,
      });
    }
  }, [selectedCaseId, retryDelay, maxRetries]);

  if (scenariosQuery.loading || baselineQuery.loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-28 w-full rounded-xl" />
        <Skeleton className="h-96 w-full rounded-xl" />
      </div>
    );
  }

  const baselineData: BaselineComparisonResponse | undefined = baselineQuery.data ?? undefined;

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <Card className="p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <StatusBadge tone="info">WHAT-IF SIMULATION LAB</StatusBadge>
              <StatusBadge tone="success">READ-ONLY EVALUATION</StatusBadge>
            </div>
            <h1 className="mt-2 text-2xl font-bold text-slate-50">Strategy Lab</h1>
            <p className="mt-1 text-sm text-slate-300">
              Simulate & compare candidate recovery strategies with custom policy parameters without mutating real state.
            </p>
          </div>
        </div>
      </Card>

      {/* Baseline Uplift Benchmark Cards */}
      {baselineData ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <MetricCard
            subtext="Standard retries only"
            title="Baseline Recovered"
            tone="neutral"
            value={`${formatMoney(baselineData.baseline.projected_recovered.amount, true)} INR`}
          />

          <MetricCard
            subtext="ERV-ranked optimal selection"
            title="RevivePay Recovered"
            tone="emerald"
            value={`${formatMoney(baselineData.revivepay.projected_recovered.amount, true)} INR`}
          />

          <MetricCard
            subtext="Net recovered revenue delta"
            title="Recovered Uplift"
            tone="emerald"
            value={`+${formatMoney(baselineData.recovered_uplift.amount, true)} INR`}
          />

          <MetricCard
            subtext="Expected value gain"
            title="ERV Uplift"
            tone="sky"
            value={`+${formatMoney(baselineData.expected_value_uplift.amount, true)} INR`}
          />
        </div>
      ) : null}

      {/* Scenario Selector & Override Controls */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Controls Card (1 col) */}
        <Card className="p-6">
          <CardHeader className="px-0 pt-0 mb-4">
            <div>
              <h2 className="text-base font-semibold text-slate-100">Simulation Controls</h2>
              <p className="text-xs text-slate-400">Select scenario and adjust policy parameters</p>
            </div>
            <SlidersHorizontal className="size-5 text-sky-400" />
          </CardHeader>

          <div className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">Target Scenario Case</label>
              <select
                className="w-full h-9 rounded-lg border border-white/10 bg-slate-900 px-3 text-xs text-slate-200 outline-none focus:border-sky-400"
                value={selectedCaseId}
                onChange={(e) => setSelectedCaseId(e.target.value)}
              >
                {scenariosQuery.data?.scenarios.map((sc) => (
                  <option key={sc.case_id} value={sc.case_id}>
                    Scenario {sc.key}: {sc.title}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Retry Later Delay (Minutes): <span className="font-mono text-sky-400">{retryDelay}m</span>
              </label>
              <input
                className="w-full"
                max={60}
                min={5}
                step={5}
                type="range"
                value={retryDelay}
                onChange={(e) => setRetryDelay(Number(e.target.value))}
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Max Automatic Retries: <span className="font-mono text-sky-400">{maxRetries}</span>
              </label>
              <input
                className="w-full"
                max={5}
                min={1}
                step={1}
                type="range"
                value={maxRetries}
                onChange={(e) => setMaxRetries(Number(e.target.value))}
              />
            </div>
          </div>
        </Card>

        {/* Strategy Options Table (2 cols) */}
        <div className="lg:col-span-2">
          {error ? <ErrorState error={error} /> : null}

          {labResult ? (
            <Card className="p-6">
              <CardHeader className="px-0 pt-0 mb-4">
                <div>
                  <h2 className="text-base font-semibold text-slate-100">Evaluated Strategy Options</h2>
                  <p className="text-xs text-slate-400">
                    Recommended: <span className="font-mono text-sky-300 font-bold">{labResult.recommended_action}</span>
                  </p>
                </div>
                <Beaker className="size-5 text-sky-400" />
              </CardHeader>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="border-b border-white/10 text-[0.68rem] font-bold uppercase tracking-wider text-slate-400">
                    <tr>
                      <th className="pb-3">Action</th>
                      <th className="pb-3 text-right">Probability</th>
                      <th className="pb-3 text-right">Gross Recovery</th>
                      <th className="pb-3 text-right">Costs</th>
                      <th className="pb-3 text-right">ERV</th>
                      <th className="pb-3 text-right">Policy Verdict</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.04]">
                    {labResult.options.map((opt) => (
                      <tr key={opt.action} className={opt.is_recommended ? 'bg-sky-500/10' : 'hover:bg-white/[0.02]'}>
                        <td className="py-3 font-semibold text-slate-200">
                          {opt.action} {opt.is_recommended ? '⭐' : ''}
                        </td>
                        <td className="py-3 text-right font-mono text-slate-300">{formatPercent(opt.probability)}</td>
                        <td className="py-3 text-right font-mono text-slate-300">{formatMoney(opt.gross_expected_recovery.amount, true)}</td>
                        <td className="py-3 text-right font-mono text-rose-400">-{formatMoney(opt.intervention_cost.amount + opt.friction_penalty.amount, true)}</td>
                        <td className="py-3 text-right font-mono font-bold text-emerald-400">{formatMoney(opt.expected_recovery_value.amount, true)} INR</td>
                        <td className="py-3 text-right">
                          <StatusBadge tone={opt.policy_outcome === 'APPROVED' ? 'success' : 'danger'}>
                            {opt.policy_outcome}
                          </StatusBadge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <Accordion title="View Effective Settings & Model Provenance">
                <pre className="overflow-x-auto rounded bg-black/40 p-3 font-mono text-[0.7rem] text-slate-400">
                  {JSON.stringify({ effective_settings: labResult.effective_settings, model_version: labResult.model_version }, null, 2)}
                </pre>
              </Accordion>
            </Card>
          ) : null}
        </div>
      </div>
    </div>
  );
}
