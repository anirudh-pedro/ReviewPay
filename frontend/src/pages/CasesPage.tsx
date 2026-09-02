import { useMemo, useState } from 'react';
import { ChevronRight, Search } from 'lucide-react';
import { Link } from 'react-router-dom';
import { listCases } from '@/api';
import {
  Card,
  ErrorState,
  Skeleton,
  StatusBadge,
} from '@/components/ui';
import type { StatusTone } from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import type { CaseState, RecoveryCaseSummary } from '@/types/api';
import { formatDateTime, formatMoney } from '@/utils/format';

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
  const casesQuery = useApi(() => listCases({ limit: 100 }), []);

  const cases: RecoveryCaseSummary[] = useMemo(() => {
    if (!casesQuery.data) return [];
    return casesQuery.data.items.filter((c) => {
      const matchesState = selectedState === 'ALL' || c.state === selectedState;
      const matchesSearch =
        !search ||
        c.case_id.toLowerCase().includes(search.toLowerCase()) ||
        c.payment_id.toLowerCase().includes(search.toLowerCase()) ||
        c.state.toLowerCase().includes(search.toLowerCase());
      return matchesState && matchesSearch;
    });
  }, [casesQuery.data, selectedState, search]);

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

  return (
    <div className="space-y-6">
      {/* Header & Controls */}
      <Card className="p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-xl font-bold text-slate-50">Recovery Cases</h1>
            <p className="mt-1 text-xs text-slate-400">
              Inspect active risk cases, decision explanations, policy gating, and verification history.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {/* Search */}
            <div className="relative">
              <Search className="absolute left-3 top-2.5 size-4 text-slate-500" />
              <input
                className="h-9 w-48 rounded-lg border border-white/10 bg-slate-900 pl-9 pr-3 text-xs text-slate-200 outline-none focus:border-sky-400 focus:ring-1 focus:ring-sky-400"
                placeholder="Search cases..."
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>

            {/* State Filter */}
            <select
              className="h-9 rounded-lg border border-white/10 bg-slate-900 px-3 text-xs text-slate-200 outline-none focus:border-sky-400"
              value={selectedState}
              onChange={(e) => setSelectedState(e.target.value)}
            >
              <option value="ALL">All States</option>
              <option value="DETECTED">Detected</option>
              <option value="DIAGNOSED">Diagnosed</option>
              <option value="APPROVED">Approved</option>
              <option value="BLOCKED">Blocked</option>
              <option value="RECOVERED">Recovered</option>
              <option value="ESCALATED">Escalated</option>
              <option value="STOPPED">Stopped</option>
            </select>
          </div>
        </div>
      </Card>

      {/* Cases Table */}
      <Card className="p-6">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-white/10 text-[0.68rem] font-bold uppercase tracking-wider text-slate-400">
              <tr>
                <th className="pb-3">Case ID</th>
                <th className="pb-3">Payment ID</th>
                <th className="pb-3">Amount at Risk</th>
                <th className="pb-3">Status</th>
                <th className="pb-3">Created</th>
                <th className="pb-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {cases.length === 0 ? (
                <tr>
                  <td className="py-8 text-center text-slate-400" colSpan={6}>
                    No recovery cases found matching criteria.
                  </td>
                </tr>
              ) : (
                cases.map((c) => (
                  <tr key={c.case_id} className="hover:bg-white/[0.02] transition-colors">
                    <td className="py-3 font-mono font-semibold text-sky-400">{c.case_id}</td>
                    <td className="py-3 font-mono text-slate-400">{c.payment_id}</td>
                    <td className="py-3 font-mono font-bold text-slate-200">
                      {formatMoney(c.amount_at_risk.amount, true)} INR
                    </td>
                    <td className="py-3">
                      <StatusBadge tone={stateTone(c.state)}>{c.state}</StatusBadge>
                    </td>
                    <td className="py-3 text-slate-400">{formatDateTime(c.created_at)}</td>
                    <td className="py-3 text-right">
                      <Link
                        className="inline-flex items-center gap-1 font-semibold text-sky-400 hover:text-sky-300"
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
    </div>
  );
}
