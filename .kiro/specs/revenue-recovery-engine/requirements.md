# Requirements Document

## Introduction

RevivePay is an autonomous revenue recovery system for merchants. Revenue is lost when payments fail, when payment infrastructure degrades temporarily, when checkouts are abandoned, and when subscription charges fail. Conventional systems respond with generic retry loops or static rule tables that optimize for retry count.

RevivePay optimizes for expected recovered revenue instead. For every payment whose revenue is at risk, RevivePay detects the risk, diagnoses the cause, builds a structured context, generates the recovery actions that are plausible for that cause, scores a recovery probability for each action, calculates the expected recovery value of each action, ranks the actions, selects the best policy-eligible action, passes the selection through a safety policy guard, executes exactly one bounded action through a payment simulator, verifies the resulting payment state independently, records the actual revenue recovered, and emits a complete audit trail explaining every step.

This document covers **Phase 0 only**: the complete, working, end-to-end foundation. Every component listed here is a real working implementation, not a placeholder. Phase 0 uses deterministic scoring rather than machine learning, but it establishes the component interfaces that Phase 1 will extend, so that replacing deterministic diagnosis and prediction with ML or LLM implementations requires no redesign of the surrounding system.

The build target is a hackathon MVP implementable in a few days at zero cost. All payment behaviour is simulated. No real money moves, no production payment infrastructure is contacted, and the application runs fully offline with no paid API key.

The repository is greenfield. It currently contains only this spec directory: no Python source, no FastAPI application, no database, no services, no workflow, no simulator, and no tests. Nothing existing needs to be preserved.

Technology decisions are locked: Python 3, FastAPI with a `create_app()` application factory, a modular monolith laid out as `app/{api,core,db,models,schemas,services,integrations,workflows,ml}` plus `scripts/`, SQLAlchemy 2.0 over SQLite via `DATABASE_URL`, pydantic v2 with pydantic-settings behind `get_settings()`, `create_all()` plus a seed command instead of Alembic, and pytest for tests. There is no frontend: the deliverable surface is the HTTP API, the generated FastAPI `/docs`, and CLI scripts.

## Glossary

- **RevivePay**: The complete system described by this document.
- **API_Layer**: The FastAPI routing layer in `app/api`. Contains thin handlers that validate input, delegate to services, and serialize responses.
- **Workflow_Orchestrator**: The `RevenueRecoveryWorkflow` component in `app/workflows` that sequences all recovery stages for one Recovery_Case run. The orchestration boundary.
- **Risk_Detector**: The `RiskDetector` component that decides whether a payment represents revenue at risk.
- **Diagnosis_Engine**: The `DiagnosisEngine` component that classifies why revenue is at risk and produces a structured diagnosis.
- **Context_Builder**: The `RecoveryContextBuilder` component that builds a Recovery_Context from persisted domain records.
- **Recovery_Context**: A single read-only structure holding the Payment, the Customer, all payment attempts, previous recovery actions, previous recovery outcomes, failure history, and the derived scoring features for one payment.
- **Candidate_Generator**: The component that produces the set of plausible recovery actions for a diagnosis. Holds all per-Failure_Reason branching.
- **Recovery_Predictor**: The component in `app/ml` exposing `predict(context, action) -> PredictionResult`, backed in Phase 0 by deterministic scoring logic.
- **PredictionResult**: A structure containing probability, confidence, model_version, features_used, and explanation.
- **Expected_Value_Calculator**: The `ExpectedRecoveryCalculator` component that computes the expected recovery value of a candidate action and its full breakdown.
- **Expected_Recovery_Value**: `recovery_probability x payment_amount - intervention_cost - customer_friction_penalty`, abbreviated ERV.
- **Decision_Engine**: The `RecoveryDecisionEngine` component that scores, ranks, and selects among candidate actions.
- **Policy_Engine**: The `PolicyEngine` / `RecoveryGuard` component that approves, blocks, or escalates a selected action based on configurable safety rules. The mandatory execution gate.
- **Policy_Outcome**: The result of Policy_Engine evaluation, one of APPROVED, BLOCKED, or ESCALATED, together with the deciding rule identifier and a human-readable reason.
- **Action_Executor**: The `ActionExecutor` interface in `app/integrations` exposing `execute(action, payment_context)`. The only component permitted to execute recovery actions. Provider-independent.
- **Payment_Simulator**: The `PaymentSimulatorExecutor` implementation of Action_Executor. The only Action_Executor implementation in Phase 0. Simulates payment provider behaviour deterministically.
- **Outcome_Verifier**: The `OutcomeVerifier` component that independently verifies payment state after execution and produces a Recovery_Outcome. Separate from execution.
- **Recovery_Outcome**: A record containing the action reference, previous_payment_status, new_payment_status, recovered, recovered_amount, failure_reason, and verification_timestamp.
- **State_Machine**: The component that owns Recovery_Case lifecycle states and permitted transitions.
- **Recovery_Case**: The unit of recovery work tracking one at-risk payment through the lifecycle, identified by case_id.
- **Policy_Guard_Order**: The fixed execution order Prediction -> Decision -> Policy -> Execution.
- **Audit_Service**: The centralized component that records immutable Audit_Event records.
- **Audit_Event**: A stored record containing event ID, case ID, payment ID, stage, event type, message, metadata, and timestamp.
- **Analytics_Service**: The component that aggregates revenue and recovery metrics from persisted records.
- **Virtual_Clock**: The component providing the current simulation time and supporting explicit time advancement. Deterministic, with no background scheduling.
- **Scenario_Generator**: The seeded generator that creates synthetic customers, payments, attempts, and failures for demos and tests.
- **Demo_Script**: The `scripts/demo.py` CLI script that prints a readable walkthrough of the complete workflow.
- **Configuration_Service**: The pydantic-settings based `get_settings()` provider of all runtime configuration.
- **Test_Suite**: The pytest based automated test suite.
- **Minor_Units**: Integer currency amounts in the smallest denomination of the currency, paise for the default currency INR.
- **Failure_Reason**: The enumerated cause of a non-successful payment: BANK_TIMEOUT, INSUFFICIENT_FUNDS, EXPIRED_CARD, NETWORK_ERROR, CHECKOUT_ABANDONMENT, SUBSCRIPTION_FAILURE, and UNKNOWN.
- **Action_Type**: The enumerated recovery action: RETRY_NOW, RETRY_LATER, SEND_PAYMENT_LINK, CHANGE_PAYMENT_METHOD, SEND_REMINDER, ESCALATE_HUMAN, and STOP.

## Requirements

### Requirement 1: Application Foundation and Configuration

**User Story:** As a developer, I want a modular FastAPI application skeleton with centralized configuration and logging, so that every component plugs into a consistent foundation.

#### Acceptance Criteria

1. THE RevivePay SHALL expose an application factory function `create_app()` in `app/main.py` that returns a configured FastAPI application.
2. THE RevivePay SHALL organize source code into the packages `app/api`, `app/core`, `app/db`, `app/models`, `app/schemas`, `app/services`, `app/integrations`, `app/workflows`, and `app/ml`, plus a top-level `scripts` directory.
3. THE Configuration_Service SHALL load `APP_NAME`, `VERSION`, `ENVIRONMENT`, `API_PREFIX`, `LOG_LEVEL`, `DATABASE_URL`, and `BACKEND_CORS_ORIGINS` from environment variables using pydantic-settings and SHALL expose the loaded values through a `get_settings()` function.
4. THE Configuration_Service SHALL additionally load the simulation seed, the RETRY_LATER delay, the maximum automatic retry count, the high-value escalation threshold, and the per-Action_Type intervention cost and customer friction penalty values.
5. THE RevivePay SHALL include an `.env.example` file listing every environment variable the Configuration_Service reads, each with a working local default value.
6. WHEN `create_app()` is called, THE RevivePay SHALL invoke `configure_logging()` from `app/core/logging.py` before registering routes.
7. WHEN a request completes, THE API_Layer SHALL add a response header carrying the elapsed request duration in milliseconds.
8. IF a request raises a handled application error, THEN THE API_Layer SHALL return the response body `{"error": {"code": <string>, "message": <string>}}` with the HTTP status code mapped to that error.
9. THE API_Layer SHALL restrict route handlers to input validation, service delegation, and response serialization, and SHALL place recovery logic in `app/services`, `app/workflows`, or `app/ml` modules.
10. THE RevivePay SHALL declare only the dependencies fastapi, uvicorn, pydantic, pydantic-settings, SQLAlchemy, and pytest, plus their transitive requirements.

### Requirement 2: Domain Model and Persistence

**User Story:** As a developer, I want persisted domain entities that capture enough detail for later machine learning decisions, so that prediction, policy, and audit all read from one consistent model.

#### Acceptance Criteria

1. THE RevivePay SHALL define SQLAlchemy 2.0 models for exactly seven entities: Customer, Payment, PaymentAttempt, RecoveryCase, RecoveryAction, RecoveryOutcome, and AuditEvent.
2. THE Payment model SHALL contain the fields payment_id, customer_id, amount, currency, payment_method, status, created_at, updated_at, attempt_count, failure_reason, merchant_id, and metadata.
3. THE Customer model SHALL contain the fields customer_id, historical_payment_count, successful_payment_count, failed_payment_count, historical_success_rate, average_transaction_value, subscription_status, and metadata.
4. THE RecoveryCase model SHALL contain the fields case_id, payment_id, state, amount_at_risk, diagnosis, created_at, updated_at, and the terminal outcome summary.
5. THE RecoveryAction model SHALL contain the fields action_id, case_id, payment_id, action_type, estimated_probability, expected_recovery_value, the ERV breakdown, risk_level, policy_outcome, policy_rule_id, policy_reason, decision_explanation, status, created_at, scheduled_at, and executed_at.
6. THE RecoveryOutcome model SHALL contain the fields outcome_id, action_id, previous_payment_status, new_payment_status, recovered, recovered_amount, failure_reason, and verification_timestamp.
7. THE AuditEvent model SHALL contain the fields event_id, case_id, payment_id, stage, event_type, message, metadata, and timestamp.
8. THE RevivePay SHALL store every monetary field as Minor_Units in an integer column and SHALL default the currency field to INR.
9. THE RevivePay SHALL define relationships from Customer to Payment, from Payment to PaymentAttempt, from Payment to RecoveryCase, from RecoveryCase to RecoveryAction, from RecoveryAction to RecoveryOutcome, and from RecoveryCase to AuditEvent.
10. THE RevivePay SHALL define indexes on Payment.customer_id, Payment.status, RecoveryCase.payment_id, RecoveryCase.state, RecoveryAction.case_id, and AuditEvent.case_id.
11. THE RevivePay SHALL connect to the database using the `DATABASE_URL` value from the Configuration_Service and SHALL create the schema through a `create_all()` based initialization command without Alembic.
12. THE RevivePay SHALL persist domain records through modules in `app/db` and `app/services` that accept and return domain structures, so that domain logic runs without an HTTP request present.

### Requirement 3: Enumerations and Shared Constants

**User Story:** As a developer, I want every status and action expressed as an enumeration, so that no component compares free-text strings.

#### Acceptance Criteria

1. THE RevivePay SHALL define enumerations for payment status, Recovery_Case state, Failure_Reason, Action_Type, recovery action status, Policy_Outcome, risk level, workflow stage, and audit event type in a shared constants module under `app/core`.
2. THE Failure_Reason enumeration SHALL contain exactly the members BANK_TIMEOUT, INSUFFICIENT_FUNDS, EXPIRED_CARD, NETWORK_ERROR, CHECKOUT_ABANDONMENT, SUBSCRIPTION_FAILURE, and UNKNOWN.
3. THE Action_Type enumeration SHALL contain the members RETRY_NOW, RETRY_LATER, SEND_PAYMENT_LINK, CHANGE_PAYMENT_METHOD, SEND_REMINDER, ESCALATE_HUMAN, and STOP, and SHALL permit additional members to be added without modifying Decision_Engine, Policy_Engine, or Action_Executor interfaces.
4. THE Policy_Outcome enumeration SHALL contain exactly the members APPROVED, BLOCKED, and ESCALATED.
5. THE RevivePay SHALL reference enumeration members by symbol in all components and SHALL confine string representations to serialization boundaries and database storage.
6. IF a request supplies a value outside a declared enumeration, THEN THE API_Layer SHALL return HTTP 422 with the standard error envelope and a message naming the invalid field.

### Requirement 4: Payment Ingestion and Failure Simulation

**User Story:** As a demo operator, I want to create and fail synthetic payments through the API, so that I can trigger the recovery pipeline on demand.

#### Acceptance Criteria

1. WHEN a client sends `POST /payments/simulate` with a valid payload, THE API_Layer SHALL create a Payment with the requested status, create the corresponding PaymentAttempt, and return the created Payment.
2. WHEN a client sends `POST /payments/{payment_id}/fail` with a Failure_Reason, THE API_Layer SHALL set the Payment status to FAILED, record the Failure_Reason on the Payment, increment attempt_count, and create a PaymentAttempt recording the failed attempt.
3. THE RevivePay SHALL treat CHECKOUT_ABANDONMENT and SUBSCRIPTION_FAILURE as Failure_Reason values on ordinary Payment records rather than as separate entities, and SHALL carry failure provenance on the Payment and PaymentAttempt records.
4. IF `POST /payments/{payment_id}/fail` names a payment_id that has no stored Payment, THEN THE API_Layer SHALL return HTTP 404 with the standard error envelope.
5. THE API_Layer SHALL serve `GET /payments` with pagination parameters and `GET /payments/{payment_id}` returning one Payment with its attempt history.
6. THE RevivePay SHALL mark every Payment and Customer created by simulation or seeding as synthetic demonstration data in a stored field.

### Requirement 5: Revenue Risk Detection

**User Story:** As a merchant, I want RevivePay to identify which payments put revenue at risk, so that recovery effort targets real losses.

#### Acceptance Criteria

1. WHEN a Payment reaches a non-successful status, THE Risk_Detector SHALL evaluate that Payment for revenue risk using a single detection path shared by all Failure_Reason values.
2. WHEN THE Risk_Detector classifies a Payment as revenue at risk, THE RevivePay SHALL create one Recovery_Case in state DETECTED referencing that payment_id and SHALL record the amount at risk in Minor_Units.
3. WHERE a Recovery_Case already exists for a payment_id in a non-terminal state, THE Risk_Detector SHALL reuse that Recovery_Case instead of creating a second Recovery_Case.
4. WHEN THE Risk_Detector creates a Recovery_Case, THE Audit_Service SHALL record an Audit_Event of type REVENUE_RISK_DETECTED containing the payment_id, the amount at risk, and the Failure_Reason.
5. WHEN a Payment holds a successful status, THE Risk_Detector SHALL classify that Payment as not at risk and SHALL return a result carrying the reason for that classification.

### Requirement 6: Recovery Context Building

**User Story:** As a developer, I want one reusable context structure, so that downstream components stop querying database models directly.

#### Acceptance Criteria

1. WHEN THE Workflow_Orchestrator processes a Recovery_Case, THE Context_Builder SHALL build one Recovery_Context combining the Payment, the Customer, all PaymentAttempt records for that Payment, all previous RecoveryAction records, all previous Recovery_Outcome records, and the failure history.
2. THE Context_Builder SHALL derive and expose the structured scoring features payment_amount, payment_method, failure_reason, attempt_count, customer_success_rate, customer_failed_payments, customer_total_payments, subscription_status, transaction_hour, is_returning_customer, days_since_previous_payment, previous_recovery_attempt_count, and the Action_Type values already attempted.
3. THE Context_Builder SHALL derive transaction_hour and days_since_previous_payment from the Virtual_Clock time and stored timestamps rather than from wall-clock time at call time.
4. WHEN THE Context_Builder receives the same persisted state twice, THE Context_Builder SHALL produce identical Recovery_Context feature values.
5. THE Context_Builder SHALL expose the Recovery_Context as a read-only structure whose fields are accessible without further database queries.
6. THE Diagnosis_Engine, Candidate_Generator, Recovery_Predictor, Decision_Engine, Expected_Value_Calculator, and Policy_Engine SHALL read payment and customer data from the Recovery_Context.
7. IF the referenced Customer record is missing, THEN THE Context_Builder SHALL populate the customer section with documented neutral defaults and SHALL set a flag marking the customer history as unavailable.

### Requirement 7: Failure Diagnosis

**User Story:** As a merchant, I want each at-risk payment diagnosed, so that recovery decisions respond to the actual cause.

#### Acceptance Criteria

1. WHEN THE Workflow_Orchestrator advances a Recovery_Case from DETECTED, THE Diagnosis_Engine SHALL produce a diagnosis containing the resolved Failure_Reason, a failure category, a transience classification, and a human-readable explanation.
2. THE Diagnosis_Engine SHALL classify BANK_TIMEOUT and NETWORK_ERROR as transient, EXPIRED_CARD as requiring customer action, INSUFFICIENT_FUNDS as time-dependent, and CHECKOUT_ABANDONMENT and SUBSCRIPTION_FAILURE as customer-engagement dependent.
3. IF the stored Failure_Reason is absent or unrecognized, THEN THE Diagnosis_Engine SHALL resolve the Failure_Reason to UNKNOWN and SHALL mark the diagnosis as requiring escalation.
4. THE Diagnosis_Engine SHALL derive the diagnosis from the Recovery_Context alone, so that repeated diagnosis of unchanged data yields an identical diagnosis.
5. WHEN a diagnosis is produced, THE RevivePay SHALL persist the diagnosis on the Recovery_Case and THE Audit_Service SHALL record an Audit_Event of type DIAGNOSIS_COMPLETED containing the resolved Failure_Reason, the transience classification, and the explanation.
6. THE Diagnosis_Engine SHALL sit behind a declared interface, so that a later LLM-backed implementation replaces it without changes to the Workflow_Orchestrator.

### Requirement 8: Candidate Action Generation

**User Story:** As a merchant, I want only plausible recovery actions considered for each failure cause, so that RevivePay evaluates sensible options.

#### Acceptance Criteria

1. WHEN THE Workflow_Orchestrator requests candidates, THE Candidate_Generator SHALL return a list of candidate Action_Type values derived from the diagnosis and the Recovery_Context, and SHALL return no selected action.
2. WHERE the resolved Failure_Reason is BANK_TIMEOUT, THE Candidate_Generator SHALL include RETRY_NOW, RETRY_LATER, and SEND_PAYMENT_LINK.
3. WHERE the resolved Failure_Reason is EXPIRED_CARD, THE Candidate_Generator SHALL include CHANGE_PAYMENT_METHOD, SEND_PAYMENT_LINK, and ESCALATE_HUMAN.
4. WHERE the resolved Failure_Reason is INSUFFICIENT_FUNDS, THE Candidate_Generator SHALL include RETRY_LATER, SEND_PAYMENT_LINK, and SEND_REMINDER.
5. WHERE the resolved Failure_Reason is CHECKOUT_ABANDONMENT, THE Candidate_Generator SHALL include SEND_REMINDER and SEND_PAYMENT_LINK.
6. WHERE the resolved Failure_Reason is NETWORK_ERROR, THE Candidate_Generator SHALL include RETRY_NOW and RETRY_LATER.
7. WHERE the resolved Failure_Reason is SUBSCRIPTION_FAILURE, THE Candidate_Generator SHALL include RETRY_LATER, SEND_REMINDER, and SEND_PAYMENT_LINK.
8. WHERE the resolved Failure_Reason is UNKNOWN, THE Candidate_Generator SHALL include ESCALATE_HUMAN and STOP.
9. THE Candidate_Generator SHALL hold all per-Failure_Reason branching, so that Risk_Detector, Recovery_Predictor, and Decision_Engine contain no per-reason branching.
10. THE Candidate_Generator SHALL exclude Action_Type values already attempted unsuccessfully for the Payment where an alternative candidate remains available.

### Requirement 9: Deterministic Recovery Probability Prediction

**User Story:** As a merchant, I want a recovery probability per candidate action, so that selection reflects the situation rather than a fixed ordering.

#### Acceptance Criteria

1. THE Recovery_Predictor SHALL expose `predict(context, action)` returning a PredictionResult containing probability, confidence, model_version, features_used, and explanation.
2. THE Recovery_Predictor SHALL return a probability value in the inclusive range 0.0 to 1.0.
3. THE Recovery_Predictor SHALL compute the probability from deterministic scoring logic over the Recovery_Context features and the candidate Action_Type, using no machine learning library and no network call.
4. WHEN THE Recovery_Predictor receives the same Recovery_Context and the same Action_Type twice, THE Recovery_Predictor SHALL return an identical PredictionResult.
5. THE Recovery_Predictor SHALL populate `model_version` with an identifier naming the deterministic scorer and its version.
6. THE Recovery_Predictor SHALL populate `features_used` with the feature names that contributed to the score and `explanation` with the contributing scoring factors ordered by influence.
7. THE Recovery_Predictor SHALL score RETRY_LATER above RETRY_NOW for a transient time-dependent Failure_Reason, and SHALL score CHANGE_PAYMENT_METHOD above RETRY_NOW for EXPIRED_CARD.
8. THE Recovery_Predictor SHALL reduce the probability as the Payment attempt_count rises and SHALL raise the probability as the customer historical success rate rises.
9. THE Recovery_Predictor SHALL remain behind the Recovery_Predictor interface in `app/ml`, so that replacing the deterministic scorer with a machine learning model requires no change to Decision_Engine, Policy_Engine, or Action_Executor code.

### Requirement 10: Expected Recovery Value Calculation

**User Story:** As a merchant, I want each candidate valued in money with a full breakdown, so that selection optimizes recovered revenue rather than attempt count.

#### Acceptance Criteria

1. THE Expected_Value_Calculator SHALL compute Expected_Recovery_Value as `recovery_probability x payment_amount - intervention_cost - customer_friction_penalty` in Minor_Units.
2. THE Expected_Value_Calculator SHALL return a breakdown containing recovery_probability, payment_amount, gross_expected_recovery, intervention_cost, customer_friction_penalty, and expected_recovery_value.
3. WHEN THE Expected_Value_Calculator receives a payment_amount of 1,000,000 Minor_Units, Action_Type RETRY_LATER, a probability of 0.72, an intervention_cost of 2,000 Minor_Units, and a customer_friction_penalty of 10,000 Minor_Units, THE Expected_Value_Calculator SHALL return gross_expected_recovery 720,000 Minor_Units and expected_recovery_value 708,000 Minor_Units.
4. THE RevivePay SHALL implement the Expected_Recovery_Value formula in exactly one calculator service module, and SHALL have all other components obtain values by calling that module.
5. THE Expected_Value_Calculator SHALL read per-Action_Type intervention_cost and customer_friction_penalty values from the Configuration_Service and SHALL apply documented defaults when a value is not configured.
6. WHEN an action is selected, THE RevivePay SHALL store the Expected_Recovery_Value breakdown on the RecoveryAction record.

### Requirement 11: Recovery Decision Engine and Ranking

**User Story:** As a merchant, I want the highest-value permitted action selected with a stated reason, so that every decision is defensible.

#### Acceptance Criteria

1. WHEN THE Workflow_Orchestrator requests a decision, THE Decision_Engine SHALL for each candidate obtain a PredictionResult from the Recovery_Predictor, obtain an Expected_Recovery_Value breakdown from the Expected_Value_Calculator, and assign a risk level.
2. WHEN all candidates are scored, THE Decision_Engine SHALL rank the candidates in descending Expected_Recovery_Value order and SHALL break ties by a documented deterministic rule.
3. THE Decision_Engine SHALL select the highest-ranked candidate and SHALL record a decision explanation naming the selected Action_Type and the Expected_Recovery_Value basis for the selection.
4. THE Decision_Engine SHALL return the decision as a data structure as its only output, and SHALL perform no payment execution and no Payment state change.
5. IF the candidate list is empty, THEN THE Decision_Engine SHALL select ESCALATE_HUMAN when the diagnosis permits human handling and SHALL select STOP otherwise, and SHALL record the reason for that outcome.
6. WHEN candidates are evaluated, THE Audit_Service SHALL record an Audit_Event of type RECOVERY_OPTIONS_EVALUATED containing the ordered candidates with their probability and Expected_Recovery_Value, and WHEN a candidate is selected THE Audit_Service SHALL record an Audit_Event of type RECOVERY_DECISION_SELECTED containing the selected Action_Type and the explanation.
7. THE RevivePay SHALL run the stages in Policy_Guard_Order for every Recovery_Case run.

### Requirement 12: Decision Explanation

**User Story:** As a merchant, I want a structured explanation of each choice, so that a later interface can answer "why did the system choose this?".

#### Acceptance Criteria

1. WHEN THE Decision_Engine selects an action, THE RevivePay SHALL store a structured explanation on the RecoveryAction containing selected_action, reason, probability, expected_recovery_value, confidence, and an alternatives array.
2. THE RevivePay SHALL include in every alternatives entry the action, the probability, and the expected_recovery_value.
3. THE Decision_Engine SHALL express `reason` as a sentence naming the selected Action_Type and the Expected_Recovery_Value basis for the selection.
4. WHEN a client sends `GET /recovery/cases/{case_id}`, THE API_Layer SHALL return the structured explanation for the most recent RecoveryAction.
5. THE RevivePay SHALL store the structured explanation in the same form on the RecoveryAction record and in the corresponding Audit_Event metadata.

### Requirement 13: Policy Engine and Safety Guard

**User Story:** As a merchant, I want a configurable safety guard in front of every action, so that autonomous recovery stays bounded.

#### Acceptance Criteria

1. WHEN THE Workflow_Orchestrator holds a decision, THE Policy_Engine SHALL evaluate the selected action and SHALL return a Policy_Outcome of APPROVED, BLOCKED, or ESCALATED together with the deciding rule identifier and a human-readable reason.
2. THE Policy_Engine SHALL read the maximum automatic retry count defaulting to 2, the high-value escalation threshold, and the repeated-failure limit from the Configuration_Service.
3. IF the Payment attempt_count has reached the configured maximum automatic retry count and the selected action is a retry action, THEN THE Policy_Engine SHALL return BLOCKED with a retry-limit rule identifier and THE State_Machine SHALL move the Recovery_Case to STOPPED.
3a. THE RevivePay SHALL treat the configured maximum automatic retry count as a **global automatic-recovery safety boundary** called the recovery budget, not merely a cap on retries.
3b. IF the Payment attempt_count has reached the configured maximum automatic retry count, THEN THE Policy_Engine SHALL return BLOCKED for every automatic recovery Action_Type, including RETRY_NOW, RETRY_LATER, SEND_PAYMENT_LINK, SEND_REMINDER, CHANGE_PAYMENT_METHOD, and any Action_Type added later, and THE State_Machine SHALL move the Recovery_Case to STOPPED.
3c. WHERE the selected Action_Type is ESCALATE_HUMAN or STOP, THE Policy_Engine SHALL NOT block the action on the grounds of an exhausted recovery budget, because neither Action_Type attempts a charge and both are valid dispositions for an exhausted case.
3d. WHEN the recovery budget is exhausted, THE RevivePay SHALL NOT invoke the Action_Executor for that Recovery_Case, so that no automatic recovery action executes after the boundary is reached.
3e. THE Candidate_Generator and THE Decision_Engine SHALL remain independent of the recovery budget: candidate generation and expected-value ranking SHALL produce identical results whether or not the budget is exhausted, and enforcement SHALL reside solely in the Policy_Engine.
4. IF the payment amount exceeds the configured high-value escalation threshold, THEN THE Policy_Engine SHALL return ESCALATED and THE State_Machine SHALL move the Recovery_Case to ESCALATED.
5. IF the resolved Failure_Reason is UNKNOWN, THEN THE Policy_Engine SHALL return ESCALATED when human handling is permitted and BLOCKED otherwise.
6. IF the Payment status is not a state from which the selected action is valid, THEN THE Policy_Engine SHALL return BLOCKED naming the invalid state.
7. IF the selected Action_Type is not supported by the configured Action_Executor, THEN THE Policy_Engine SHALL return BLOCKED naming the unsupported Action_Type.
8. IF the count of previous unsuccessful Recovery_Outcome records for the Payment has reached the configured repeated-failure limit, THEN THE Policy_Engine SHALL return BLOCKED.
9. THE RevivePay SHALL route every recovery action through the Policy_Engine before execution, and SHALL restrict execution authority to the Action_Executor.
10. WHEN a Policy_Outcome is produced, THE RevivePay SHALL persist the outcome, the rule identifier, and the reason on the RecoveryAction, and THE Audit_Service SHALL record an Audit_Event of type POLICY_APPROVED, POLICY_BLOCKED, or POLICY_ESCALATED containing the rule identifier, the reason, and the evaluated action.
11. THE Policy_Engine SHALL express all rules in one configurable rule-set module, so that no policy rule is implemented inside an API route handler.
12. THE Policy_Engine SHALL evaluate rules in a documented fixed order and SHALL return the outcome of the first rule that blocks or escalates.

### Requirement 14: Action Execution Through the Payment Simulator

**User Story:** As a developer, I want execution behind one provider-independent interface implemented by a deterministic simulator, so that no real money moves and a real provider can be added later.

#### Acceptance Criteria

1. THE Action_Executor SHALL expose `execute(action, payment_context)` returning a structured execution result containing the executed Action_Type, an execution status, a simulated provider response, and a timestamp from the Virtual_Clock.
2. THE RevivePay SHALL provide Payment_Simulator as the only Action_Executor implementation in Phase 0, and SHALL contact no external payment provider.
3. THE Payment_Simulator SHALL simulate a successful retry, a failed retry, a delayed retry, a payment link recovery, an alternative payment method recovery, an escalation, and a stopped action.
4. THE Payment_Simulator SHALL support the scenarios BANK_TIMEOUT, INSUFFICIENT_FUNDS, EXPIRED_CARD, NETWORK_ERROR, CHECKOUT_ABANDONMENT, and SUBSCRIPTION_FAILURE.
5. WHERE the scenario is BANK_TIMEOUT, THE Payment_Simulator SHALL fail the initial payment and SHALL succeed on RETRY_LATER.
6. WHERE the scenario is EXPIRED_CARD, THE Payment_Simulator SHALL fail RETRY_NOW and SHALL succeed on CHANGE_PAYMENT_METHOD.
7. WHERE the scenario is INSUFFICIENT_FUNDS, THE Payment_Simulator SHALL fail repeated retries so that the configured retry limit is reached.
8. THE Payment_Simulator SHALL derive every simulated outcome from the seed supplied by the Configuration_Service together with the payment identity and the attempt number, so that identical seed and identical input produce identical outcomes across runs and machines.
9. THE Payment_Simulator SHALL read per-scenario success probabilities from the Configuration_Service and SHALL label those probabilities as synthetic demonstration values.
10. WHEN THE Payment_Simulator succeeds, THE RevivePay SHALL update the Payment status to the successful status and SHALL create a PaymentAttempt recording the successful attempt.
11. THE RevivePay SHALL resolve the Action_Executor implementation through the Configuration_Service in `app/integrations`, so that adding a provider-backed executor requires no change to Decision_Engine, Policy_Engine, or Workflow_Orchestrator code.
12. WHEN execution completes, THE Audit_Service SHALL record an Audit_Event of type ACTION_EXECUTED or ACTION_FAILED containing the Action_Type, the execution status, and the simulated provider response.

### Requirement 15: Outcome Verification

**User Story:** As a judge, I want recovery claims verified against payment state, so that reported revenue reflects actual recovery.

#### Acceptance Criteria

1. WHEN an action execution completes, THE Outcome_Verifier SHALL read the resulting Payment state and SHALL produce a Recovery_Outcome containing the action reference, previous_payment_status, new_payment_status, recovered, recovered_amount, failure_reason, and verification_timestamp.
2. THE Outcome_Verifier SHALL determine `recovered` from the verified Payment state rather than from the execution status returned by the Action_Executor.
3. WHEN the verified transition is from a failed status to a successful status, THE Outcome_Verifier SHALL set `recovered` to true and SHALL set recovered_amount to the verified Payment amount in Minor_Units.
4. WHEN the verified new_payment_status is not a successful status, THE Outcome_Verifier SHALL set `recovered` to false and SHALL set recovered_amount to zero.
5. THE Outcome_Verifier SHALL be implemented as a component separate from the Action_Executor and SHALL not call the Action_Executor.
6. WHEN a Recovery_Outcome is produced, THE Audit_Service SHALL record an Audit_Event of type OUTCOME_VERIFIED, and WHEN `recovered` is true THE Audit_Service SHALL additionally record an Audit_Event of type REVENUE_RECOVERED containing the recovered_amount.
7. THE Analytics_Service SHALL compute recovered revenue from persisted Recovery_Outcome records only.

### Requirement 16: Recovery Case State Machine

**User Story:** As a developer, I want enforced lifecycle transitions, so that no action reaches execution without passing decision and policy stages.

#### Acceptance Criteria

1. THE State_Machine SHALL define the states DETECTED, DIAGNOSING, DIAGNOSED, EVALUATING, DECISION_READY, POLICY_CHECK, APPROVED, BLOCKED, SCHEDULED, EXECUTING, VERIFYING, RECOVERED, FAILED, ESCALATED, and STOPPED.
2. THE State_Machine SHALL permit the forward path DETECTED -> DIAGNOSING -> DIAGNOSED -> EVALUATING -> DECISION_READY -> POLICY_CHECK -> APPROVED -> EXECUTING -> VERIFYING.
3. THE State_Machine SHALL permit POLICY_CHECK to transition to BLOCKED and to ESCALATED, and SHALL permit BLOCKED to transition to STOPPED.
4. THE State_Machine SHALL permit APPROVED to transition to SCHEDULED for a delayed action, and SHALL permit SCHEDULED to transition to EXECUTING when the Virtual_Clock reaches the scheduled time.
5. THE State_Machine SHALL permit VERIFYING to transition to RECOVERED and to FAILED.
6. THE State_Machine SHALL treat RECOVERED, ESCALATED, and STOPPED as terminal states and SHALL permit no transition out of a terminal state.
7. THE State_Machine SHALL permit FAILED to transition to DIAGNOSING, so that an unrecovered and unblocked Recovery_Case is re-runnable and re-decides using the updated attempt_count and recovery history.
8. IF a transition request is not in the permitted transition table, THEN THE State_Machine SHALL reject the transition, SHALL leave the Recovery_Case state unchanged, and SHALL raise a domain error naming the source state and the requested target state.
9. THE State_Machine SHALL require a Recovery_Case to pass through DECISION_READY and POLICY_CHECK before entering EXECUTING, and SHALL reject a transition from DETECTED directly to EXECUTING.
10. WHEN a Recovery_Case changes state, THE RevivePay SHALL persist the new state with the transition timestamp from the Virtual_Clock.

### Requirement 17: Recovery Workflow Orchestration

**User Story:** As a demo operator, I want one API call to perform exactly one recovery cycle, so that each step of the demo is observable and repeatable.

#### Acceptance Criteria

1. WHEN a client sends `POST /recovery/cases/{case_id}/run`, THE Workflow_Orchestrator SHALL execute one cycle of gather context, diagnose, generate candidates, predict probability, calculate Expected_Recovery_Value, rank and select, policy check, execute, verify, record audit, and return the result.
2. THE Workflow_Orchestrator SHALL execute at most one recovery action per run.
3. THE Workflow_Orchestrator SHALL be the single orchestration boundary in `app/workflows` and SHALL coordinate components without embedding their logic.
4. WHEN a run completes with a verified Recovery_Outcome where `recovered` is false and the Policy_Engine has not blocked further attempts, THE State_Machine SHALL move the Recovery_Case to FAILED so that a subsequent run re-decides using the updated attempt_count and recovery history.
5. WHEN a run completes with a verified Recovery_Outcome where `recovered` is true, THE State_Machine SHALL move the Recovery_Case to RECOVERED and THE API_Layer SHALL reject further run requests for that Recovery_Case with HTTP 409.
6. WHEN THE Policy_Engine blocks the run because the maximum automatic retry count has been reached, THE State_Machine SHALL move the Recovery_Case to STOPPED and THE Audit_Service SHALL record an Audit_Event of type WORKFLOW_STOPPED with the blocking rule identifier.
7. WHEN THE Policy_Engine escalates the run, THE State_Machine SHALL move the Recovery_Case to ESCALATED and THE Workflow_Orchestrator SHALL execute no action.
8. WHEN a run ends, THE API_Layer SHALL return the Recovery_Case state, the selected Action_Type, the Policy_Outcome, the execution result, the Recovery_Outcome, and the recovered_amount.
9. IF any stage raises an unhandled error, THEN THE Workflow_Orchestrator SHALL record an Audit_Event describing the failed stage, SHALL leave the Recovery_Case in a recoverable persisted state, and THE API_Layer SHALL return the standard error envelope.

### Requirement 18: Virtual Clock and Scheduled Retries

**User Story:** As a demo operator, I want to fast-forward time on demand, so that delayed retries demonstrate deterministically without a scheduler.

#### Acceptance Criteria

1. THE Virtual_Clock SHALL provide the current simulation time to every component that records or reads a timestamp.
2. THE RevivePay SHALL use no real background scheduling, no scheduler library, and no background threads for delayed actions.
3. WHEN THE Decision_Engine selects RETRY_LATER and THE Policy_Engine approves it, THE RevivePay SHALL persist a `scheduled_at` value on the RecoveryAction equal to the Virtual_Clock time plus the configured retry delay, SHALL move the Recovery_Case to SCHEDULED, SHALL execute no payment attempt during that run, and THE Audit_Service SHALL record an Audit_Event of type ACTION_SCHEDULED.
4. THE Configuration_Service SHALL supply the RETRY_LATER delay with a default of 15 minutes.
5. WHILE the Virtual_Clock time is earlier than the RecoveryAction `scheduled_at` value, THE Workflow_Orchestrator SHALL report the Recovery_Case as waiting for the scheduled time and SHALL execute no action for that Recovery_Case.
6. WHEN a client sends `POST /simulate/advance-clock` with a duration, THE Virtual_Clock SHALL advance the simulation time by that duration and SHALL return the new simulation time.
7. THE RevivePay SHALL expose an equivalent CLI mechanism for advancing the Virtual_Clock.
8. WHEN the Virtual_Clock time reaches or passes a RecoveryAction `scheduled_at` value and a run is requested, THE Workflow_Orchestrator SHALL execute the scheduled retry and SHALL verify the outcome.
9. WHEN a Payment fails at simulation time 13:00, RETRY_LATER is scheduled at 13:01 for 13:15, and the Virtual_Clock advances by 15 minutes, THE Workflow_Orchestrator SHALL execute the retry at simulation time 13:15 and THE Outcome_Verifier SHALL verify the outcome at simulation time 13:15.
10. THE RevivePay SHALL advance simulation time only through explicit advance-clock requests, so that repeated demo runs produce identical timelines.

### Requirement 19: Audit Trail

**User Story:** As a judge, I want a complete decision trail per case, so that I can see what happened, why, and what the policy allowed.

#### Acceptance Criteria

1. THE Audit_Service SHALL support exactly the thirteen event types REVENUE_RISK_DETECTED, DIAGNOSIS_COMPLETED, RECOVERY_OPTIONS_EVALUATED, RECOVERY_DECISION_SELECTED, POLICY_APPROVED, POLICY_BLOCKED, POLICY_ESCALATED, ACTION_SCHEDULED, ACTION_EXECUTED, ACTION_FAILED, OUTCOME_VERIFIED, REVENUE_RECOVERED, and WORKFLOW_STOPPED.
2. THE Audit_Service SHALL record on every Audit_Event the event ID, the case ID, the payment ID, the workflow stage, the event type, a human-readable message, a metadata structure, and the Virtual_Clock timestamp.
3. THE Audit_Service SHALL include in decision-related Audit_Event metadata the model_version, the predicted probability, the confidence, the Expected_Recovery_Value, the selected Action_Type, the alternatives, and the explanation.
4. THE Audit_Service SHALL include in policy-related Audit_Event metadata the deciding rule identifier and the reason.
5. THE Audit_Service SHALL append Audit_Event records without updating or deleting existing Audit_Event records.
6. THE RevivePay SHALL record audit events through the centralized Audit_Service only, so that no component writes AuditEvent rows directly.
7. WHEN a client sends `GET /recovery/cases/{case_id}/audit`, THE API_Layer SHALL return the Audit_Event records for that Recovery_Case ordered by timestamp ascending.
8. THE Audit_Service SHALL limit recorded metadata to the fields required by this document, and SHALL record payment method information as a non-sensitive method type rather than as instrument credentials.

### Requirement 20: Revenue and Recovery Analytics

**User Story:** As a merchant, I want revenue and recovery metrics computed from stored data, so that I can see how much revenue was actually recovered.

#### Acceptance Criteria

1. WHEN a client sends `GET /analytics/revenue`, THE Analytics_Service SHALL return revenue at risk, revenue recovered, recovery rate, and average recovery value, with monetary values in Minor_Units.
2. WHEN a client sends `GET /analytics/recovery`, THE Analytics_Service SHALL return the average recovery probability and the counts of actions selected, actions successful, actions failed, actions stopped, and actions escalated.
3. THE Analytics_Service SHALL compute recovery rate as recovered revenue divided by revenue at risk and SHALL return zero when revenue at risk is zero.
4. THE Analytics_Service SHALL derive all metrics from persisted Payment, RecoveryCase, RecoveryAction, and Recovery_Outcome records rather than from in-memory counters.
5. THE Analytics_Service SHALL label every returned metric payload as computed from synthetic simulated data.

### Requirement 21: Synthetic Scenario Generation and Seeding

**User Story:** As a demo operator, I want a seeded scenario generator, so that every demo starts from the same realistic data set.

#### Acceptance Criteria

1. WHEN THE Scenario_Generator runs, THE Scenario_Generator SHALL create synthetic Customer records with historical payment counts, successful and failed payment counts, historical success rate, average transaction value, and subscription status.
2. THE Scenario_Generator SHALL create Payment, PaymentAttempt, and failure records covering the scenarios BANK_TIMEOUT, INSUFFICIENT_FUNDS, EXPIRED_CARD, NETWORK_ERROR, CHECKOUT_ABANDONMENT, and SUBSCRIPTION_FAILURE.
3. THE Scenario_Generator SHALL accept a seed from the Configuration_Service and SHALL produce identical records for an identical seed and version.
4. THE Scenario_Generator SHALL create a deterministic successful-recovery scenario in which a BANK_TIMEOUT failure recovers through RETRY_LATER and the recovered revenue is recorded.
5. THE Scenario_Generator SHALL create a deterministic stopping-rule scenario in which an INSUFFICIENT_FUNDS failure exhausts the configured retry limit and the Recovery_Case reaches STOPPED.
6. THE Scenario_Generator SHALL create a deterministic escalation scenario in which a high-value payment produces a candidate action that the Policy_Engine escalates and the Recovery_Case reaches ESCALATED.
7. THE Scenario_Generator SHALL create a deterministic alternative-recovery scenario in which an EXPIRED_CARD failure recovers through CHANGE_PAYMENT_METHOD.
8. THE Scenario_Generator SHALL mark every generated record as synthetic demonstration data in a stored field.
9. THE RevivePay SHALL expose the Scenario_Generator through a seed command that populates an initialized database.

### Requirement 22: CLI Demo

**User Story:** As a demo operator, I want one command that prints the whole pipeline in readable terminal output, so that I can present the system without a UI.

#### Acceptance Criteria

1. THE RevivePay SHALL provide `scripts/demo.py` that runs against a seeded database and prints a readable walkthrough of the complete workflow.
2. THE Demo_Script SHALL print the payment, the failure, the diagnosis, the candidate actions, the Expected_Recovery_Value per candidate, the selected action, the Policy_Outcome, the execution result, the verification result, the actual revenue recovered, and the Audit_Event trail.
3. WHERE the selected action is RETRY_LATER, THE Demo_Script SHALL print the scheduled time, advance the Virtual_Clock, and print the resulting execution and verification.
4. THE Demo_Script SHALL demonstrate the successful recovery scenario, the stopping-rule scenario, and the human escalation scenario.
5. THE Demo_Script SHALL print a statement identifying all figures as results of a synthetic simulation.
6. THE Demo_Script SHALL invoke the same Workflow_Orchestrator, Policy_Engine, Action_Executor, and Outcome_Verifier components used by the API_Layer.

### Requirement 23: Observability and Logging

**User Story:** As a developer running a live demo, I want readable execution logs and workflow records, so that I can debug a failing step on stage.

#### Acceptance Criteria

1. WHEN THE Workflow_Orchestrator runs, THE RevivePay SHALL record a workflow record containing workflow_id, payment_id, case_id, start timestamp, end timestamp, current state, selected Action_Type, Policy_Outcome, execution result, recovered_amount, and final status.
2. THE RevivePay SHALL emit one log line per workflow stage containing the workflow_id, the stage name, and the stage result.
3. THE RevivePay SHALL emit log output at the level configured by `LOG_LEVEL` through `configure_logging()`.
4. IF a workflow stage raises an error, THEN THE RevivePay SHALL log the workflow_id, the stage name, the error type, and the error message.
5. THE RevivePay SHALL exclude payment instrument credentials and customer contact details from log output.

### Requirement 24: HTTP API Contract

**User Story:** As a demo operator, I want a documented endpoint set, so that the entire flow is drivable from the generated API documentation.

#### Acceptance Criteria

1. THE API_Layer SHALL serve `GET /health` returning the application name, version, environment, and the current Virtual_Clock time.
2. THE API_Layer SHALL serve `GET /payments`, `GET /payments/{payment_id}`, `POST /payments/simulate`, and `POST /payments/{payment_id}/fail`.
3. THE API_Layer SHALL serve `GET /recovery/cases`, `GET /recovery/cases/{case_id}`, `POST /recovery/cases/{case_id}/run`, and `GET /recovery/cases/{case_id}/audit`.
4. THE API_Layer SHALL serve `POST /simulate/advance-clock`, `GET /analytics/revenue`, and `GET /analytics/recovery`.
5. THE API_Layer SHALL mount all routes except `GET /health` under the configured `API_PREFIX`.
6. THE API_Layer SHALL define pydantic v2 request and response schemas in `app/schemas` for every endpoint, so that the generated `/docs` page describes every field.
7. THE API_Layer SHALL return monetary values as integer Minor_Units together with the currency code.
8. IF a path identifier names a record that does not exist, THEN THE API_Layer SHALL return HTTP 404 with the standard error envelope.
9. IF a run is requested for a Recovery_Case in a terminal state, THEN THE API_Layer SHALL return HTTP 409 with the standard error envelope and the current state.

### Requirement 25: Automated Test Coverage

**User Story:** As a developer, I want pytest coverage of every pipeline stage and all three end-to-end paths, so that changes stay safe under hackathon time pressure.

#### Acceptance Criteria

1. THE Test_Suite SHALL cover database initialization, payment creation, failure simulation, risk detection, diagnosis, candidate action generation, recovery probability prediction, Expected_Recovery_Value calculation, decision selection, policy approval, policy blocking, retry limits, the Virtual_Clock, the Payment_Simulator, outcome verification, the audit trail, and analytics.
2. THE Test_Suite SHALL include an end-to-end successful workflow test asserting that a BANK_TIMEOUT failure is detected, diagnosed, evaluated, selected as RETRY_LATER, approved by the Policy_Engine, executed through the Payment_Simulator as a simulated success, verified as recovered, and recorded with the actual recovered amount.
3. THE Test_Suite SHALL include an end-to-end stopped workflow test asserting that an INSUFFICIENT_FUNDS failure produces repeated unsuccessful recovery, reaches the configured retry limit, moves the Recovery_Case to STOPPED, and records a WORKFLOW_STOPPED Audit_Event.
4. THE Test_Suite SHALL include an end-to-end escalation workflow test asserting that a high-value payment has its automatic action blocked by the Policy_Engine, moves the Recovery_Case to ESCALATED, and records a POLICY_ESCALATED Audit_Event.
5. THE Test_Suite SHALL assert that the Context_Builder returns identical feature values for repeated identical persisted state.
6. THE Test_Suite SHALL assert the candidate sets generated for BANK_TIMEOUT, EXPIRED_CARD, INSUFFICIENT_FUNDS, CHECKOUT_ABANDONMENT, NETWORK_ERROR, SUBSCRIPTION_FAILURE, and UNKNOWN.
7. THE Test_Suite SHALL assert the Expected_Recovery_Value breakdown for the worked example in Requirement 10 acceptance criterion 3.
8. THE Test_Suite SHALL assert that the Decision_Engine selects the candidate with the highest Expected_Recovery_Value.
9. THE Test_Suite SHALL assert the RETRY_LATER flow in which a payment fails at simulation time 13:00, RETRY_LATER records `scheduled_at` at 13:15, the Virtual_Clock advances by 15 minutes, the next run executes the scheduled retry, and the Payment is verified as recovered.
10. THE Test_Suite SHALL assert that the State_Machine rejects a transition from DETECTED directly to EXECUTING.
11. THE Test_Suite SHALL assert that the Payment_Simulator produces identical outcomes for an identical seed and identical input across repeated runs.
12. THE Test_Suite SHALL assert that the Outcome_Verifier reports `recovered` as false when the Action_Executor reports a successful execution but the verified Payment status is not successful.
13. THE Test_Suite SHALL assert that an EXPIRED_CARD failure recovers through CHANGE_PAYMENT_METHOD after RETRY_NOW fails.
14. THE Test_Suite SHALL run against a temporary SQLite database created per test session and SHALL require no network access.

### Requirement 26: Developer Documentation

**User Story:** As a developer or judge picking up the repository, I want a README that explains and runs the project, so that I can evaluate it without reading the source.

#### Acceptance Criteria

1. THE RevivePay SHALL provide a `README.md` containing the problem statement, the RevivePay concept, the architecture, the tech stack, the folder structure, setup instructions, the environment variables, database instructions, seed instructions, API documentation, CLI demo instructions, testing instructions, a synthetic-data disclaimer, the Phase 0 limitations, and the future Phase 1 direction.
2. THE RevivePay SHALL document commands for environment setup, database initialization, seeding, running the development server, running the CLI demo, and running the test suite.
3. THE RevivePay SHALL state in the README that all payment behaviour is simulated, that no real money moves, and that no figure reported by the system represents a real payment result.

### Requirement 27: Non-Functional Constraints and Extensibility

**User Story:** As a maintainer, I want the boundaries and honesty constraints enforced by structure, so that Phase 1 attaches without a rewrite.

#### Acceptance Criteria

1. THE RevivePay SHALL label every reported metric, report, and API analytics payload as produced by synthetic simulated data.
2. WHEN THE RevivePay is run twice from the same seed, the same configuration, and the same Virtual_Clock start time, THE RevivePay SHALL produce identical decisions, identical simulated outcomes, and identical reported totals.
3. THE RevivePay SHALL place all prediction behaviour behind the Recovery_Predictor interface in `app/ml`.
4. THE RevivePay SHALL place all payment provider behaviour behind the Action_Executor interface in `app/integrations`.
5. THE RevivePay SHALL restrict financial action execution to the Action_Executor, and SHALL have the Decision_Engine and the Recovery_Predictor return data structures as their only outputs.
6. THE RevivePay SHALL route every recovery action through the Policy_Engine and SHALL produce an Audit_Event for every executed action and every verified outcome.
7. THE RevivePay SHALL keep the Recovery_Predictor, Diagnosis_Engine, Expected_Value_Calculator, Decision_Engine, Policy_Engine, Action_Executor, Outcome_Verifier, Audit_Service, and Workflow_Orchestrator interfaces stable, so that Phase 1 replaces an implementation behind any one of them without changing its collaborators.
8. THE RevivePay SHALL keep domain logic in `app/services`, `app/workflows`, `app/ml`, and `app/models` importable and executable without an HTTP request or a FastAPI application instance.
9. THE RevivePay SHALL run all functionality with no outbound network access and with no paid API key configured.
10. THE RevivePay SHALL support swapping SQLite for PostgreSQL by changing the `DATABASE_URL` value alone.

### Requirement 28: Phase 0 Completion Criteria

**User Story:** As a project lead, I want Phase 0 judged on demonstrated behaviour rather than on the presence of files, so that the foundation is genuinely working before Phase 1 begins.

#### Acceptance Criteria

1. THE RevivePay SHALL start the FastAPI application successfully and serve `GET /health`.
2. THE RevivePay SHALL initialize the SQLite database through the documented initialization command.
3. THE RevivePay SHALL populate synthetic data through the documented seed command.
4. THE RevivePay SHALL create a failed payment through the API.
5. THE RevivePay SHALL detect revenue risk for that failed payment and create a Recovery_Case.
6. THE RevivePay SHALL produce a diagnosis for that Recovery_Case.
7. THE RevivePay SHALL generate and evaluate candidate recovery actions for that Recovery_Case.
8. THE RevivePay SHALL calculate an Expected_Recovery_Value for every evaluated candidate.
9. THE RevivePay SHALL select one recovery action with a stored explanation.
10. THE RevivePay SHALL produce a Policy_Outcome of APPROVED, BLOCKED, or ESCALATED for the selected action.
11. THE RevivePay SHALL execute an approved action through the Payment_Simulator.
12. THE RevivePay SHALL complete a RETRY_LATER recovery using the Virtual_Clock advance mechanism.
13. THE RevivePay SHALL verify the outcome independently of the execution result.
14. THE RevivePay SHALL store the actual recovered revenue for a verified recovery.
15. THE RevivePay SHALL persist Audit_Event records for the complete run.
16. THE RevivePay SHALL compute analytics from database records.
17. THE RevivePay SHALL run `scripts/demo.py` to completion.
18. THE RevivePay SHALL pass the complete Test_Suite.

## Non-Goals

### Deferred to Phase 1

- Machine-learning-backed recovery prediction. Phase 0 uses deterministic scoring behind the Recovery_Predictor interface; no scikit-learn, numpy, or joblib dependency is introduced.
- The 10,000-row synthetic training dataset and its generator.
- Model training scripts and persisted model artifacts.
- Model evaluation metrics including accuracy, precision, recall, F1, ROC-AUC, and calibration.
- The batch evaluation script, the baseline-versus-RevivePay comparison report, and the improvement percentage.
- A dedicated RecoveryFingerprint component. Phase 0 folds deterministic feature extraction into the Context_Builder.
- Configurable confidence threshold routing that marks decisions for automated handling, human review, or escalation based on prediction confidence. Phase 0 records `confidence` on PredictionResult but does not route on it.
- Per-Action_Type analytics performance breakdown covering attempts, successes, success rate, amount recovered, and average amount recovered.
- LLM-based diagnosis, explanation generation, and any external model API call.
- The AWAITING_APPROVAL state and the human approve and reject endpoints. Phase 0 terminates a high-value transaction in ESCALATED.

### Out of scope entirely for now

- Any frontend, dashboard, or visualization surface. The delivered interface is the HTTP API, the generated `/docs`, and CLI scripts.
- Real Razorpay integration, including test mode. No component may depend on Razorpay presence.
- Production deployment, containerization for production, and hosted infrastructure.
- Authentication, authorization, and multi-tenant access control.
- Online learning, incremental model updates, and automated retraining.
- Microservice decomposition, message queues, and distributed schedulers, including APScheduler, Celery, and Redis.
- Alembic migrations and versioned schema evolution.
- PostgreSQL as the Phase 0 database. The application must remain swappable to PostgreSQL by configuration alone, but Phase 0 runs on SQLite.
