# Implementation Plan

Tasks are ordered so that every task depends only on tasks above it. Each carries explicit acceptance criteria and the requirements it satisfies. Tests are written alongside the component they cover; task 24 adds the end-to-end paths that span components.

- [ ] 1. Scaffold the project skeleton and dependency manifest
  - Create the package tree `app/{api/routes,core,db,models,schemas,services,integrations,ml,workflows}`, `scripts/`, and `tests/`, each Python package with an `__init__.py`
  - Write `requirements.txt` pinning only fastapi, uvicorn[standard], pydantic, pydantic-settings, SQLAlchemy, and pytest with compatible-release bounds
  - Write `.gitignore` covering `.venv`, `__pycache__`, `*.db`, `.env`, and `.revivepay_clock.json`
  - Acceptance: `pip install -r requirements.txt` succeeds in a clean venv; `python -c "import app"` succeeds; no ML or scheduler package appears in the manifest
  - _Requirements: 1.2, 1.10_

- [ ] 2. Implement shared enumerations
  - Create `app/core/enums.py` with `PaymentStatus`, `CaseState` (15 members), `FailureReason` (7 members), `ActionType` (7 members), `ActionStatus`, `PolicyOutcome` (3 members), `RiskLevel`, `WorkflowStage`, `AuditEventType` (13 members), `PaymentMethod`, `SubscriptionStatus`, `FailureCategory`, `Transience`, `ExecutionStatus`
  - Use `str`-valued `Enum` subclasses so database storage and JSON serialization are stable
  - Acceptance: `FailureReason` contains `NETWORK_ERROR` and no `NETWORK_FAILURE`; `AuditEventType` has exactly the 13 named members; `PolicyOutcome` has exactly `APPROVED`, `BLOCKED`, `ESCALATED`; a unit test asserts each member count
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 19.1_

- [ ] 3. Implement configuration and logging
  - Create `app/core/config.py` with a pydantic-settings `Settings` model and a cached `get_settings()`, covering app metadata, `API_PREFIX`, `LOG_LEVEL`, `DATABASE_URL`, `BACKEND_CORS_ORIGINS`, `SIMULATION_SEED`, `VIRTUAL_CLOCK_START`, `VIRTUAL_CLOCK_STATE_PATH`, `RETRY_LATER_DELAY_MINUTES`, `MAX_AUTOMATIC_RETRIES`, `REPEATED_FAILURE_LIMIT`, `HIGH_VALUE_ESCALATION_THRESHOLD`, `ALLOW_HUMAN_ESCALATION`, and the per-`ActionType` intervention cost and friction penalty maps
  - Create `app/core/logging.py` with `configure_logging()` honouring `LOG_LEVEL`
  - Write `.env.example` with every variable and a working default, matching the design's values
  - Acceptance: `get_settings()` loads with no `.env` present using defaults; every key in `.env.example` maps to a `Settings` field and vice versa, asserted by a test
  - _Requirements: 1.3, 1.4, 1.5, 1.6, 23.3_

- [ ] 4. Implement domain errors
  - Create `app/core/errors.py` with `RevivePayError` base plus `RecordNotFound`, `InvalidStateTransition`, `CaseAlreadyTerminal`, and `ActionNotDue`
  - `InvalidStateTransition` must carry the source and target states in its message
  - Acceptance: no module under `app/services`, `app/ml`, `app/workflows`, or `app/integrations` imports `fastapi`; asserted by a test that scans imports
  - _Requirements: 1.8, 16.8, 27.8_

- [ ] 5. Implement the virtual clock
  - Create `app/core/clock.py` with `VirtualClock` exposing `now()`, `advance(minutes, hours)`, and `reset(to)`
  - Persist simulation time as JSON at `VIRTUAL_CLOCK_STATE_PATH`, initializing from `VIRTUAL_CLOCK_START` when the file is absent
  - Use no threads, no scheduler, and no wall-clock reads outside initialization
  - Write `tests/test_clock.py` covering initialization, advance arithmetic, persistence across instances, and reset
  - Acceptance: `advance(minutes=15)` from `2026-01-01T13:01` returns `13:16`; a second `VirtualClock` instance reading the same path observes the advanced time; no `time.sleep` or scheduler import exists
  - _Requirements: 18.1, 18.2, 18.6, 18.10_

- [ ] 6. Implement database engine, session, and the seven models
  - Create `app/db/base.py` with a `DeclarativeBase`, `app/db/session.py` with the engine and session factory built from `DATABASE_URL`, and `app/db/init_db.py` exposing `create_all()`
  - Create `app/models/{customer,payment,payment_attempt,recovery_case,recovery_action,recovery_outcome,audit_event}.py` with the columns, relationships, and indexes from the design, exporting all seven from `app/models/__init__.py`
  - Store all money as integer minor-unit columns and default `currency` to `INR`
  - Write `scripts/init_db.py` invoking `create_all()`
  - Write `tests/test_models.py` covering schema creation, relationship navigation, and index presence
  - Acceptance: `python scripts/init_db.py` creates a SQLite file with exactly seven tables; `Customer → Payment → PaymentAttempt` and `RecoveryCase → RecoveryAction → RecoveryOutcome` navigate in both directions; no Alembic file exists
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 2.12_

- [ ] 7. Implement pydantic request and response schemas
  - Create `app/schemas/common.py` with `ErrorResponse`, `ErrorDetail`, a `Money` representation carrying integer amount plus currency code, and a generic pagination envelope
  - Create `app/schemas/{payment,recovery,analytics,simulate}.py` covering every endpoint in the API contract
  - Acceptance: every response schema serializes money as an integer plus currency string, never a float; schemas import no SQLAlchemy model
  - _Requirements: 24.6, 24.7_

- [ ] 8. Implement the FastAPI application factory and health endpoint
  - Create `app/main.py` with `create_app()` calling `configure_logging()` before route registration, adding CORS from settings, adding request-timing middleware that sets an elapsed-milliseconds response header, and registering exception handlers that emit the `{"error": {"code", "message"}}` envelope for domain errors, validation errors, and unhandled exceptions
  - Create `app/api/router.py` aggregating routers under `API_PREFIX`, `app/api/deps.py` for session and component injection, and `app/api/routes/health.py` serving `GET /health` outside the prefix
  - Create `app/core/container.py` resolving `DiagnosisEngine`, `RecoveryPredictor`, and `ActionExecutor` implementations from settings
  - Acceptance: `uvicorn app.main:app` starts; `GET /health` returns app name, version, environment, and the current virtual clock time; a deliberately raised `RecordNotFound` returns 404 in the error envelope; `/docs` renders
  - _Requirements: 1.1, 1.7, 1.8, 24.1, 24.5, 27.7_

- [ ] 9. Implement the payment service and payment endpoints
  - Create `app/services/payment_service.py` handling payment creation, failure recording with `attempt_count` increment and `PaymentAttempt` insertion, listing with pagination, and retrieval with attempt history
  - Mark generated records with the synthetic-data flag
  - Create `app/api/routes/payments.py` serving `GET /payments`, `GET /payments/{payment_id}`, `POST /payments/simulate`, and `POST /payments/{payment_id}/fail`, delegating all logic to the service
  - Write `tests/test_payments.py` covering creation, failure, pagination, 404, and 422
  - Acceptance: failing a payment sets status `FAILED`, records the `FailureReason`, increments `attempt_count`, and writes a `PaymentAttempt`; an unknown `payment_id` returns 404 in the envelope; an invalid `failure_reason` returns 422 naming the field; route handlers contain no business logic
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 24.2, 24.8, 1.9_

- [ ] 10. Implement the state machine
  - Create `app/services/state_machine.py` with the `TRANSITIONS` table from the design, plus `can()`, `assert_transition()`, and `transition()` stamping `updated_at` from the virtual clock
  - Treat `RECOVERED`, `ESCALATED`, and `STOPPED` as terminal with empty transition sets; permit `FAILED → DIAGNOSING` for re-runs
  - Write `tests/test_state_machine.py` covering the full forward path, every branch, terminal immutability, and rejection cases
  - Acceptance: `DETECTED → EXECUTING` raises `InvalidStateTransition` naming both states; `EXECUTING` is unreachable without passing `DECISION_READY` then `POLICY_CHECK`; no transition out of a terminal state succeeds
  - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 16.8, 16.9, 16.10_

- [ ] 11. Implement the centralized audit service
  - Create `app/services/audit_service.py` with `record()` accepting case id, payment id, stage, event type, message, metadata, and workflow id, and `for_case()` returning events ordered by ascending timestamp
  - Timestamp from the virtual clock; place `workflow_id` inside metadata; expose no update or delete method
  - Write `tests/test_audit.py` covering append-only behaviour, ordering, metadata contents, and the absence of instrument credentials
  - Acceptance: the service is the only module writing `AuditEvent` rows, asserted by a test scanning for `AuditEvent(` construction elsewhere; recorded events carry all eight fields; no method mutates an existing row
  - _Requirements: 19.2, 19.5, 19.6, 19.7, 19.8_

- [ ] 12. Implement the risk detector
  - Create `app/services/risk_detector.py` with `assess()` returning a frozen `RiskAssessment` and `detect_and_open_case()` creating or reusing a `RecoveryCase` in state `DETECTED` with `amount_at_risk`, emitting `REVENUE_RISK_DETECTED`
  - Use one detection path for all failure reasons
  - Write `tests/test_risk_detector.py` covering at-risk detection, the successful-payment path, case reuse, and the audit event
  - Acceptance: a second call for the same failed payment returns the same `case_id` rather than creating a second case; a succeeded payment returns `at_risk=False` with a populated reason; exactly one `REVENUE_RISK_DETECTED` event exists per case
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [ ] 13. Implement the recovery context builder
  - Create `app/services/context_builder.py` with frozen `CustomerSnapshot` and `RecoveryContext` dataclasses and a `build()` performing all reads for a run in one pass
  - Derive `transaction_hour` and `days_since_previous_payment` from the virtual clock and stored timestamps; expose `features()` as the single projection for the predictor; populate neutral defaults with `history_available=False` when the customer is missing
  - Write `tests/test_context_builder.py` covering field population, determinism, the missing-customer path, and history sets
  - Acceptance: two `build()` calls over unchanged rows produce equal `features()` dicts; no wall-clock call occurs; `attempted_action_types`, `succeeded_action_types`, and `failed_action_types` reflect prior actions
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.7_

- [ ] 14. Implement the diagnosis engine
  - Create `app/services/diagnosis_engine.py` with a `DiagnosisEngine` Protocol, a frozen `Diagnosis` dataclass, and `RuleBasedDiagnosisEngine` implementing the classification table from the design
  - Resolve absent or unrecognized reasons to `UNKNOWN` with `requires_escalation=True`; derive everything from the context
  - Persist the diagnosis on the case and emit `DIAGNOSIS_COMPLETED`
  - Write `tests/test_diagnosis.py` covering all seven reasons, the unknown path, and determinism
  - Acceptance: each of the seven failure reasons maps to the category and transience in the design table; repeated diagnosis of unchanged data is equal; the engine satisfies the Protocol
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [ ] 15. Implement the candidate action generator
  - Create `app/services/candidate_generator.py` mapping each `FailureReason` to its candidate list per the design table, returning candidates only
  - Filter out action types that previously failed for the payment while at least one alternative remains
  - Write `tests/test_candidates.py` asserting the candidate set for all seven reasons plus the filtering behaviour
  - Acceptance: the seven candidate sets match the design exactly; no selection is returned; this is the only module containing per-`FailureReason` branching, asserted by a test scanning other service modules
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10_

- [ ] 16. Implement the deterministic recovery predictor
  - Create `app/ml/predictor.py` with the `RecoveryPredictor` Protocol and frozen `PredictionResult` and `ScoringFactor` dataclasses
  - Create `app/ml/scoring_tables.py` holding the base-rate matrix, decay, and factor constants, documented in-file as synthetic demonstration values
  - Create `app/ml/deterministic_scorer.py` implementing the multiplicative score with clamping to `[0.02, 0.97]`, the data-completeness confidence, `model_version = "deterministic-scorer-v1"`, `features_used`, and factors ordered by absolute influence
  - Write `tests/test_predictor.py` covering purity, bounds, the required orderings, attempt decay, and customer-rate monotonicity
  - Acceptance: `RETRY_LATER` scores above `RETRY_NOW` for `BANK_TIMEOUT`; `CHANGE_PAYMENT_METHOD` scores above `RETRY_NOW` for `EXPIRED_CARD`; probability falls as `attempt_count` rises and rises as customer success rate rises; repeated calls are identical; no ML library is imported
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8, 9.9, 27.3_

- [ ] 17. Implement the expected recovery value calculator
  - Create `app/services/expected_value.py` with a frozen `ExpectedValueBreakdown` and a `calculate()` reading per-action intervention cost and friction penalty from settings with the documented defaults
  - Compute gross as rounded `probability × amount` and ERV as gross minus cost minus penalty, all in minor units
  - Write `tests/test_expected_value.py` including the worked example and the monotonicity property
  - Acceptance: amount 1,000,000 with `RETRY_LATER` at probability 0.72, cost 2,000, penalty 10,000 returns gross 720,000 and ERV exactly 708,000; the formula appears in no other module, asserted by a repository scan test
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

- [ ] 18. Implement the decision engine and structured explanation
  - Create `app/services/decision_engine.py` with frozen `ScoredCandidate`, `DecisionExplanation`, and `RecoveryDecision` dataclasses
  - Score every candidate through the predictor and calculator, assign risk level, rank by descending ERV with the documented tie-break chain, and select the top candidate
  - Build the explanation with `selected_action`, templated `reason`, probability, ERV, confidence, and the alternatives array; emit `RECOVERY_OPTIONS_EVALUATED` then `RECOVERY_DECISION_SELECTED`
  - Handle the empty-candidate case by selecting `ESCALATE_HUMAN` or `STOP` per the diagnosis
  - Write `tests/test_decision_engine.py` covering ranking, tie-breaks, explanation contents, the empty case, and the no-side-effects guarantee
  - Acceptance: the highest-ERV candidate is selected; equal ERVs resolve deterministically by probability then cost then enum order; `decide()` performs no payment mutation and no execution; alternatives contain every non-selected candidate with action, probability, and ERV
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 12.1, 12.2, 12.3, 12.5, 27.5_

- [ ] 19. Implement the policy rule set and policy engine
  - Create `app/services/policy_rules.py` with each rule as a small object exposing `rule_id` and `evaluate()`, ordered as `invalid_payment_state`, `unsupported_action`, `retry_limit_reached`, `repeated_failure_limit`, `unknown_failure`, `high_value_transaction`, then default approval
  - Create `app/services/policy_engine.py` returning the first non-`None` result as a frozen `PolicyResult`, persisting outcome, rule id, and reason on the `RecoveryAction`, and emitting `POLICY_APPROVED`, `POLICY_BLOCKED`, or `POLICY_ESCALATED`
  - Write `tests/test_policy_engine.py` covering every rule in isolation, ordering precedence, and the totality property
  - Acceptance: `attempt_count` at `MAX_AUTOMATIC_RETRIES` with a retry action returns `BLOCKED` with `rule_id="retry_limit_reached"`; an amount above the high-value threshold returns `ESCALATED`; `UNKNOWN` reason returns `ESCALATED` when escalation is allowed and `BLOCKED` otherwise; an unsupported action returns `BLOCKED`; every result carries a non-empty `rule_id`; no rule logic lives in a route handler
  - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 13.8, 13.10, 13.11, 13.12_

- [ ] 20. Implement the action executor interface and payment simulator
  - Create `app/integrations/action_executor.py` with the `ActionExecutor` Protocol, frozen `ExecutionResult`, and `supports()`
  - Create `app/integrations/payment_simulator.py` implementing the scripted outcome table for the four mandated pairs and the SHA-256 seeded draw for all other pairs, reading per-scenario probabilities from settings
  - Implement the seven simulated behaviours; on simulated success update the payment status and write a successful `PaymentAttempt`; emit `ACTION_EXECUTED` or `ACTION_FAILED`
  - Write `tests/test_simulator.py` covering the scripted pairs, draw reproducibility, each behaviour, and `supports()`
  - Acceptance: `BANK_TIMEOUT` with `RETRY_LATER` always succeeds; `EXPIRED_CARD` with `RETRY_NOW` always fails and with `CHANGE_PAYMENT_METHOD` always succeeds; `INSUFFICIENT_FUNDS` retries always fail; identical seed, payment id, action, and attempt number always produce the same outcome; no network call occurs
  - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7, 14.8, 14.9, 14.10, 14.11, 14.12, 27.4_

- [ ] 21. Implement the outcome verifier
  - Create `app/services/outcome_verifier.py` re-reading the persisted payment and producing a `RecoveryOutcome` row, deciding `recovered` from payment state alone
  - Set `recovered_amount` to the payment amount on a verified failed-to-successful transition and to zero otherwise; emit `OUTCOME_VERIFIED` plus `REVENUE_RECOVERED` when recovered
  - Hold no reference to the executor
  - Write `tests/test_outcome_verifier.py` covering the recovered path, the unrecovered path, and the independence property
  - Acceptance: an execution result reporting success while the persisted payment status is not successful yields `recovered=False` and `recovered_amount=0`; the module imports nothing from `app/integrations`
  - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6_

- [ ] 22. Implement the recovery workflow orchestrator
  - Create `app/workflows/recovery_workflow.py` with a frozen `WorkflowRun` and a `run(case_id)` executing the eleven-stage order from the design, exactly one action per run
  - Generate a `workflow_id` per run and stamp it into every audit event; emit one log line per stage; return early with `waiting_until` when a scheduled action is not yet due
  - Set `scheduled_at` and state `SCHEDULED` for approved `RETRY_LATER` with `ACTION_SCHEDULED`, execute nothing that run
  - Route `BLOCKED` to `BLOCKED` then `STOPPED` with `WORKFLOW_STOPPED`, route `ESCALATED` to `ESCALATED` without execution, and route verified results to `RECOVERED` or the re-runnable `FAILED`
  - Wrap stage errors so the case stays persisted and recoverable
  - Acceptance: one run performs at most one execution; a run against a terminal case raises `CaseAlreadyTerminal`; a `RETRY_LATER` run executes no payment attempt; every audit event from a run shares one `workflow_id`; the returned `WorkflowRun` carries all fields in the design
  - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7, 17.8, 17.9, 18.3, 18.5, 18.8, 23.1, 23.2, 23.4, 19.3, 19.4, 11.7, 13.9, 27.6_

- [ ] 23. Implement recovery, analytics, and simulation endpoints
  - Create `app/api/routes/recovery.py` serving `GET /recovery/cases`, `GET /recovery/cases/{case_id}` including the latest decision explanation and policy result, `POST /recovery/cases/{case_id}/run`, and `GET /recovery/cases/{case_id}/audit`
  - Create `app/services/analytics_service.py` computing revenue and recovery aggregates from persisted rows only, guarding the zero-at-risk divide, and marking payloads as synthetic; expose via `app/api/routes/analytics.py`
  - Create `app/api/routes/simulate.py` serving `POST /simulate/advance-clock` and `scripts/advance_clock.py` as the CLI equivalent
  - Write `tests/test_analytics.py` and endpoint tests covering 200, 404, and 409 paths
  - Acceptance: running a terminal case returns 409 with the current state; recovered revenue equals the sum of verified outcomes; recovery rate returns 0 when nothing is at risk; every analytics payload carries the synthetic-data marker; advancing the clock by 15 minutes via API and via CLI both return the new time
  - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 24.3, 24.4, 24.9, 18.6, 18.7, 19.7, 12.4, 15.7_

- [ ] 24. Implement the scenario generator and seed command
  - Create `app/services/scenario_generator.py` and `scripts/seed.py` producing seeded synthetic customers with full history plus payments and attempts across all six scenarios, every record flagged synthetic
  - Include the four required deterministic scenarios: `BANK_TIMEOUT` recovering via `RETRY_LATER`, `INSUFFICIENT_FUNDS` exhausting the retry limit to `STOPPED`, a high-value payment escalating to `ESCALATED`, and `EXPIRED_CARD` recovering via `CHANGE_PAYMENT_METHOD`
  - Acceptance: `python scripts/seed.py` twice against a fresh database produces identical rows for the same seed; all six scenarios are present; the high-value scenario amount exceeds `HIGH_VALUE_ESCALATION_THRESHOLD`; every seeded row carries the synthetic flag
  - _Requirements: 21.1, 21.2, 21.3, 21.4, 21.5, 21.6, 21.7, 21.8, 21.9, 27.2_

- [ ] 25. Write the end-to-end workflow tests
  - Create `tests/conftest.py` providing a per-session temporary SQLite database, a fixed seed, a virtual clock backed by a `tmp_path` state file, and a FastAPI `TestClient`
  - Create `tests/test_workflow_e2e.py` with the successful-recovery path including the 13:00 to 13:16 clock timeline, the stopped path reaching the retry limit, the escalation path for a high-value payment, and the alternative-recovery path for `EXPIRED_CARD`
  - Acceptance: the success test asserts `recovered=True`, the full recovered amount, state `RECOVERED`, and the presence of all nine expected audit event types; the stopped test asserts state `STOPPED`, a `WORKFLOW_STOPPED` event, and zero recovered revenue; the escalation test asserts state `ESCALATED`, a `POLICY_ESCALATED` event, and no `ACTION_EXECUTED` event; the alternative test asserts recovery via `CHANGE_PAYMENT_METHOD` after `RETRY_NOW` fails; the whole suite passes with no network access
  - _Requirements: 25.1, 25.2, 25.3, 25.4, 25.5, 25.6, 25.7, 25.8, 25.9, 25.10, 25.11, 25.12, 25.13, 25.14, 18.9_

- [ ] 26. Implement the CLI demo
  - Create `scripts/demo.py` running against a seeded database through the same workflow, policy, executor, and verifier used by the API
  - Print the payment, failure, diagnosis, candidates, per-candidate ERV breakdown, selected action with explanation, policy decision, clock advancement where the action is `RETRY_LATER`, execution, verification, actual recovered revenue, and the audit trail
  - Demonstrate the successful, stopped, and escalation scenarios, and print the synthetic-simulation disclaimer
  - Acceptance: `python scripts/demo.py` completes with exit code 0 after seeding, printing all three scenarios; the `RETRY_LATER` scenario shows the scheduled time, the advance, and the subsequent execution; the disclaimer appears in the output
  - _Requirements: 22.1, 22.2, 22.3, 22.4, 22.5, 22.6_

- [ ] 27. Write the README and verify the completion criteria
  - Write `README.md` covering the problem statement, concept, architecture, tech stack, folder structure, setup, environment variables, database, seeding, API documentation, CLI demo, testing, the synthetic-data disclaimer, Phase 0 limitations, and the Phase 1 direction
  - Document each PowerShell command from the design's setup section
  - Walk the eighteen Phase 0 completion criteria end to end and record the result of each
  - Acceptance: a clean clone followed only by the documented commands reaches a passing `pytest` run and a successful `scripts/demo.py`; the README states plainly that all behaviour is simulated and no figure represents a real payment; all eighteen completion criteria are demonstrated, not merely asserted
  - _Requirements: 26.1, 26.2, 26.3, 28.1, 28.2, 28.3, 28.4, 28.5, 28.6, 28.7, 28.8, 28.9, 28.10, 28.11, 28.12, 28.13, 28.14, 28.15, 28.16, 28.17, 28.18_
