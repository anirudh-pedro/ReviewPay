/**
 * Typed endpoint functions. One function per backend route.
 *
 * Every function maps 1:1 onto an existing FastAPI route; no recovery
 * calculation, ranking, or policy decision is reimplemented in the browser.
 */

import { API_PREFIX, apiGet, apiPost } from './client';
import {
  isAuditTrailResponse,
  isAutopilotResponse,
  isBaselineComparisonResponse,
  isClockResponse,
  isDemoResetResponse,
  isHealthResponse,
  isOverviewResponse,
  isPageOf,
  isPaymentDetail,
  isRecoveryCaseDetail,
  isRecoveryCaseSummary,
  isRecoveryIntelligenceResponse,
  isIntelligenceModelStatusResponse,
  isJudgeDemoResponse,
  isScenariosResponse,
  isStrategyLabResponse,
  isWorkflowRunResponse,
} from './validators';
import type {
  AuditTrailResponse,
  AutopilotResponse,
  BaselineComparisonResponse,
  CaseState,
  ClockResponse,
  DemoResetResponse,
  HealthResponse,
  OverviewResponse,
  Page,
  PaymentDetail,
  RecoveryCaseDetail,
  RecoveryCaseSummary,
  RecoveryIntelligenceResponse,
  IntelligenceModelStatusResponse,
  ScenarioOverrides,
  ScenariosResponse,
  StrategyLabResponse,
  WorkflowRunResponse,
} from '@/types/api';

// Configurable FastAPI mount path; defaults to the local backend's `/api` prefix.
const PREFIX = API_PREFIX;

/** Body accepted by POST /api/simulate/advance-clock. */
export interface AdvanceClockRequest {
  minutes: number;
  hours?: number;
}

/** Query parameters accepted by GET /api/recovery/cases. */
export interface ListCasesParams {
  limit?: number;
  offset?: number;
  state?: CaseState;
}

/** Body accepted by POST /api/recovery/autopilot. */
export interface AutopilotRequest {
  limit?: number;
}

/** Body accepted by POST /api/demo/reset. */
export interface DemoResetRequest {
  background_customers?: number;
}

// ---------------------------------------------------------------------------
// Health and clock
// ---------------------------------------------------------------------------

export const getHealth = (signal?: AbortSignal) =>
  apiGet<HealthResponse>('/health', signal, isHealthResponse);

export const getClock = (signal?: AbortSignal) =>
  apiGet<ClockResponse>(`${PREFIX}/simulate/clock`, signal, isClockResponse);

/**
 * Advance the deterministic virtual clock. The numeric signature remains for
 * backward compatibility; new callers can pass the backend-shaped request body.
 */
export function advanceClock(
  requestOrMinutes: AdvanceClockRequest | number,
  hours = 0,
): Promise<ClockResponse> {
  const request: AdvanceClockRequest =
    typeof requestOrMinutes === 'number'
      ? { minutes: requestOrMinutes, hours }
      : requestOrMinutes;

  return apiPost<ClockResponse>(
    `${PREFIX}/simulate/advance-clock`,
    request,
    undefined,
    isClockResponse,
  );
}

// ---------------------------------------------------------------------------
// Command Center overview
// ---------------------------------------------------------------------------

export const getOverview = (signal?: AbortSignal) =>
  apiGet<OverviewResponse>(`${PREFIX}/recovery/overview`, signal, isOverviewResponse);

export const getScenarios = (signal?: AbortSignal) =>
  apiGet<ScenariosResponse>(`${PREFIX}/recovery/scenarios`, signal, isScenariosResponse);

export const getBaselineComparison = (signal?: AbortSignal) =>
  apiGet<BaselineComparisonResponse>(
    `${PREFIX}/recovery/baseline`,
    signal,
    isBaselineComparisonResponse,
  );

// ---------------------------------------------------------------------------
// Cases
// ---------------------------------------------------------------------------

const isRecoveryCasePage = (value: unknown): value is Page<RecoveryCaseSummary> =>
  isPageOf(value, isRecoveryCaseSummary);

export function listCases(
  params: ListCasesParams = {},
  signal?: AbortSignal,
): Promise<Page<RecoveryCaseSummary>> {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.offset !== undefined) query.set('offset', String(params.offset));
  if (params.state) query.set('state', params.state);

  const suffix = query.toString() ? `?${query.toString()}` : '';
  return apiGet<Page<RecoveryCaseSummary>>(
    `${PREFIX}/recovery/cases${suffix}`,
    signal,
    isRecoveryCasePage,
  );
}

export const getCase = (caseId: string, signal?: AbortSignal) =>
  apiGet<RecoveryCaseDetail>(
    `${PREFIX}/recovery/cases/${encodeURIComponent(caseId)}`,
    signal,
    isRecoveryCaseDetail,
  );

export const getCaseAudit = (caseId: string, signal?: AbortSignal) =>
  apiGet<AuditTrailResponse>(
    `${PREFIX}/recovery/cases/${encodeURIComponent(caseId)}/audit`,
    signal,
    isAuditTrailResponse,
  );

export const runCase = (caseId: string) =>
  apiPost<WorkflowRunResponse>(
    `${PREFIX}/recovery/cases/${encodeURIComponent(caseId)}/run`,
    {},
    undefined,
    isWorkflowRunResponse,
  );

export const simulateStrategies = (caseId: string, overrides: ScenarioOverrides = {}) =>
  apiPost<StrategyLabResponse>(
    `${PREFIX}/recovery/cases/${encodeURIComponent(caseId)}/simulate`,
    overrides,
    undefined,
    isStrategyLabResponse,
  );

/** Read-only bounded diagnosis, learned probability, and counterfactual evidence. */
export const getRecoveryIntelligence = (caseId: string, signal?: AbortSignal) =>
  apiGet<RecoveryIntelligenceResponse>(
    `${PREFIX}/recovery/cases/${encodeURIComponent(caseId)}/intelligence`,
    signal,
    isRecoveryIntelligenceResponse,
  );

/** Apply Strategy Lab overrides to a separate, read-only intelligence projection. */
export const simulateRecoveryIntelligence = (
  caseId: string,
  overrides: ScenarioOverrides = {},
) =>
  apiPost<RecoveryIntelligenceResponse>(
    `${PREFIX}/recovery/cases/${encodeURIComponent(caseId)}/intelligence/simulate`,
    overrides,
    undefined,
    isRecoveryIntelligenceResponse,
  );

// ---------------------------------------------------------------------------
// Payments
// ---------------------------------------------------------------------------

export const getPayment = (paymentId: string, signal?: AbortSignal) =>
  apiGet<PaymentDetail>(
    `${PREFIX}/payments/${encodeURIComponent(paymentId)}`,
    signal,
    isPaymentDetail,
  );

// ---------------------------------------------------------------------------
// Autopilot
// ---------------------------------------------------------------------------

/**
 * Runs a real batch recovery. A numeric limit is retained for compatibility;
 * callers may also provide the backend-shaped request body.
 */
export function runAutopilot(input: AutopilotRequest | number = {}): Promise<AutopilotResponse> {
  const request: AutopilotRequest = typeof input === 'number' ? { limit: input } : input;
  return apiPost<AutopilotResponse>(
    `${PREFIX}/recovery/autopilot`,
    request,
    undefined,
    isAutopilotResponse,
  );
}

// ---------------------------------------------------------------------------
// Demo control
// ---------------------------------------------------------------------------

/**
 * Destructively reseeds the synthetic dataset in a permitted demo environment.
 * The number overload preserves the original public API.
 */
export function resetDemo(input: DemoResetRequest | number = 12): Promise<DemoResetResponse> {
  const request: DemoResetRequest =
    typeof input === 'number' ? { background_customers: input } : input;

  return apiPost<DemoResetResponse>(
    `${PREFIX}/demo/reset`,
    request,
    undefined,
    isDemoResetResponse,
  );
}


/** Read-only status of the configured predictor and bounded local evidence. */
export const getIntelligenceModelStatus = (signal?: AbortSignal) =>
  apiGet<IntelligenceModelStatusResponse>(
    `${PREFIX}/recovery/intelligence/model-status`,
    signal,
    isIntelligenceModelStatusResponse,
  );

/** 8-stage Judge Demo evaluation pipeline for a case. */
export const getJudgeDemo = (caseId: string, signal?: AbortSignal) =>
  apiGet<import('@/types/api').JudgeDemoResponse>(
    `${PREFIX}/recovery/cases/${encodeURIComponent(caseId)}/judge-demo`,
    signal,
    isJudgeDemoResponse,
  );

