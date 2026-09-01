import { useMemo, useState } from 'react';
import {
  ArrowUpDown,
  ChevronRight,
  CircleAlert,
  Filter,
  Search,
  SlidersHorizontal,
  X,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { getCaseExplorerPage } from '@/api';
import type { CaseExplorerRow } from '@/api';
import {
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  Skeleton,
  StatusBadge,
  buttonClassName,
  cx,
} from '@/components/ui';
import { useApi } from '@/hooks/useApi';
import { useDemoData } from '@/contexts/DemoDataContext';
import type { CaseState, PolicyOutcome, RiskLevel } from '@/types/api';
import { formatDateTime, formatMoney, humanize } from '@/utils/format';
import {
  caseStateTone,
  policyOutcomeTone,
  riskLevelTone,
} from '@/utils/recoveryPresentation';

const CASE_LIMIT = 50;

const CASE_STATES: CaseState[] = [
  'DETECTED',
  'DIAGNOSING',
  'DIAGNOSED',
  'EVALUATING',
  'DECISION_READY',
  'POLICY_CHECK',
  'APPROVED',
  'BLOCKED',
  'SCHEDULED',
  'EXECUTING',
  'VERIFYING',
  'RECOVERED',
  'FAILED',
  'ESCALATED',
  'STOPPED',
];

type StateFilter = CaseState | 'ALL';
type PolicyFilter = PolicyOutcome | 'ALL';
type RiskFilter = RiskLevel | 'ALL';
type SortOrder = 'updated' | 'amount' | 'recovered';

function latestPolicy(row: CaseExplorerRow): PolicyOutcome | null {
  return row.detail?.latest_policy?.outcome ?? row.detail?.latest_action?.policy_outcome ?? null;
}

function latestAction(row: CaseExplorerRow): string | null {
  return row.detail?.latest_action?.action_type ?? row.detail?.latest_explanation?.selected_action ?? null;
}

function failureReason(row: CaseExplorerRow): string | null {
  return row.detail?.diagnosis?.failure_reason ?? null;
}

function rowMatchesQuery(row: CaseExplorerRow, query: string): boolean {
  if (!query) return true;

  const searchable = [
    row.summary.case_id,
    row.summary.payment_id,
    row.summary.state,
    failureReason(row) ?? '',
    latestAction(row) ?? '',
    latestPolicy(row) ?? '',
    row.detail?.latest_action?.risk_level ?? '',
  ]
    .join(' ')
    .toLowerCase();

  return searchable.includes(query);
}

function CaseExplorerSkeleton() {
  return (
    <div aria-busy="true" className="space-y-5" role="status">
      <span className="sr-only">Loading recovery cases.</span>
      <Card className="p-5 sm:p-6">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="mt-3 h-4 w-full max-w-2xl" />
        <div className="mt-6 grid gap-3 lg:grid-cols-[1.4fr_repeat(4,minmax(0,1fr))]">
          {[0, 1, 2, 3, 4].map((item) => (
            <Skeleton key={item} className="h-10 w-full" />
          ))}
        </div>
      </Card>
      <Card className="overflow-hidden">
        <div className="space-y-4 p-5">
          {[0, 1, 2, 3, 4, 5].map((item) => (
            <div key={item} className="grid grid-cols-[1.5fr_repeat(5,minmax(5rem,1fr))] items-center gap-5 border-b border-white/[0.05] pb-4 last:border-0">
              <div><Skeleton className="h-3 w-28" /><Skeleton className="mt-2 h-3 w-20" /></div>
              {[0, 1, 2, 3, 4].map((column) => <Skeleton key={column} className="h-6 w-full" />)}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

function FilterSelect({
  children,
  label,
  onChange,
  value,
}: {
  children: React.ReactNode;
  label: string;
  onChange: (value: string) => void;
  value: string;
}) {
  return (
    <label className="block min-w-0">
      <span className="mb-1.5 block text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-slate-500">{label}</span>
      <select
        className="h-10 w-full appearance-none rounded-lg border border-white/[0.08] bg-ink-800 px-3 text-sm text-slate-200 outline-none transition-colors hover:border-white/[0.16] focus:border-accent focus:ring-2 focus:ring-accent/20"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {children}
      </select>
    </label>
  );
}

function DetailsUnavailable({ row }: { row: CaseExplorerRow }) {
  if (!row.detailError) return null;

  return (
    <span className="inline-flex items-center gap-1 text-[0.68rem] text-amber-300" title={row.detailError.message}>
      <CircleAlert aria-hidden="true" className="size-3" />
      Detail unavailable
    </span>
  );
}

export function CasesPage() {
  const { dataVersion } = useDemoData();
  const [stateFilter, setStateFilter] = useState<StateFilter>('ALL');
  const [policyFilter, setPolicyFilter] = useState<PolicyFilter>('ALL');
  const [riskFilter, setRiskFilter] = useState<RiskFilter>('ALL');
  const [reasonFilter, setReasonFilter] = useState('ALL');
  const [sortOrder, setSortOrder] = useState<SortOrder>('updated');
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);

  const requestState = stateFilter === 'ALL' ? undefined : stateFilter;
  const casePage = useApi(
    (signal) => getCaseExplorerPage({
      includeDetails: true,
      limit: CASE_LIMIT,
      offset,
      state: requestState,
    }, signal),
    [requestState, offset, dataVersion],
  );

  const rows = casePage.data?.items ?? [];
  const loadedOffset = casePage.data?.offset ?? offset;
  const loadedLimit = casePage.data?.limit ?? CASE_LIMIT;
  const totalCases = casePage.data?.total ?? 0;
  const totalPages = totalCases ? Math.ceil(totalCases / loadedLimit) : 0;
  const currentPage = totalPages ? Math.min(Math.floor(loadedOffset / loadedLimit) + 1, totalPages) : 0;
  const pageStart = rows.length ? Math.min(loadedOffset + 1, totalCases) : 0;
  const pageEnd = rows.length ? Math.min(loadedOffset + rows.length, totalCases) : 0;
  const hasPreviousPage = loadedOffset > 0;
  const hasNextPage = loadedOffset + rows.length < totalCases;
  const failureReasons = useMemo(
    () => Array.from(new Set(rows.map(failureReason).filter((reason): reason is string => Boolean(reason)))).sort(),
    [rows],
  );

  const filteredRows = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();

    return [...rows]
      .filter((row) => rowMatchesQuery(row, normalizedQuery))
      .filter((row) => policyFilter === 'ALL' || latestPolicy(row) === policyFilter)
      .filter((row) => riskFilter === 'ALL' || row.detail?.latest_action?.risk_level === riskFilter)
      .filter((row) => reasonFilter === 'ALL' || failureReason(row) === reasonFilter)
      .sort((left, right) => {
        if (sortOrder === 'amount') {
          return right.summary.amount_at_risk.amount - left.summary.amount_at_risk.amount;
        }
        if (sortOrder === 'recovered') {
          return (right.detail?.latest_outcome?.recovered_amount ?? -1) - (left.detail?.latest_outcome?.recovered_amount ?? -1);
        }
        return new Date(right.summary.updated_at).getTime() - new Date(left.summary.updated_at).getTime();
      });
  }, [policyFilter, query, reasonFilter, riskFilter, rows, sortOrder]);

  const filtersApplied = stateFilter !== 'ALL' || policyFilter !== 'ALL' || riskFilter !== 'ALL' || reasonFilter !== 'ALL' || Boolean(query);

  function clearFilters() {
    setStateFilter('ALL');
    setPolicyFilter('ALL');
    setRiskFilter('ALL');
    setReasonFilter('ALL');
    setQuery('');
    setSortOrder('updated');
    setOffset(0);
  }

  function handleStateFilter(value: StateFilter) {
    setStateFilter(value);
    setOffset(0);
  }

  function previousPage() {
    setOffset((current) => Math.max(0, current - CASE_LIMIT));
  }

  function nextPage() {
    setOffset((current) => current + CASE_LIMIT);
  }

  if (casePage.loading && !casePage.data) return <CaseExplorerSkeleton />;

  if (casePage.error && !casePage.data) {
    return (
      <ErrorState
        error={casePage.error}
        onRetry={casePage.refetch}
        title="Case Explorer is unavailable"
      />
    );
  }

  return (
    <div className="space-y-5">
      <Card className="surface-grid overflow-hidden p-5 sm:p-6">
        <div className="flex flex-col justify-between gap-5 xl:flex-row xl:items-end">
          <div className="max-w-2xl">
            <div className="flex items-center gap-2">
              <div className="grid size-8 place-items-center rounded-lg border border-accent/25 bg-accent/10 text-accent">
                <Filter aria-hidden="true" className="size-4" />
              </div>
              <p className="text-sm font-semibold text-slate-100">Recovery Case Explorer</p>
              {casePage.data ? <StatusBadge tone="info">{totalCases} server cases</StatusBadge> : null}
            </div>
            <h1 className="mt-4 text-xl font-semibold tracking-tight text-slate-50 sm:text-2xl">Find the decision behind every rupee at risk.</h1>
            <p className="mt-2 text-sm leading-6 text-slate-400">
              Browse the live recovery queue, inspect the action the backend selected, and open the full evidence trail.
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <SlidersHorizontal aria-hidden="true" className="size-3.5 text-accent" />
            <span>State filtering is server-backed; detail filters apply to the loaded page.</span>
          </div>
        </div>

        <div className="mt-6 grid gap-3 md:grid-cols-2 xl:grid-cols-[1.65fr_repeat(4,minmax(0,1fr))]">
          <label className="relative block min-w-0 md:col-span-2 xl:col-span-1">
            <span className="mb-1.5 block text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-slate-500">Search cases</span>
            <Search aria-hidden="true" className="pointer-events-none absolute bottom-3 left-3 size-4 text-slate-500" />
            <input
              className="h-10 w-full rounded-lg border border-white/[0.08] bg-ink-800 pl-9 pr-3 text-sm text-slate-100 outline-none transition-colors placeholder:text-slate-600 hover:border-white/[0.16] focus:border-accent focus:ring-2 focus:ring-accent/20"
              placeholder="Case, payment, action, reason…"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <FilterSelect label="State" value={stateFilter} onChange={(value) => handleStateFilter(value as StateFilter)}>
            <option value="ALL">All states</option>
            {CASE_STATES.map((state) => <option key={state} value={state}>{humanize(state)}</option>)}
          </FilterSelect>
          <FilterSelect label="Policy" value={policyFilter} onChange={(value) => setPolicyFilter(value as PolicyFilter)}>
            <option value="ALL">All verdicts</option>
            <option value="APPROVED">Approved</option>
            <option value="BLOCKED">Blocked</option>
            <option value="ESCALATED">Escalated</option>
          </FilterSelect>
          <FilterSelect label="Failure reason" value={reasonFilter} onChange={setReasonFilter}>
            <option value="ALL">All reasons</option>
            {failureReasons.map((reason) => <option key={reason} value={reason}>{humanize(reason)}</option>)}
          </FilterSelect>
          <FilterSelect label="Risk level" value={riskFilter} onChange={(value) => setRiskFilter(value as RiskFilter)}>
            <option value="ALL">All risk levels</option>
            <option value="HIGH">High</option>
            <option value="MEDIUM">Medium</option>
            <option value="LOW">Low</option>
          </FilterSelect>
        </div>
      </Card>

      <Card className="overflow-hidden">
        <CardHeader className="items-center pb-4">
          <div>
            <p className="text-sm font-semibold text-slate-100">Live recovery queue</p>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              {casePage.loading && casePage.data
                ? 'Loading the next server page…'
                : `Showing ${filteredRows.length} of ${rows.length} cases on this page${totalCases !== rows.length ? ` · ${totalCases} server-matched cases` : ''}.`}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {filtersApplied ? (
              <button className={buttonClassName('ghost', 'sm')} type="button" onClick={clearFilters}>
                <X aria-hidden="true" className="size-3.5" />
                Clear
              </button>
            ) : null}
            <label className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-white/[0.07] bg-ink-800 px-2.5 text-xs text-slate-300">
              <ArrowUpDown aria-hidden="true" className="size-3.5 text-slate-500" />
              <span className="sr-only">Sort cases</span>
              <select
                className="max-w-28 appearance-none bg-transparent font-medium outline-none"
                value={sortOrder}
                onChange={(event) => setSortOrder(event.target.value as SortOrder)}
              >
                <option value="updated">Recently updated</option>
                <option value="amount">At-risk amount</option>
                <option value="recovered">Recovered amount</option>
              </select>
            </label>
          </div>
        </CardHeader>

        {casePage.error ? (
          <div className="border-b border-amber-400/10 bg-amber-400/[0.035] px-5 py-3 text-xs leading-5 text-amber-200">
            The latest refresh was incomplete. Previously loaded cases are still shown; retry to refresh the source data.
            <button className="ml-2 font-semibold text-amber-100 underline decoration-amber-300/40 underline-offset-2" type="button" onClick={casePage.refetch}>Retry</button>
          </div>
        ) : null}

        {rows.length === 0 ? (
          <EmptyState
            compact
            description="The backend returned no recovery cases for this state. Reset the demo dataset or choose another case state to continue."
            icon={Filter}
            title="No recovery cases are available"
          />
        ) : filteredRows.length === 0 ? (
          <EmptyState
            compact
            action={<button className={buttonClassName('secondary', 'sm')} type="button" onClick={clearFilters}>Clear filters</button>}
            description="No loaded case matches these client-side filters. Clear a filter or search by a different identifier."
            icon={Search}
            title="No matching cases"
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1080px] border-collapse text-left">
              <thead className="border-y border-white/[0.055] bg-white/[0.018] text-[0.64rem] font-semibold uppercase tracking-[0.12em] text-slate-500">
                <tr>
                  <th className="px-5 py-3">Case</th>
                  <th className="px-4 py-3">At risk</th>
                  <th className="px-4 py-3">Failure / diagnosis</th>
                  <th className="px-4 py-3">Recommended action</th>
                  <th className="px-4 py-3">Risk</th>
                  <th className="px-4 py-3">Policy gate</th>
                  <th className="px-4 py-3">Recovered</th>
                  <th className="px-4 py-3">State</th>
                  <th className="px-5 py-3 text-right">Open</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.045]">
                {filteredRows.map((row) => {
                  const action = latestAction(row);
                  const policy = latestPolicy(row);
                  const reason = failureReason(row);
                  const outcome = row.detail?.latest_outcome;
                  const risk = row.detail?.latest_action?.risk_level;

                  return (
                    <tr key={row.summary.case_id} className="group transition-colors hover:bg-white/[0.018]">
                      <td className="px-5 py-4 align-top">
                        <Link className="group/link inline-flex items-center gap-1.5 font-mono text-xs font-semibold text-sky-300 hover:text-sky-200" to={`/cases/${row.summary.case_id}`}>
                          {row.summary.case_id}
                          <ChevronRight aria-hidden="true" className="size-3.5 transition-transform group-hover/link:translate-x-0.5" />
                        </Link>
                        <p className="mt-1.5 font-mono text-[0.67rem] text-slate-600">{row.summary.payment_id}</p>
                        <p className="mt-1.5 text-[0.68rem] text-slate-500">Updated {formatDateTime(row.summary.updated_at)}</p>
                      </td>
                      <td className="px-4 py-4 align-top font-mono text-sm font-semibold tabular-nums text-amber-100">{formatMoney(row.summary.amount_at_risk)}</td>
                      <td className="px-4 py-4 align-top">
                        {reason ? <span className="text-sm text-slate-200">{humanize(reason)}</span> : <DetailsUnavailable row={row} />}
                        {row.detail?.diagnosis?.category ? <p className="mt-1 text-[0.68rem] text-slate-500">{humanize(row.detail.diagnosis.category)} · {humanize(row.detail.diagnosis.transience)}</p> : null}
                      </td>
                      <td className="px-4 py-4 align-top">
                        {action ? <span className="text-sm font-medium text-slate-100">{humanize(action)}</span> : <span className="text-sm text-slate-600">Awaiting evaluation</span>}
                        {row.detail?.latest_explanation?.expected_recovery_value !== undefined ? <p className="mt-1 font-mono text-[0.68rem] tabular-nums text-slate-500">ERV {formatMoney(row.detail.latest_explanation.expected_recovery_value)}</p> : null}
                      </td>
                      <td className="px-4 py-4 align-top">
                        {risk ? <StatusBadge tone={riskLevelTone(risk)}>{humanize(risk)}</StatusBadge> : <span className="text-xs text-slate-600">—</span>}
                      </td>
                      <td className="px-4 py-4 align-top">
                        {policy ? <StatusBadge tone={policyOutcomeTone(policy)}>{humanize(policy)}</StatusBadge> : <span className="text-xs text-slate-600">Not evaluated</span>}
                        {row.detail?.latest_policy?.rule_id ? <p className="mt-1 max-w-36 truncate font-mono text-[0.65rem] text-slate-600" title={row.detail.latest_policy.rule_id}>{row.detail.latest_policy.rule_id}</p> : null}
                      </td>
                      <td className="px-4 py-4 align-top">
                        {outcome ? <span className={cx('font-mono text-sm font-semibold tabular-nums', outcome.recovered ? 'text-green-300' : 'text-slate-400')}>{formatMoney(outcome.recovered_amount)}</span> : <span className="text-xs text-slate-600">Not verified</span>}
                      </td>
                      <td className="px-4 py-4 align-top"><StatusBadge tone={caseStateTone(row.summary.state)}>{humanize(row.summary.state)}</StatusBadge></td>
                      <td className="px-5 py-4 text-right align-top">
                        <Link aria-label={`Inspect recovery case ${row.summary.case_id}`} className={buttonClassName('ghost', 'sm', 'group-hover:border-white/[0.08]')} to={`/cases/${row.summary.case_id}`}>
                          Inspect
                          <ChevronRight aria-hidden="true" className="size-3.5" />
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {casePage.data && totalCases > 0 ? (
          <footer className="flex flex-col justify-between gap-3 border-t border-white/[0.055] px-5 py-3.5 text-xs text-slate-500 sm:flex-row sm:items-center">
            <p>
              Showing {pageStart}–{pageEnd} of {totalCases} server case{totalCases === 1 ? '' : 's'}.
            </p>
            <div className="flex items-center gap-2">
              <button
                className={buttonClassName('ghost', 'sm')}
                disabled={!hasPreviousPage || casePage.loading}
                type="button"
                onClick={previousPage}
              >
                Previous
              </button>
              <span className="min-w-20 text-center font-mono text-[0.68rem] tabular-nums text-slate-400">
                Page {currentPage} of {totalPages}
              </span>
              <button
                className={buttonClassName('ghost', 'sm')}
                disabled={!hasNextPage || casePage.loading}
                type="button"
                onClick={nextPage}
              >
                Next
                <ChevronRight aria-hidden="true" className="size-3.5" />
              </button>
            </div>
          </footer>
        ) : null}
      </Card>
    </div>
  );
}
