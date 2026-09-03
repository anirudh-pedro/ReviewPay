/**
 * Types mirroring the RevivePay API response schemas.
 *
 * These describe the wire format only. No recovery logic, no expected-value
 * arithmetic, and no policy evaluation lives on this side of the boundary — the
 * backend is the single source of truth for all of it.
 *
 * Money is always an integer in minor units (paise for INR) plus a currency code,
 * exactly as the backend sends it. Never do arithmetic on the display value.
 */

/** An amount in minor units with its currency code. */
export interface Money {
  amount: number;
  currency: string;
}

export type CaseState =
  | 'DETECTED'
  | 'DIAGNOSING'
  | 'DIAGNOSED'
  | 'EVALUATING'
  | 'DECISION_READY'
  | 'POLICY_CHECK'
  | 'APPROVED'
  | 'BLOCKED'
  | 'SCHEDULED'
  | 'EXECUTING'
  | 'VERIFYING'
  | 'RECOVERED'
  | 'FAILED'
  | 'ESCALATED'
  | 'STOPPED';

export type PolicyOutcome = 'APPROVED' | 'BLOCKED' | 'ESCALATED';

export type ActionType =
  | 'RETRY_NOW'
  | 'RETRY_LATER'
  | 'SEND_PAYMENT_LINK'
  | 'CHANGE_PAYMENT_METHOD'
  | 'SEND_REMINDER'
  | 'ESCALATE_HUMAN'
  | 'STOP'
  | 'VOICE_CALL';

export type FailureReason =
  | 'BANK_TIMEOUT'
  | 'INSUFFICIENT_FUNDS'
  | 'EXPIRED_CARD'
  | 'NETWORK_ERROR'
  | 'CHECKOUT_ABANDONMENT'
  | 'SUBSCRIPTION_FAILURE'
  | 'UNKNOWN';

export type PaymentStatus =
  | 'CREATED'
  | 'PENDING'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'ABANDONED';

export type AuditEventType =
  | 'REVENUE_RISK_DETECTED'
  | 'DIAGNOSIS_COMPLETED'
  | 'RECOVERY_OPTIONS_EVALUATED'
  | 'RECOVERY_DECISION_SELECTED'
  | 'POLICY_APPROVED'
  | 'POLICY_BLOCKED'
  | 'POLICY_ESCALATED'
  | 'ACTION_SCHEDULED'
  | 'ACTION_EXECUTED'
  | 'ACTION_FAILED'
  | 'OUTCOME_VERIFIED'
  | 'REVENUE_RECOVERED'
  | 'WORKFLOW_STOPPED';

export type WorkflowStage =
  | 'DETECTION'
  | 'CONTEXT'
  | 'DIAGNOSIS'
  | 'CANDIDATE_GENERATION'
  | 'EVALUATION'
  | 'DECISION'
  | 'POLICY'
  | 'SCHEDULING'
  | 'EXECUTION'
  | 'VERIFICATION'
  | 'COMPLETION';

export type ExecutionStatus =
  | 'SUCCEEDED'
  | 'FAILED'
  | 'SCHEDULED'
  | 'ESCALATED'
  | 'STOPPED';

export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH';

/** Every computed payload carries its provenance. */
export interface SyntheticNotice {
  data_source: string;
  notice: string;
}

/** The standard error envelope. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
  };
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export interface HealthResponse {
  status: string;
  app_name: string;
  version: string;
  environment: string;
  virtual_clock_time: string;
  data_source: string;
  environment_profile?: string;
  authentication_mode?: string;
}

// ---------------------------------------------------------------------------
// Overview
// ---------------------------------------------------------------------------

export interface FailureReasonBreakdown {
  failure_reason: string;
  cases: number;
  amount_at_risk: Money;
  amount_recovered: Money;
  recovered_cases: number;
  recovery_rate: number;
}

export interface ActionBreakdown {
  action_type: string;
  selected: number;
  executed: number;
  successes: number;
  failures: number;
  success_rate: number;
  amount_recovered: Money;
  average_amount_recovered: Money;
  blocked: number;
  escalated: number;
}

export interface SafetyChecks {
  recovery_budget_enforced: boolean;
  high_value_escalation_enabled: boolean;
  blocked_actions_never_executed: boolean;
  outcomes_independently_verified: boolean;
  complete_audit_trail: boolean;
  max_automatic_retries: number;
  high_value_threshold: Money;
  policy_rules: string[];
}

export interface OverviewResponse extends SyntheticNotice {
  revenue_at_risk: Money;
  revenue_recovered: Money;
  recovery_rate: number;
  average_recovery_value: Money;
  expected_recovery_value_total: Money;
  expected_recovery_value_approved: Money;

  active_cases: number;
  scheduled_cases: number;
  cases_total: number;
  cases_recovered: number;
  payments_at_risk: number;

  successful_recoveries: number;
  human_escalations: number;
  policy_blocks: number;
  policy_approvals: number;

  average_recovery_probability: number;
  verified_outcomes: number;
  cases_by_state: Record<string, number>;

  by_failure_reason: FailureReasonBreakdown[];
  by_action: ActionBreakdown[];

  safety: SafetyChecks;
  virtual_clock_time: string;
}

// ---------------------------------------------------------------------------
// Cases
// ---------------------------------------------------------------------------

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface RecoveryCaseSummary {
  case_id: string;
  payment_id: string;
  state: CaseState;
  amount_at_risk: Money;
  created_at: string;
  updated_at: string;
  gateway_order_id?: string | null;
  is_synthetic?: boolean;
  failure_reason?: string | null;
}

export interface ExpectedValueBreakdown {
  action?: string;
  recovery_probability: number;
  payment_amount: number;
  gross_expected_recovery: number;
  intervention_cost: number;
  customer_friction_penalty: number;
  expected_recovery_value: number;
}

export interface DecisionAlternative {
  action: ActionType;
  probability: number;
  expected_recovery_value: number;
}

export interface DecisionExplanation {
  selected_action: ActionType;
  reason: string;
  probability: number;
  expected_recovery_value: number;
  confidence: number;
  alternatives: DecisionAlternative[];
}

export interface Diagnosis {
  failure_reason: FailureReason;
  category: string;
  transience: string;
  requires_escalation: boolean;
  explanation: string;
}

export interface PolicyResult {
  outcome: PolicyOutcome;
  rule_id: string;
  reason: string;
}

export interface RecoveryActionRead {
  action_id: string;
  action_type: ActionType;
  estimated_probability: number;
  confidence: number;
  model_version: string;
  expected_recovery_value: number;
  erv_breakdown: Partial<ExpectedValueBreakdown>;
  risk_level: RiskLevel;
  policy_outcome: PolicyOutcome | null;
  policy_rule_id: string | null;
  policy_reason: string | null;
  decision_explanation: Partial<DecisionExplanation>;
  status: string;
  requires_human_approval: boolean;
  created_at: string;
  scheduled_at: string | null;
  executed_at: string | null;
}

export interface RecoveryOutcomeRead {
  outcome_id: string;
  action_id: string;
  previous_payment_status: PaymentStatus;
  new_payment_status: PaymentStatus;
  recovered: boolean;
  recovered_amount: number;
  failure_reason: FailureReason | null;
  verification_timestamp: string;
}

export interface RecoveryCaseDetail extends RecoveryCaseSummary {
  diagnosis: Diagnosis | null;
  latest_action: RecoveryActionRead | null;
  latest_explanation: DecisionExplanation | null;
  latest_policy: PolicyResult | null;
  latest_outcome: RecoveryOutcomeRead | null;
  actions: RecoveryActionRead[];
  waiting_until: string | null;
  is_terminal: boolean;
}

export interface AuditEvent {
  event_id: string;
  case_id: string;
  payment_id: string;
  stage: WorkflowStage;
  event_type: AuditEventType;
  message: string;
  metadata: Record<string, unknown>;
  timestamp: string;
  sequence: number;
}

export interface AuditTrailResponse {
  case_id: string;
  events: AuditEvent[];
  total: number;
}

// ---------------------------------------------------------------------------
// Payments
// ---------------------------------------------------------------------------

export interface PaymentAttempt {
  attempt_id: string;
  attempt_number: number;
  status: PaymentStatus;
  failure_reason: FailureReason | null;
  action_type: ActionType | null;
  source: string;
  provider_response: Record<string, unknown>;
  attempted_at: string;
}

export interface PaymentRead {
  payment_id: string;
  customer_id: string;
  money: Money;
  payment_method: string;
  status: PaymentStatus;
  attempt_count: number;
  failure_reason: FailureReason | null;
  merchant_id: string;
  is_synthetic: boolean;
  gateway_order_id?: string | null;
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface PaymentDetail extends PaymentRead {
  attempts: PaymentAttempt[];
}

/** Isolated real-provider Sandbox order data; never used by simulator views. */
export interface RazorpayOrderResponse {
  data_source: 'razorpay_sandbox' | string;
  notice: string;
  key_id: string;
  order_id: string;
  payment: PaymentRead;
  money: Money;
}

export interface RazorpayVerificationResponse {
  data_source: 'razorpay_sandbox' | string;
  notice: string;
  payment: PaymentRead;
  verified_provider_status: string;
  recovery_case_id: string | null;
  recovery_case_state: string | null;
}

// ---------------------------------------------------------------------------
// Workflow run
// ---------------------------------------------------------------------------

export interface ExecutionResultRead {
  action: ActionType;
  status: ExecutionStatus;
  provider_response: Record<string, unknown>;
  executed_at: string;
}

export interface WorkflowRunResponse {
  workflow_id: string;
  case_id: string;
  payment_id: string;
  started_at: string;
  ended_at: string;
  state: CaseState;
  final_status: CaseState;
  selected_action: ActionType | null;
  explanation: DecisionExplanation | null;
  policy: PolicyResult | null;
  execution: ExecutionResultRead | null;
  outcome: RecoveryOutcomeRead | null;
  recovered_amount: Money;
  waiting_until: string | null;
  stages: string[];
  message: string;
}

// ---------------------------------------------------------------------------
// Autopilot
// ---------------------------------------------------------------------------

export interface AutopilotStep {
  run_index: number;
  state: CaseState;
  selected_action: string | null;
  policy_outcome: string | null;
  policy_rule_id: string | null;
  execution_status: string | null;
  recovered_amount: Money;
  waiting_until: string | null;
  stages: string[];
  message: string;
}

export interface AutopilotCase {
  case_id: string;
  payment_id: string;
  customer_id: string;
  amount_at_risk: Money;
  failure_reason: string;
  payment_method: string;
  final_state: CaseState;
  selected_action: string | null;
  policy_outcome: string | null;
  policy_rule_id: string | null;
  policy_reason: string | null;
  probability: number | null;
  expected_recovery_value: Money | null;
  recovered_amount: Money;
  recovered: boolean;
  runs: number;
  clock_advances: number;
  explanation: string | null;
  alternatives: Record<string, unknown>[];
  steps: AutopilotStep[];
  error: string | null;
}

export interface AutopilotResponse extends SyntheticNotice {
  started_at: string;
  ended_at: string;
  total_cases: number;
  total_at_risk: Money;
  total_recovered: Money;
  recovery_rate: number;
  cases_recovered: number;
  cases_stopped: number;
  cases_escalated: number;
  cases_unresolved: number;
  actions_executed: number;
  actions_blocked: number;
  actions_escalated: number;
  total_expected_recovery_value: Money;
  results: AutopilotCase[];
}

// ---------------------------------------------------------------------------
// Strategy Lab
// ---------------------------------------------------------------------------

export interface ScenarioOverrides {
  retry_later_delay_minutes?: number;
  max_automatic_retries?: number;
  repeated_failure_limit?: number;
  high_value_escalation_threshold?: number;
  intervention_cost_minor?: Record<string, number>;
  friction_penalty_minor?: Record<string, number>;
}

export interface StrategyOption {
  action: ActionType;
  probability: number;
  confidence: number;
  intervention_cost: Money;
  friction_penalty: Money;
  gross_expected_recovery: Money;
  expected_recovery_value: Money;
  risk_level: RiskLevel;
  policy_outcome: PolicyOutcome;
  policy_rule_id: string;
  policy_reason: string;
  eligible: boolean;
  is_candidate: boolean;
  is_recommended: boolean;
  is_current: boolean;
  simulated_would_succeed: boolean;
  simulation_basis: string;
}

export interface CustomerContext {
  customer_id: string;
  total_payments: number;
  successful_payments: number;
  failed_payments: number;
  success_rate: number;
  average_transaction_value: Money;
  subscription_status: string;
  history_available: boolean;
  is_returning_customer: boolean;
  days_since_previous_payment: number | null;
  previous_recovery_attempts: number;
  attempted_actions: string[];
  failed_actions: string[];
  succeeded_actions: string[];
}

export interface StrategyLabResponse extends SyntheticNotice {
  case_id: string;
  payment_id: string;
  amount: Money;
  payment_method: string;
  failure_reason: string;
  attempt_count: number;
  case_state: string;
  diagnosis: Partial<Diagnosis>;
  customer: CustomerContext;
  options: StrategyOption[];
  recommended_action: ActionType | null;
  current_action: ActionType | null;
  recommendation_reason: string;
  overrides_applied: boolean;
  effective_settings: Record<string, unknown>;
  model_version: string;
}

// ---------------------------------------------------------------------------
// Recovery Intelligence
// ---------------------------------------------------------------------------

/** Non-identifying payment-history evidence used by the structured diagnosis. */
export interface IntelligenceCustomerContext {
  history_available: boolean;
  total_payments: number;
  success_rate: number;
  subscription_status: string;
  is_returning_customer: boolean;
  successful_recovery_actions: string[];
  summary: string;
}

/** Structured diagnosis from the local agent, with fallback provenance. */
export interface IntelligenceDiagnosis {
  root_cause: string;
  severity: string;
  customer_context: IntelligenceCustomerContext;
  recommended_recovery_approach: ActionType | null;
  reasoning: string;
  source: string;
  fallback_used: boolean;
  fallback_reason: string | null;
}

/** One explainable influence behind the bounded learned prediction. */
export interface IntelligenceFactor {
  name: string;
  value: string;
  influence: number;
  description: string;
}

/** Comparable synthetic and independently verified observations for one action. */
export interface HistoricalLearningEvidence {
  cohort: string;
  synthetic_samples: number;
  synthetic_successes: number;
  verified_samples: number;
  verified_successes: number;
  total_samples: number;
  success_rate: number | null;
  statement: string;
}

/** Provenance for the bounded, on-demand empirical-Bayes calibration. */
export interface IntelligenceModelTraining {
  model_version: string;
  training_samples: number;
  synthetic_samples: number;
  verified_outcome_samples: number;
  bounded_window: string;
  fallback_used: boolean;
  fallback_reason: string | null;
}

/** One real production candidate, compared deterministically and advisorially. */
export interface RecoveryIntelligenceCandidate {
  action: ActionType;
  is_candidate: boolean;
  is_production_selected: boolean;
  is_adaptive_recommended: boolean;
  deterministic_probability: number;
  learned_probability: number;
  probability_delta: number;
  deterministic_confidence: number;
  model_confidence: number;
  deterministic_expected_recovery_value: Money;
  adaptive_expected_recovery_value: Money;
  intervention_cost: Money;
  friction_penalty: Money;
  risk_level: RiskLevel;
  policy_outcome: PolicyOutcome;
  policy_rule_id: string;
  policy_reason: string;
  historical_evidence: HistoricalLearningEvidence;
  learning_factors: IntelligenceFactor[];
  rejected_reason: string;
  simulated_would_recover: boolean;
  simulation_basis: string;
}

/** One policy-aware, read-only arm of the per-case counterfactual. */
export interface RecoveryIntelligenceCounterfactualArm {
  label: string;
  action: ActionType | null;
  policy_outcome: PolicyOutcome | null;
  policy_rule_id: string | null;
  policy_reason: string | null;
  probability: number;
  expected_recovery_value: Money;
  projected_recovered: Money;
  simulated_would_recover: boolean;
  simulation_basis: string;
}

/** Baseline retry-now versus the advisory RevivePay arm on the same context. */
export interface RecoveryIntelligenceCounterfactual {
  basis: string;
  baseline: RecoveryIntelligenceCounterfactualArm;
  revivepay: RecoveryIntelligenceCounterfactualArm;
  projected_recovered_uplift: Money;
  projected_recovered_uplift_pct: number | null;
  expected_recovery_value_uplift: Money;
  notice: string;
}

/** Complete bounded-learning explanation for a recovery case. */
export interface RecoveryIntelligenceResponse extends SyntheticNotice {
  case_id: string;
  payment_id: string;
  amount: Money;
  failure_detected: string;
  diagnosis: IntelligenceDiagnosis;
  model: IntelligenceModelTraining;
  production_selected_action: ActionType | null;
  adaptive_recommended_action: ActionType | null;
  adaptive_reasoning: string;
  candidates: RecoveryIntelligenceCandidate[];
  counterfactual: RecoveryIntelligenceCounterfactual;
}

// ---------------------------------------------------------------------------
// Baseline benchmark
// ---------------------------------------------------------------------------

export interface StrategyComparison {
  strategy: string;
  description: string;
  cases: number;
  amount_at_risk: Money;
  expected_recovery_value: Money;
  projected_recovered: Money;
  projected_recovery_rate: number;
  cases_projected_recovered: number;
  cases_blocked: number;
  cases_escalated: number;
  escalation_rate: number;
  actions_used: Record<string, number>;
}

export interface BaselineComparisonResponse extends SyntheticNotice {
  baseline: StrategyComparison;
  revivepay: StrategyComparison;
  recovered_uplift: Money;
  recovered_uplift_pct: number;
  recovery_rate_uplift_pct: number;
  expected_value_uplift: Money;
  cases_evaluated: number;
}

// ---------------------------------------------------------------------------
// Scenarios and demo control
// ---------------------------------------------------------------------------

export interface DemoScenario {
  key: string;
  title: string;
  narrative: string;
  case_id: string;
  payment_id: string;
  amount: Money;
  failure_reason: string;
  expected_action: string;
  expected_final_state: string;
  requires_clock_advance: boolean;
  current_state: CaseState;
}

export interface ScenariosResponse extends SyntheticNotice {
  scenarios: DemoScenario[];
  virtual_clock_time: string;
}

export interface DemoResetResponse extends SyntheticNotice {
  customers: number;
  payments: number;
  cases: number;
  scenarios: DemoScenario[];
  virtual_clock_time: string;
  message: string;
}

// ---------------------------------------------------------------------------
// Clock
// ---------------------------------------------------------------------------

export interface ClockResponse {
  virtual_clock_time: string;
  advanced_by_minutes: number;
  previous_virtual_clock_time: string | null;
}


/** Configured predictor status and bounded training provenance. */
export interface IntelligenceModelStatusResponse extends SyntheticNotice {
  active_predictor: string;
  mode: 'deterministic_default' | 'deterministic_fallback' | 'local_model' | string;
  fallback_mode: boolean;
  feature_schema_version: string;
  training: IntelligenceModelTraining;
}

export interface JudgeDemoStage {
  stage_number: number;
  name: string;
  label: string;
  status: 'PASSED' | 'BLOCKED' | 'ESCALATED' | 'INFO' | string;
  detail: string;
  payload: Record<string, unknown>;
}

export interface JudgeDemoResponse extends SyntheticNotice {
  case_id: string;
  payment_id: string;
  amount: Money;
  evidence_source: string;
  is_real_razorpay: boolean;
  razorpay_order_id: string | null;
  razorpay_payment_id: string | null;
  ai_root_cause: string;
  ai_confidence: number;
  ai_recommended_action: string;
  ai_reasoning: string;
  selected_action: string | null;
  expected_recovery_value: Money | null;
  gross_recovery: Money | null;
  intervention_cost: Money | null;
  friction_penalty: Money | null;
  policy_outcome: string | null;
  policy_rule_id: string | null;
  policy_reason: string | null;
  final_case_state: string;
  execution_status: string | null;
  recovered_amount: Money;
  is_recovered: boolean;
  stages: JudgeDemoStage[];
}

export interface CustomerRecoveryViewResponse {
  case_id: string;
  payment_id: string;
  order_id: string | null;
  merchant_name: string;
  amount: Money;
  status: 'PENDING_RECOVERY' | 'RECOVERED' | 'EXPIRED';
  failure_reason: FailureReason;
  failure_title: string;
  failure_explanation: string;
  recommended_action: ActionType;
  solution_title: string;
  solution_description: string;
  action_type: 'UPI_QR' | 'ALTERNATIVE_PAYMENT' | 'SMART_RETRY';
  available_methods: string[];
  simulated_upi_qr: string;
  cooldown_seconds: number;
  expires_at: string | null;
}

export interface CustomerRecoveryExecutionRequest {
  selected_method: string;
  instrument_details?: Record<string, unknown>;
}

export interface CustomerRecoveryExecutionResponse {
  success: boolean;
  receipt_id: string;
  case_id: string;
  payment_id: string;
  amount_recovered: Money;
  recovered_at: string;
  message: string;
}

export interface GatewayFailureSimulationRequest {
  failure_reason: FailureReason;
  error_description?: string;
  payment_method?: string;
}

export interface GatewayFailureSimulationResponse {
  data_source: string;
  notice: string;
  payment: PaymentRead;
  recovery_case_id: string;
  recovery_case_state: string;
  failure_reason: FailureReason;
  diagnosis_explanation: string;
  selected_action: ActionType | null;
  policy_outcome: string;
  customer_recovery_url: string;
}

export interface SendRecoveryEmailRequest {
  recipient_email: string;
  customer_name?: string;
  portal_base_url?: string;
}

export interface SendRecoveryEmailResponse {
  success: boolean;
  provider: string;
  recipient: string;
  message: string;
  message_id?: string | null;
  mailto_fallback_url?: string | null;
  error?: string | null;
}

export interface VoiceRecoveryRequest {
  customer_phone: string;
  customer_name?: string;
  portal_base_url?: string;
}

export interface VoiceRecoveryResponse {
  case_id: string;
  channel: string;
  status: string;
  call_id?: string | null;
  payment_link: string;
  policy_decision: string;
  message: string;
  success: boolean;
  error?: string | null;
}

