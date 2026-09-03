import { useMemo, useState } from 'react';
import { ChevronRight, Search, Zap, CreditCard, RefreshCw, Trash2 } from 'lucide-react';
import { Link } from 'react-router-dom';
import { listCases, clearCases } from '@/api';
import {
  Button,
  Card,
  ErrorState,
  Skeleton,
  StatusBadge,
} from '@/components/ui';
import type { StatusTone } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import type { CaseState, RecoveryCaseSummary } from '@/types/api';
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

export function CasesPage() {
  const [selectedState, setSelectedState] = useState<string>('ALL');
  const [search, setSearch] = useState('');
  const [clearing, setClearing] = useState(false);

  // Retrieve only authentic cases created via the Razorpay Recovery Simulator / Sandbox
  const casesQuery = useApi(() => listCases({ limit: 100, real_only: true }), []);

  const cases: RecoveryCaseSummary[] = useMemo(() => {
    if (!casesQuery.data) return [];
    return casesQuery.data.items.filter((c) => {
      // Strictly exclude any synthetic or seeded demo items
      if (c.is_synthetic === true || c.case_id.startsWith('case_seed_') || c.case_id.startsWith('case_demo_')) {
        return false;
      }
      const matchesState = selectedState === 'ALL' || c.state === selectedState;
      const q = search.toLowerCase().trim();
      const matchesSearch =
        !q ||
        c.case_id.toLowerCase().includes(q) ||
        c.payment_id.toLowerCase().includes(q) ||
        (c.gateway_order_id && c.gateway_order_id.toLowerCase().includes(q)) ||
        (c.failure_reason && c.failure_reason.toLowerCase().includes(q)) ||
        c.state.toLowerCase().includes(q);
      return matchesState && matchesSearch;
    });
  }, [casesQuery.data, selectedState, search]);

  const handleClear = async () => {
    setClearing(true);
    try {
      await clearCases();
      await casesQuery.refetch();
    } finally {
      setClearing(false);
    }
  };

  if (casesQuery.loading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-12 w-full rounded-xl" />
        <Skeleton className="h-96 w-full rounded-xl" />
      </div>
    );
  }

  if (casesQuery.error) {
    return (
      <ErrorState
        error={casesQuery.error}
        onRetry={() => void casesQuery.refetch()}
      />
    );
  }

  const rawCount = casesQuery.data?.items?.filter(
    (c) => !(c.is_synthetic === true || c.case_id.startsWith('case_seed_') || c.case_id.startsWith('case_demo_')),
  ).length ?? 0;

  return (
    <div className="space-y-6">
      {/* Header & Controls */}
      <Card className="p-5 bg-white border-slate-200">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-xl font-bold text-slate-900">Recovery Cases & Audit</h1>
            <p className="text-xs text-slate-500 mt-0.5">
              Live cases initiated through Razorpay Sandbox Checkout. Filter by lifecycle state or search.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-slate-400" />
              <input
                className="h-9 w-64 rounded-lg border border-slate-300 bg-white pl-9 pr-3 text-xs text-slate-900 outline-none focus:border-indigo-600 focus:ring-2 focus:ring-indigo-100"
                placeholder="Search case, order, reason..."
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => void casesQuery.refetch()}
              title="Refresh case queue"
            >
              <RefreshCw className="size-3.5" />
            </Button>
            {rawCount > 0 && (
              <Button
                size="sm"
                variant="ghost"
                className="text-rose-600 hover:text-rose-700 hover:bg-rose-50"
                loading={clearing}
                onClick={() => void handleClear()}
                title="Clear all cases"
              >
                <Trash2 className="size-3.5 mr-1" /> Clear Queue
              </Button>
            )}
          </div>
        </div>

        {/* State Filter Pills */}
        <div className="mt-4 flex flex-wrap gap-1.5 border-t border-slate-100 pt-3">
          {['ALL', 'RECOVERED', 'FAILED', 'ESCALATED', 'STOPPED', 'BLOCKED'].map((state) => (
            <button
              key={state}
              type="button"
              onClick={() => setSelectedState(state)}
              className={`rounded-lg px-3 py-1 text-xs font-semibold transition cursor-pointer ${
                selectedState === state
                  ? 'bg-indigo-600 text-white shadow-2xs'
                  : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
            >
              {state}
            </button>
          ))}
        </div>
      </Card>

      {/* Cases Table or Empty State */}
      {rawCount === 0 ? (
        /* Professional Empty State */
        <Card className="p-12 text-center bg-white border-slate-200">
          <div className="mx-auto size-14 rounded-2xl bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600 mb-4 shadow-2xs">
            <CreditCard className="size-7" />
          </div>
          <h2 className="text-lg font-bold text-slate-900">
            No recovery cases yet — run a Razorpay payment through the Recovery Simulator.
          </h2>
          <p className="mt-1.5 text-xs text-slate-500 max-w-md mx-auto">
            This page exclusively displays real cases persisted by the Razorpay Sandbox recovery pipeline.
            Make a checkout attempt and simulate a failure to watch RevivePay take over.
          </p>
          <div className="mt-6 flex justify-center gap-3">
            <Link to="/simulator">
              <Button>
                <Zap className="size-4 mr-1.5" /> Open Recovery Simulator
              </Button>
            </Link>
          </div>
        </Card>
      ) : (
        <Card className="overflow-hidden bg-white border-slate-200">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-slate-200 bg-slate-50 font-semibold text-slate-600 uppercase tracking-wider text-[11px]">
                <tr>
                  <th className="px-5 py-3">Case ID</th>
                  <th className="py-3">Razorpay Order</th>
                  <th className="py-3">Amount at Risk</th>
                  <th className="py-3">Failure Reason</th>
                  <th className="py-3">State</th>
                  <th className="py-3">Created</th>
                  <th className="px-5 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-700">
                {cases.length === 0 ? (
                  <tr>
                    <td className="py-12 text-center text-slate-500" colSpan={7}>
                      No cases match the selected filter “{selectedState}”
                      {search ? ` with query “${search}”` : ''}.
                    </td>
                  </tr>
                ) : (
                  cases.map((c) => (
                    <tr key={c.case_id} className="hover:bg-slate-50/70 transition-colors">
                      <td className="px-5 py-3 font-mono font-semibold text-indigo-600">
                        {c.case_id}
                      </td>
                      <td className="py-3 font-mono text-slate-600">
                        {c.gateway_order_id ? (
                          <span className="bg-slate-50 border border-slate-200 px-1.5 py-0.5 rounded text-[11px]">
                            {c.gateway_order_id}
                          </span>
                        ) : (
                          c.payment_id
                        )}
                      </td>
                      <td className="py-3 font-mono font-bold text-slate-900">
                        {formatMoney(c.amount_at_risk.amount, true)} INR
                      </td>
                      <td className="py-3 font-medium text-slate-800">
                        {c.failure_reason ? humanize(c.failure_reason) : 'Recorded Failure'}
                      </td>
                      <td className="py-3">
                        <StatusBadge tone={stateTone(c.state)}>{c.state}</StatusBadge>
                      </td>
                      <td className="py-3 text-slate-500">{formatDateTime(c.created_at)}</td>
                      <td className="px-5 py-3 text-right">
                        <Link
                          className="inline-flex items-center gap-1 font-semibold text-indigo-600 hover:text-indigo-800"
                          to={`/cases/${c.case_id}`}
                        >
                          Inspect <ChevronRight className="size-3.5" />
                        </Link>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
