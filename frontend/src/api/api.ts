/**
 * Public Command Center API facade.
 *
 * `recovery.ts` maps individual FastAPI endpoints. This module composes those
 * typed calls for views that need multiple resources while keeping `fetch` and
 * error handling inside the shared API boundary.
 */

import { isAbortError, toApiError } from './client';
import {
  getCase,
  getCaseAudit,
  getPayment,
  listCases,
} from './recovery';
import type { ApiError } from './client';
import type { ListCasesParams } from './recovery';
import type {
  AuditTrailResponse,
  PaymentDetail,
  RecoveryCaseDetail,
  RecoveryCaseSummary,
} from '@/types/api';

export * from './recovery';
export * from './gateway';

/** Bound parallel detail requests so a large case page cannot flood the API. */
const CASE_DETAIL_CONCURRENCY = 6;

/** Inputs for the Case Explorer's server-backed page plus optional enrichment. */
export interface CaseExplorerRequest extends ListCasesParams {
  /** Fetch each row's real decision/policy data after its summary is loaded. */
  includeDetails?: boolean;
}

/**
 * A list row carries the source summary plus optional detail enrichment.
 * A detail failure is isolated to its row so an otherwise usable case list stays
 * visible; the API error is retained for an explicit UI state.
 */
export interface CaseExplorerRow {
  summary: RecoveryCaseSummary;
  detail: RecoveryCaseDetail | null;
  detailError: ApiError | null;
}

/** Server pagination metadata and enrichable Case Explorer rows. */
export interface CaseExplorerPage {
  items: CaseExplorerRow[];
  total: number;
  limit: number;
  offset: number;
}

/** Everything the Case Intelligence screen needs from authoritative endpoints. */
export interface CaseIntelligence {
  recoveryCase: RecoveryCaseDetail;
  payment: PaymentDetail;
  audit: AuditTrailResponse;
}

function createAbortError(): Error {
  const error = new Error('The request was aborted.');
  error.name = 'AbortError';
  return error;
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw createAbortError();
}

/**
 * Fetch case details with bounded concurrency. Failed details settle individually
 * so Case Explorer can show the real summary and a row-specific retry/error state.
 */
async function settleCaseDetails(
  summaries: readonly RecoveryCaseSummary[],
  signal?: AbortSignal,
): Promise<PromiseSettledResult<RecoveryCaseDetail>[]> {
  const results = Array<PromiseSettledResult<RecoveryCaseDetail> | undefined>(summaries.length).fill(undefined);
  let nextIndex = 0;

  async function worker(): Promise<void> {
    while (true) {
      throwIfAborted(signal);
      const index = nextIndex;
      nextIndex += 1;
      const summary = summaries[index];
      if (!summary) return;

      try {
        results[index] = {
          status: 'fulfilled',
          value: await getCase(summary.case_id, signal),
        };
      } catch (cause) {
        if (isAbortError(cause)) throw cause;
        results[index] = { status: 'rejected', reason: cause };
      }
    }
  }

  await Promise.all(
    Array.from(
      { length: Math.min(CASE_DETAIL_CONCURRENCY, summaries.length) },
      () => worker(),
    ),
  );
  throwIfAborted(signal);

  return results.map(
    (result) =>
      result ?? {
        status: 'rejected',
        reason: new Error('A case detail request ended before returning a result.'),
      },
  );
}

/**
 * Load a paginated case list and, by default, enrich each listed case with its
 * backend-computed diagnosis, selected action, and policy result. This is read-
 * only composition: it never ranks, calculates ERV, or determines policy locally.
 */
export async function getCaseExplorerPage(
  request: CaseExplorerRequest = {},
  signal?: AbortSignal,
): Promise<CaseExplorerPage> {
  const { includeDetails = true, ...listRequest } = request;
  const page = await listCases(listRequest, signal);
  throwIfAborted(signal);

  if (!includeDetails || page.items.length === 0) {
    return {
      total: page.total,
      limit: page.limit,
      offset: page.offset,
      items: page.items.map((summary) => ({ summary, detail: null, detailError: null })),
    };
  }

  const detailResults = await settleCaseDetails(page.items, signal);
  const items = page.items.map((summary, index): CaseExplorerRow => {
    const result = detailResults[index];
    if (result?.status === 'fulfilled') {
      return { summary, detail: result.value, detailError: null };
    }

    return {
      summary,
      detail: null,
      detailError: toApiError(result?.reason),
    };
  });

  return { total: page.total, limit: page.limit, offset: page.offset, items };
}

/**
 * Load the Case Intelligence resources efficiently: the case and its audit trail
 * start together; payment history starts as soon as the authoritative case gives
 * us its payment identifier. Any endpoint failure retains the central ApiError.
 */
export async function getCaseIntelligence(
  caseId: string,
  signal?: AbortSignal,
): Promise<CaseIntelligence> {
  const caseRequest = getCase(caseId, signal);
  const auditRequest = getCaseAudit(caseId, signal);
  const [recoveryCase, audit] = await Promise.all([caseRequest, auditRequest]);
  throwIfAborted(signal);

  const payment = await getPayment(recoveryCase.payment_id, signal);
  throwIfAborted(signal);

  return { recoveryCase, payment, audit };
}
