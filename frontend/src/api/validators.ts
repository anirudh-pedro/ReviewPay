import type {
  ActionBreakdown,
  AuditEvent,
  AuditTrailResponse,
  AutopilotCase,
  AutopilotResponse,
  AutopilotStep,
  BaselineComparisonResponse,
  ClockResponse,
  CustomerContext,
  DemoResetResponse,
  DemoScenario,
  ExecutionResultRead,
  FailureReasonBreakdown,
  HealthResponse,
  HistoricalLearningEvidence,
  IntelligenceCustomerContext,
  IntelligenceDiagnosis,
  IntelligenceFactor,
  IntelligenceModelTraining,
  Money,
  OverviewResponse,
  Page,
  PaymentAttempt,
  PaymentDetail,
  RazorpayOrderResponse,
  RazorpayVerificationResponse,
  RecoveryActionRead,
  RecoveryCaseDetail,
  RecoveryCaseSummary,
  RecoveryIntelligenceCandidate,
  RecoveryIntelligenceCounterfactual,
  RecoveryIntelligenceCounterfactualArm,
  RecoveryIntelligenceResponse,
  RecoveryOutcomeRead,
  ScenariosResponse,
  StrategyComparison,
  StrategyLabResponse,
  StrategyOption,
  WorkflowRunResponse,
} from '@/types/api';

/**
 * Runtime response guards for every route the Command Center consumes.
 *
 * TypeScript proves the component source; it cannot prove a server, proxy, or
 * stale deployment sent the response we expect. These guards keep malformed API
 * payloads inside the shared ApiError path instead of letting them reach UI code.
 */

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isInteger(value: unknown): value is number {
  return isFiniteNumber(value) && Number.isInteger(value);
}

function isString(value: unknown): value is string {
  return typeof value === 'string';
}

function isBoolean(value: unknown): value is boolean {
  return typeof value === 'boolean';
}

function isNullable(value: unknown, validator: (candidate: unknown) => boolean): boolean {
  return value === null || validator(value);
}

function isTimestamp(value: unknown): value is string {
  return isString(value) && !Number.isNaN(Date.parse(value));
}

function isRecordOf(value: unknown, validator: (candidate: unknown) => boolean): value is Record<string, unknown> {
  return isRecord(value) && Object.values(value).every(validator);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isString);
}

function isSyntheticNotice(value: unknown): value is Record<string, unknown> & { data_source: string; notice: string } {
  return isRecord(value) && isString(value.data_source) && isString(value.notice);
}

export function isMoney(value: unknown): value is Money {
  return isRecord(value) && isInteger(value.amount) && isString(value.currency);
}

export function isHealthResponse(value: unknown): value is HealthResponse {
  return (
    isRecord(value) &&
    isString(value.status) &&
    isString(value.app_name) &&
    isString(value.version) &&
    isString(value.environment) &&
    isTimestamp(value.virtual_clock_time) &&
    isString(value.data_source)
  );
}

export function isClockResponse(value: unknown): value is ClockResponse {
  return (
    isRecord(value) &&
    isTimestamp(value.virtual_clock_time) &&
    isFiniteNumber(value.advanced_by_minutes) &&
    (value.previous_virtual_clock_time === null || isTimestamp(value.previous_virtual_clock_time))
  );
}

function isFailureReasonBreakdown(value: unknown): value is FailureReasonBreakdown {
  return (
    isRecord(value) &&
    isString(value.failure_reason) &&
    isInteger(value.cases) &&
    isMoney(value.amount_at_risk) &&
    isMoney(value.amount_recovered) &&
    isInteger(value.recovered_cases) &&
    isFiniteNumber(value.recovery_rate)
  );
}

function isActionBreakdown(value: unknown): value is ActionBreakdown {
  return (
    isRecord(value) &&
    isString(value.action_type) &&
    isInteger(value.selected) &&
    isInteger(value.executed) &&
    isInteger(value.successes) &&
    isInteger(value.failures) &&
    isFiniteNumber(value.success_rate) &&
    isMoney(value.amount_recovered) &&
    isMoney(value.average_amount_recovered) &&
    isInteger(value.blocked) &&
    isInteger(value.escalated)
  );
}

function isSafetyChecks(value: unknown): boolean {
  return (
    isRecord(value) &&
    isBoolean(value.recovery_budget_enforced) &&
    isBoolean(value.high_value_escalation_enabled) &&
    isBoolean(value.blocked_actions_never_executed) &&
    isBoolean(value.outcomes_independently_verified) &&
    isBoolean(value.complete_audit_trail) &&
    isInteger(value.max_automatic_retries) &&
    isMoney(value.high_value_threshold) &&
    isStringArray(value.policy_rules)
  );
}

export function isOverviewResponse(value: unknown): value is OverviewResponse {
  return (
    isRecord(value) &&
    isSyntheticNotice(value) &&
    isMoney(value.revenue_at_risk) &&
    isMoney(value.revenue_recovered) &&
    isFiniteNumber(value.recovery_rate) &&
    isMoney(value.average_recovery_value) &&
    isMoney(value.expected_recovery_value_total) &&
    isMoney(value.expected_recovery_value_approved) &&
    isInteger(value.active_cases) &&
    isInteger(value.scheduled_cases) &&
    isInteger(value.cases_total) &&
    isInteger(value.cases_recovered) &&
    isInteger(value.payments_at_risk) &&
    isInteger(value.successful_recoveries) &&
    isInteger(value.human_escalations) &&
    isInteger(value.policy_blocks) &&
    isInteger(value.policy_approvals) &&
    isFiniteNumber(value.average_recovery_probability) &&
    isInteger(value.verified_outcomes) &&
    isRecordOf(value.cases_by_state, isInteger) &&
    Array.isArray(value.by_failure_reason) &&
    value.by_failure_reason.every(isFailureReasonBreakdown) &&
    Array.isArray(value.by_action) &&
    value.by_action.every(isActionBreakdown) &&
    isSafetyChecks(value.safety) &&
    isTimestamp(value.virtual_clock_time)
  );
}

export function isRecoveryCaseSummary(value: unknown): value is RecoveryCaseSummary {
  return (
    isRecord(value) &&
    isString(value.case_id) &&
    isString(value.payment_id) &&
    isString(value.state) &&
    isMoney(value.amount_at_risk) &&
    isTimestamp(value.created_at) &&
    isTimestamp(value.updated_at)
  );
}

export function isPageOf<T>(
  value: unknown,
  itemValidator: (item: unknown) => item is T,
): value is Page<T> {
  return (
    isRecord(value) &&
    Array.isArray(value.items) &&
    value.items.every(itemValidator) &&
    isInteger(value.total) &&
    isInteger(value.limit) &&
    isInteger(value.offset)
  );
}

function isDecisionAlternative(value: unknown): boolean {
  return (
    isRecord(value) &&
    isString(value.action) &&
    isFiniteNumber(value.probability) &&
    isFiniteNumber(value.expected_recovery_value)
  );
}

function isDecisionExplanation(value: unknown): boolean {
  return (
    isRecord(value) &&
    isString(value.selected_action) &&
    isString(value.reason) &&
    isFiniteNumber(value.probability) &&
    isFiniteNumber(value.expected_recovery_value) &&
    isFiniteNumber(value.confidence) &&
    Array.isArray(value.alternatives) &&
    value.alternatives.every(isDecisionAlternative)
  );
}

function isDiagnosis(value: unknown): boolean {
  return (
    isRecord(value) &&
    isString(value.failure_reason) &&
    isString(value.category) &&
    isString(value.transience) &&
    isBoolean(value.requires_escalation) &&
    isString(value.explanation)
  );
}

function isPolicyResult(value: unknown): boolean {
  return isRecord(value) && isString(value.outcome) && isString(value.rule_id) && isString(value.reason);
}

function isRecoveryAction(value: unknown): value is RecoveryActionRead {
  return (
    isRecord(value) &&
    isString(value.action_id) &&
    isString(value.action_type) &&
    isFiniteNumber(value.estimated_probability) &&
    isFiniteNumber(value.confidence) &&
    isString(value.model_version) &&
    isFiniteNumber(value.expected_recovery_value) &&
    isRecord(value.erv_breakdown) &&
    isString(value.risk_level) &&
    (value.policy_outcome === null || isString(value.policy_outcome)) &&
    (value.policy_rule_id === null || isString(value.policy_rule_id)) &&
    (value.policy_reason === null || isString(value.policy_reason)) &&
    isRecord(value.decision_explanation) &&
    isString(value.status) &&
    isBoolean(value.requires_human_approval) &&
    isTimestamp(value.created_at) &&
    (value.scheduled_at === null || isTimestamp(value.scheduled_at)) &&
    (value.executed_at === null || isTimestamp(value.executed_at))
  );
}

function isRecoveryOutcome(value: unknown): value is RecoveryOutcomeRead {
  return (
    isRecord(value) &&
    isString(value.outcome_id) &&
    isString(value.action_id) &&
    isString(value.previous_payment_status) &&
    isString(value.new_payment_status) &&
    isBoolean(value.recovered) &&
    isInteger(value.recovered_amount) &&
    (value.failure_reason === null || isString(value.failure_reason)) &&
    isTimestamp(value.verification_timestamp)
  );
}

export function isRecoveryCaseDetail(value: unknown): value is RecoveryCaseDetail {
  return (
    isRecoveryCaseSummary(value) &&
    isRecord(value) &&
    isNullable(value.diagnosis, isDiagnosis) &&
    isNullable(value.latest_action, isRecoveryAction) &&
    isNullable(value.latest_explanation, isDecisionExplanation) &&
    isNullable(value.latest_policy, isPolicyResult) &&
    isNullable(value.latest_outcome, isRecoveryOutcome) &&
    Array.isArray(value.actions) &&
    value.actions.every(isRecoveryAction) &&
    (value.waiting_until === null || isTimestamp(value.waiting_until)) &&
    isBoolean(value.is_terminal)
  );
}

function isPaymentAttempt(value: unknown): value is PaymentAttempt {
  return (
    isRecord(value) &&
    isString(value.attempt_id) &&
    isInteger(value.attempt_number) &&
    isString(value.status) &&
    (value.failure_reason === null || isString(value.failure_reason)) &&
    (value.action_type === null || isString(value.action_type)) &&
    isString(value.source) &&
    isRecord(value.provider_response) &&
    isTimestamp(value.attempted_at)
  );
}

export function isPaymentDetail(value: unknown): value is PaymentDetail {
  return (
    isRecord(value) &&
    isString(value.payment_id) &&
    isString(value.customer_id) &&
    isMoney(value.money) &&
    isString(value.payment_method) &&
    isString(value.status) &&
    isInteger(value.attempt_count) &&
    (value.failure_reason === null || isString(value.failure_reason)) &&
    isString(value.merchant_id) &&
    isBoolean(value.is_synthetic) &&
    isTimestamp(value.created_at) &&
    isTimestamp(value.updated_at) &&
    Array.isArray(value.attempts) &&
    value.attempts.every(isPaymentAttempt)
  );
}

export function isRazorpayOrderResponse(value: unknown): value is RazorpayOrderResponse {
  return (
    isRecord(value) &&
    isString(value.data_source) &&
    isString(value.notice) &&
    isString(value.key_id) &&
    isString(value.order_id) &&
    isMoney(value.money) &&
    isRecord(value.payment) &&
    isString(value.payment.payment_id) &&
    isString(value.payment.status)
  );
}

export function isRazorpayVerificationResponse(value: unknown): value is RazorpayVerificationResponse {
  return (
    isRecord(value) &&
    isString(value.data_source) &&
    isString(value.notice) &&
    isString(value.verified_provider_status) &&
    isRecord(value.payment) &&
    isString(value.payment.payment_id) &&
    isString(value.payment.status) &&
    (value.recovery_case_id === null || isString(value.recovery_case_id)) &&
    (value.recovery_case_state === null || isString(value.recovery_case_state))
  );
}

function isAuditEvent(value: unknown): value is AuditEvent {
  return (
    isRecord(value) &&
    isString(value.event_id) &&
    isString(value.case_id) &&
    isString(value.payment_id) &&
    isString(value.stage) &&
    isString(value.event_type) &&
    isString(value.message) &&
    isRecord(value.metadata) &&
    isTimestamp(value.timestamp) &&
    isInteger(value.sequence)
  );
}

export function isAuditTrailResponse(value: unknown): value is AuditTrailResponse {
  return (
    isRecord(value) &&
    isString(value.case_id) &&
    Array.isArray(value.events) &&
    value.events.every(isAuditEvent) &&
    isInteger(value.total)
  );
}

function isExecutionResult(value: unknown): value is ExecutionResultRead {
  return (
    isRecord(value) &&
    isString(value.action) &&
    isString(value.status) &&
    isRecord(value.provider_response) &&
    isTimestamp(value.executed_at)
  );
}

export function isWorkflowRunResponse(value: unknown): value is WorkflowRunResponse {
  return (
    isRecord(value) &&
    isString(value.workflow_id) &&
    isString(value.case_id) &&
    isString(value.payment_id) &&
    isTimestamp(value.started_at) &&
    isTimestamp(value.ended_at) &&
    isString(value.state) &&
    isString(value.final_status) &&
    (value.selected_action === null || isString(value.selected_action)) &&
    isNullable(value.explanation, isDecisionExplanation) &&
    isNullable(value.policy, isPolicyResult) &&
    isNullable(value.execution, isExecutionResult) &&
    isNullable(value.outcome, isRecoveryOutcome) &&
    isMoney(value.recovered_amount) &&
    (value.waiting_until === null || isTimestamp(value.waiting_until)) &&
    isStringArray(value.stages) &&
    isString(value.message)
  );
}

function isAutopilotStep(value: unknown): value is AutopilotStep {
  return (
    isRecord(value) &&
    isInteger(value.run_index) &&
    isString(value.state) &&
    (value.selected_action === null || isString(value.selected_action)) &&
    (value.policy_outcome === null || isString(value.policy_outcome)) &&
    (value.policy_rule_id === null || isString(value.policy_rule_id)) &&
    (value.execution_status === null || isString(value.execution_status)) &&
    isMoney(value.recovered_amount) &&
    (value.waiting_until === null || isTimestamp(value.waiting_until)) &&
    isStringArray(value.stages) &&
    isString(value.message)
  );
}

function isAutopilotCase(value: unknown): value is AutopilotCase {
  return (
    isRecord(value) &&
    isString(value.case_id) &&
    isString(value.payment_id) &&
    isString(value.customer_id) &&
    isMoney(value.amount_at_risk) &&
    isString(value.failure_reason) &&
    isString(value.payment_method) &&
    isString(value.final_state) &&
    (value.selected_action === null || isString(value.selected_action)) &&
    (value.policy_outcome === null || isString(value.policy_outcome)) &&
    (value.policy_rule_id === null || isString(value.policy_rule_id)) &&
    (value.policy_reason === null || isString(value.policy_reason)) &&
    (value.probability === null || isFiniteNumber(value.probability)) &&
    isNullable(value.expected_recovery_value, isMoney) &&
    isMoney(value.recovered_amount) &&
    isBoolean(value.recovered) &&
    isInteger(value.runs) &&
    isInteger(value.clock_advances) &&
    (value.explanation === null || isString(value.explanation)) &&
    Array.isArray(value.alternatives) &&
    value.alternatives.every(isRecord) &&
    Array.isArray(value.steps) &&
    value.steps.every(isAutopilotStep) &&
    (value.error === null || isString(value.error))
  );
}

export function isAutopilotResponse(value: unknown): value is AutopilotResponse {
  return (
    isRecord(value) &&
    isSyntheticNotice(value) &&
    isTimestamp(value.started_at) &&
    isTimestamp(value.ended_at) &&
    isInteger(value.total_cases) &&
    isMoney(value.total_at_risk) &&
    isMoney(value.total_recovered) &&
    isFiniteNumber(value.recovery_rate) &&
    isInteger(value.cases_recovered) &&
    isInteger(value.cases_stopped) &&
    isInteger(value.cases_escalated) &&
    isInteger(value.cases_unresolved) &&
    isInteger(value.actions_executed) &&
    isInteger(value.actions_blocked) &&
    isInteger(value.actions_escalated) &&
    isMoney(value.total_expected_recovery_value) &&
    Array.isArray(value.results) &&
    value.results.every(isAutopilotCase)
  );
}

function isStrategyOption(value: unknown): value is StrategyOption {
  return (
    isRecord(value) &&
    isString(value.action) &&
    isFiniteNumber(value.probability) &&
    isFiniteNumber(value.confidence) &&
    isMoney(value.intervention_cost) &&
    isMoney(value.friction_penalty) &&
    isMoney(value.gross_expected_recovery) &&
    isMoney(value.expected_recovery_value) &&
    isString(value.risk_level) &&
    isString(value.policy_outcome) &&
    isString(value.policy_rule_id) &&
    isString(value.policy_reason) &&
    isBoolean(value.eligible) &&
    isBoolean(value.is_candidate) &&
    isBoolean(value.is_recommended) &&
    isBoolean(value.is_current) &&
    isBoolean(value.simulated_would_succeed) &&
    isString(value.simulation_basis)
  );
}

function isCustomerContext(value: unknown): value is CustomerContext {
  return (
    isRecord(value) &&
    isString(value.customer_id) &&
    isInteger(value.total_payments) &&
    isInteger(value.successful_payments) &&
    isInteger(value.failed_payments) &&
    isFiniteNumber(value.success_rate) &&
    isMoney(value.average_transaction_value) &&
    isString(value.subscription_status) &&
    isBoolean(value.history_available) &&
    isBoolean(value.is_returning_customer) &&
    (value.days_since_previous_payment === null || isInteger(value.days_since_previous_payment)) &&
    isInteger(value.previous_recovery_attempts) &&
    isStringArray(value.attempted_actions) &&
    isStringArray(value.failed_actions) &&
    isStringArray(value.succeeded_actions)
  );
}

export function isStrategyLabResponse(value: unknown): value is StrategyLabResponse {
  return (
    isRecord(value) &&
    isSyntheticNotice(value) &&
    isString(value.case_id) &&
    isString(value.payment_id) &&
    isMoney(value.amount) &&
    isString(value.payment_method) &&
    isString(value.failure_reason) &&
    isInteger(value.attempt_count) &&
    isString(value.case_state) &&
    isRecord(value.diagnosis) &&
    isCustomerContext(value.customer) &&
    Array.isArray(value.options) &&
    value.options.every(isStrategyOption) &&
    (value.recommended_action === null || isString(value.recommended_action)) &&
    (value.current_action === null || isString(value.current_action)) &&
    isString(value.recommendation_reason) &&
    isBoolean(value.overrides_applied) &&
    isRecord(value.effective_settings) &&
    isString(value.model_version)
  );
}

function isIntelligenceCustomerContext(value: unknown): value is IntelligenceCustomerContext {
  return (
    isRecord(value) &&
    isBoolean(value.history_available) &&
    isInteger(value.total_payments) &&
    isFiniteNumber(value.success_rate) &&
    isString(value.subscription_status) &&
    isBoolean(value.is_returning_customer) &&
    isStringArray(value.successful_recovery_actions) &&
    isString(value.summary)
  );
}

function isIntelligenceDiagnosis(value: unknown): value is IntelligenceDiagnosis {
  return (
    isRecord(value) &&
    isString(value.root_cause) &&
    isString(value.severity) &&
    isIntelligenceCustomerContext(value.customer_context) &&
    (value.recommended_recovery_approach === null || isString(value.recommended_recovery_approach)) &&
    isString(value.reasoning) &&
    isString(value.source) &&
    isBoolean(value.fallback_used) &&
    (value.fallback_reason === null || isString(value.fallback_reason))
  );
}

function isIntelligenceFactor(value: unknown): value is IntelligenceFactor {
  return (
    isRecord(value) &&
    isString(value.name) &&
    isString(value.value) &&
    isFiniteNumber(value.influence) &&
    isString(value.description)
  );
}

function isHistoricalLearningEvidence(value: unknown): value is HistoricalLearningEvidence {
  return (
    isRecord(value) &&
    isString(value.cohort) &&
    isInteger(value.synthetic_samples) &&
    isInteger(value.synthetic_successes) &&
    isInteger(value.verified_samples) &&
    isInteger(value.verified_successes) &&
    isInteger(value.total_samples) &&
    (value.success_rate === null || isFiniteNumber(value.success_rate)) &&
    isString(value.statement)
  );
}

function isIntelligenceModelTraining(value: unknown): value is IntelligenceModelTraining {
  return (
    isRecord(value) &&
    isString(value.model_version) &&
    isInteger(value.training_samples) &&
    isInteger(value.synthetic_samples) &&
    isInteger(value.verified_outcome_samples) &&
    isString(value.bounded_window) &&
    isBoolean(value.fallback_used) &&
    (value.fallback_reason === null || isString(value.fallback_reason))
  );
}

function isRecoveryIntelligenceCandidate(value: unknown): value is RecoveryIntelligenceCandidate {
  return (
    isRecord(value) &&
    isString(value.action) &&
    isBoolean(value.is_candidate) &&
    isBoolean(value.is_production_selected) &&
    isBoolean(value.is_adaptive_recommended) &&
    isFiniteNumber(value.deterministic_probability) &&
    isFiniteNumber(value.learned_probability) &&
    isFiniteNumber(value.probability_delta) &&
    isFiniteNumber(value.deterministic_confidence) &&
    isFiniteNumber(value.model_confidence) &&
    isMoney(value.deterministic_expected_recovery_value) &&
    isMoney(value.adaptive_expected_recovery_value) &&
    isMoney(value.intervention_cost) &&
    isMoney(value.friction_penalty) &&
    isString(value.risk_level) &&
    isString(value.policy_outcome) &&
    isString(value.policy_rule_id) &&
    isString(value.policy_reason) &&
    isHistoricalLearningEvidence(value.historical_evidence) &&
    Array.isArray(value.learning_factors) &&
    value.learning_factors.every(isIntelligenceFactor) &&
    isString(value.rejected_reason) &&
    isBoolean(value.simulated_would_recover) &&
    isString(value.simulation_basis)
  );
}

function isRecoveryIntelligenceCounterfactualArm(
  value: unknown,
): value is RecoveryIntelligenceCounterfactualArm {
  return (
    isRecord(value) &&
    isString(value.label) &&
    (value.action === null || isString(value.action)) &&
    (value.policy_outcome === null || isString(value.policy_outcome)) &&
    (value.policy_rule_id === null || isString(value.policy_rule_id)) &&
    (value.policy_reason === null || isString(value.policy_reason)) &&
    isFiniteNumber(value.probability) &&
    isMoney(value.expected_recovery_value) &&
    isMoney(value.projected_recovered) &&
    isBoolean(value.simulated_would_recover) &&
    isString(value.simulation_basis)
  );
}

function isRecoveryIntelligenceCounterfactual(
  value: unknown,
): value is RecoveryIntelligenceCounterfactual {
  return (
    isRecord(value) &&
    isString(value.basis) &&
    isRecoveryIntelligenceCounterfactualArm(value.baseline) &&
    isRecoveryIntelligenceCounterfactualArm(value.revivepay) &&
    isMoney(value.projected_recovered_uplift) &&
    (value.projected_recovered_uplift_pct === null || isFiniteNumber(value.projected_recovered_uplift_pct)) &&
    isMoney(value.expected_recovery_value_uplift) &&
    isString(value.notice)
  );
}

export function isRecoveryIntelligenceResponse(value: unknown): value is RecoveryIntelligenceResponse {
  return (
    isRecord(value) &&
    isSyntheticNotice(value) &&
    isString(value.case_id) &&
    isString(value.payment_id) &&
    isMoney(value.amount) &&
    isString(value.failure_detected) &&
    isIntelligenceDiagnosis(value.diagnosis) &&
    isIntelligenceModelTraining(value.model) &&
    (value.production_selected_action === null || isString(value.production_selected_action)) &&
    (value.adaptive_recommended_action === null || isString(value.adaptive_recommended_action)) &&
    isString(value.adaptive_reasoning) &&
    Array.isArray(value.candidates) &&
    value.candidates.every(isRecoveryIntelligenceCandidate) &&
    isRecoveryIntelligenceCounterfactual(value.counterfactual)
  );
}

function isStrategyComparison(value: unknown): value is StrategyComparison {
  return (
    isRecord(value) &&
    isString(value.strategy) &&
    isString(value.description) &&
    isInteger(value.cases) &&
    isMoney(value.amount_at_risk) &&
    isMoney(value.expected_recovery_value) &&
    isMoney(value.projected_recovered) &&
    isFiniteNumber(value.projected_recovery_rate) &&
    isInteger(value.cases_projected_recovered) &&
    isInteger(value.cases_blocked) &&
    isInteger(value.cases_escalated) &&
    isFiniteNumber(value.escalation_rate) &&
    isRecordOf(value.actions_used, isInteger)
  );
}

export function isBaselineComparisonResponse(value: unknown): value is BaselineComparisonResponse {
  return (
    isRecord(value) &&
    isSyntheticNotice(value) &&
    isStrategyComparison(value.baseline) &&
    isStrategyComparison(value.revivepay) &&
    isMoney(value.recovered_uplift) &&
    isFiniteNumber(value.recovered_uplift_pct) &&
    isFiniteNumber(value.recovery_rate_uplift_pct) &&
    isMoney(value.expected_value_uplift) &&
    isInteger(value.cases_evaluated)
  );
}

function isDemoScenario(value: unknown): value is DemoScenario {
  return (
    isRecord(value) &&
    isString(value.key) &&
    isString(value.title) &&
    isString(value.narrative) &&
    isString(value.case_id) &&
    isString(value.payment_id) &&
    isMoney(value.amount) &&
    isString(value.failure_reason) &&
    isString(value.expected_action) &&
    isString(value.expected_final_state) &&
    isBoolean(value.requires_clock_advance) &&
    isString(value.current_state)
  );
}

export function isScenariosResponse(value: unknown): value is ScenariosResponse {
  return (
    isRecord(value) &&
    isSyntheticNotice(value) &&
    Array.isArray(value.scenarios) &&
    value.scenarios.every(isDemoScenario) &&
    isTimestamp(value.virtual_clock_time)
  );
}

export function isDemoResetResponse(value: unknown): value is DemoResetResponse {
  return (
    isRecord(value) &&
    isSyntheticNotice(value) &&
    isInteger(value.customers) &&
    isInteger(value.payments) &&
    isInteger(value.cases) &&
    Array.isArray(value.scenarios) &&
    value.scenarios.every(isDemoScenario) &&
    isTimestamp(value.virtual_clock_time) &&
    isString(value.message)
  );
}


export function isIntelligenceModelStatusResponse(
  value: unknown,
): value is import('@/types/api').IntelligenceModelStatusResponse {
  return (
    isRecord(value) &&
    isSyntheticNotice(value) &&
    isString(value.active_predictor) &&
    isString(value.mode) &&
    isBoolean(value.fallback_mode) &&
    isString(value.feature_schema_version) &&
    isIntelligenceModelTraining(value.training)
  );
}
