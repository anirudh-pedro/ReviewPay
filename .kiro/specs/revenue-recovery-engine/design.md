# Design Document

## Overview

RevivePay Phase 0 is a modular monolith that takes a failed synthetic payment through a complete, auditable recovery pipeline and reports the revenue it actually recovered. It runs entirely offline on SQLite with no machine learning libraries, yet every component sits behind the interface that Phase 1 will use to substitute ML and LLM implementations.

The design has one organizing principle: **the pipeline is a sequence of pure-ish transformations over a single read-only context, with exactly one component permitted to change payment state.** Detection, diagnosis, candidate generation, prediction, valuation, and ranking all read a `RecoveryContext` and return data structures. Only `PaymentSimulatorExecutor`, behind the `ActionExecutor` interface, mutates payment state, and it is reached only after `PolicyEngine` returns `APPROVED`. `OutcomeVerifier` then re-reads persisted state to decide whether revenue was recovered, so a lying or buggy executor cannot inflate the recovered total.

Two properties make the system demo-safe. First, **determinism**: the probability scorer is a pure function, the simulator derives outcomes from a hash of `(seed, payment_id, action_type, attempt_number)`, and time advances only through explicit `advance-clock` calls. The same seed produces the same demo every time, on any machine. Second, **auditability**: thirteen event types are written through one centralized `AuditService`, each stamped with the `workflow_id`, so the full decision trail for any case is reconstructable from the database alone.

_Requirements traceability appears inline as `(R<n>.<criterion>)` and is summarized in the Requirements Coverage section._

## Architecture

### Architectural decision and rationale

**Modular monolith over microservices.** The thirteen conceptual components need to evolve independently, but they do not need to *deploy* independently. A single FastAPI process with enforced module boundaries gives the same substitutability at a fraction of the operational cost, which matters for a few-day hackathon build. Boundaries are enforced by dependency direction rather than by network hops: `app/api` may import from `app/workflows` and `app/services`; nothing may import from `app/api`.

**Layered with a single orchestration seam.** `RevenueRecoveryWorkflow` is the only component that knows the pipeline order. Every other component knows only its own inputs and outputs. Adding a stage means editing one file (R17.3).

**Context-first data access.** `RecoveryContextBuilder` performs all database reads for a run, once, and hands downstream components a frozen structure. This is what lets the decision path be tested without a database session and keeps domain logic runnable without FastAPI (R6.5, R6.6, R27.8).

**Interfaces via Protocol, implementations via constructor injection.** Each swappable component is declared as a `typing.Protocol` in its module and resolved through a small factory in `app/core/container.py` reading `get_settings()`. Phase 1 registers a different implementation; no collaborator changes (R27.7).

### Component layering

```
                    ┌──────────────────────────────────┐
                    │  app/api  (thin routes)          │
                    │  payments · recovery · analytics │
                    │  simulate · health               │
                    └────────────────┬─────────────────┘
                                     │  pydantic schemas (app/schemas)
                                     ▼
                    ┌──────────────────────────────────┐
                    │  app/workflows                   │
                    │  RevenueRecoveryWorkflow         │
                    │  (orchestration boundary)        │
                    └────────────────┬─────────────────┘
              ┌──────────────────────┼──────────────────────┐
              ▼                      ▼                      ▼
     ┌────────────────┐   ┌──────────────────┐   ┌──────────────────┐
     │ RiskDetector   │   │ DiagnosisEngine  │   │ ContextBuilder   │
     └────────────────┘   └──────────────────┘   └──────────────────┘
              └──────────────────────┼──────────────────────┘
                                     ▼
                    ┌──────────────────────────────────┐
                    │ CandidateGenerator               │
                    └────────────────┬─────────────────┘
                                     ▼
                    ┌──────────────────────────────────┐
                    │ RecoveryPredictor  (app/ml)      │
                    │ DeterministicRecoveryScorer      │
                    └────────────────┬─────────────────┘
                                     ▼
                    ┌──────────────────────────────────┐
                    │ ExpectedRecoveryCalculator       │
                    │ RecoveryDecisionEngine (ranking) │
                    └────────────────┬─────────────────┘
                                     ▼
                    ┌──────────────────────────────────┐
                    │ PolicyEngine  (mandatory gate)   │
                    │ APPROVED · BLOCKED · ESCALATED   │
                    └────────────────┬─────────────────┘
                                     ▼
                    ┌──────────────────────────────────┐
                    │ ActionExecutor  (app/integrations)│
                    │ PaymentSimulatorExecutor         │
                    └────────────────┬─────────────────┘
                                     ▼
                    ┌──────────────────────────────────┐
                    │ OutcomeVerifier  (re-reads state)│
                    └────────────────┬─────────────────┘
                                     ▼
                    ┌──────────────────────────────────┐
                    │ AuditService · AnalyticsService  │
                    └──────────────────────────────────┘

  Cross-cutting: VirtualClock · StateMachine · Settings · Logging
```

### Folder structure

```
RevivePay/
├── app/
│   ├── main.py                      # create_app() factory (R1.1)
│   ├── api/
│   │   ├── router.py                # aggregates all routers under API_PREFIX
│   │   ├── deps.py                  # DB session + component dependencies
│   │   └── routes/
│   │       ├── health.py            # GET /health
│   │       ├── payments.py          # payments endpoints
│   │       ├── recovery.py          # recovery case endpoints
│   │       ├── simulate.py          # POST /simulate/advance-clock
│   │       └── analytics.py         # analytics endpoints
│   ├── core/
│   │   ├── config.py                # Settings + get_settings() (R1.3, R1.4)
│   │   ├── logging.py               # configure_logging() (R1.6)
│   │   ├── enums.py                 # all enumerations (R3.1)
│   │   ├── clock.py                 # VirtualClock (R18)
│   │   ├── errors.py                # domain errors + HTTP mapping (R1.8)
│   │   └── container.py             # component factory / injection
│   ├── db/
│   │   ├── base.py                  # DeclarativeBase
│   │   ├── session.py               # engine, SessionLocal, get_session
│   │   └── init_db.py               # create_all() (R2.11)
│   ├── models/
│   │   ├── customer.py  payment.py  payment_attempt.py
│   │   ├── recovery_case.py  recovery_action.py
│   │   ├── recovery_outcome.py  audit_event.py
│   │   └── __init__.py              # exports all 7 models (R2.1)
│   ├── schemas/                     # pydantic v2 request/response (R24.6)
│   │   ├── payment.py  recovery.py  analytics.py
│   │   ├── simulate.py  common.py   # ErrorResponse, Money, Pagination
│   ├── services/
│   │   ├── risk_detector.py
│   │   ├── context_builder.py
│   │   ├── diagnosis_engine.py
│   │   ├── expected_value.py        # sole ERV implementation (R10.4)
│   │   ├── candidate_generator.py
│   │   ├── decision_engine.py
│   │   ├── policy_engine.py
│   │   ├── policy_rules.py          # configurable rule set (R13.11)
│   │   ├── outcome_verifier.py
│   │   ├── audit_service.py
│   │   ├── analytics_service.py
│   │   ├── payment_service.py
│   │   └── state_machine.py
│   ├── integrations/
│   │   ├── action_executor.py       # ActionExecutor Protocol (R14.1)
│   │   └── payment_simulator.py     # PaymentSimulatorExecutor
│   ├── ml/
│   │   ├── predictor.py             # RecoveryPredictor Protocol (R9.1)
│   │   ├── deterministic_scorer.py  # Phase 0 implementation
│   │   └── scoring_tables.py        # documented synthetic base rates
│   └── workflows/
│       └── recovery_workflow.py     # RevenueRecoveryWorkflow (R17)
├── scripts/
│   ├── init_db.py  seed.py  demo.py  advance_clock.py
├── tests/
│   ├── conftest.py
│   ├── test_models.py  test_payments.py  test_risk_detector.py
│   ├── test_diagnosis.py  test_candidates.py  test_predictor.py
│   ├── test_expected_value.py  test_decision_engine.py
│   ├── test_policy_engine.py  test_state_machine.py
│   ├── test_clock.py  test_simulator.py  test_outcome_verifier.py
│   ├── test_audit.py  test_analytics.py
│   └── test_workflow_e2e.py         # 3 end-to-end paths
├── .env.example   requirements.txt   README.md   .gitignore
```

## Components and Interfaces

Every signature below is the stable Phase 0 contract (R27.7). Types marked `frozen` are immutable dataclasses.

### VirtualClock (R18)

```python
class VirtualClock:
    def now(self) -> datetime: ...
    def advance(self, *, minutes: int = 0, hours: int = 0) -> datetime: ...
    def reset(self, to: datetime | None = None) -> datetime: ...
```

Simulation time is persisted to a JSON file at `VIRTUAL_CLOCK_STATE_PATH` so it survives process restarts and is shared between the API process and CLI scripts. The clock starts at `VIRTUAL_CLOCK_START` (default `2026-01-01T13:00:00`) — chosen so the canonical 13:00 → 13:15 demo timeline in R18.9 works out of the box. Advancing is the only way time moves (R18.10); no scheduler, no threads (R18.2).

_Design note:_ a JSON file rather than a database table keeps the domain model at exactly seven entities (R2.1). Single-process assumption is acceptable for Phase 0 and documented as a limitation. Tests point the path at a `tmp_path` fixture.

### StateMachine (R16)

```python
TRANSITIONS: dict[CaseState, frozenset[CaseState]] = {
    DETECTED:      {DIAGNOSING},
    DIAGNOSING:    {DIAGNOSED},
    DIAGNOSED:     {EVALUATING},
    EVALUATING:    {DECISION_READY},
    DECISION_READY:{POLICY_CHECK},
    POLICY_CHECK:  {APPROVED, BLOCKED, ESCALATED},
    APPROVED:      {EXECUTING, SCHEDULED},
    SCHEDULED:     {EXECUTING},
    EXECUTING:     {VERIFYING},
    VERIFYING:     {RECOVERED, FAILED},
    BLOCKED:       {STOPPED},
    FAILED:        {DIAGNOSING},        # re-runnable (R16.7)
    RECOVERED: frozenset(), ESCALATED: frozenset(), STOPPED: frozenset(),
}

class StateMachine:
    def can(self, src: CaseState, dst: CaseState) -> bool: ...
    def assert_transition(self, src: CaseState, dst: CaseState) -> None: ...
    def transition(self, case: RecoveryCase, dst: CaseState) -> RecoveryCase: ...
```

`assert_transition` raises `InvalidStateTransition(src, dst)` for any pair absent from the table (R16.8). Because `DETECTED` maps only to `{DIAGNOSING}`, a jump straight to `EXECUTING` is structurally impossible (R16.9). Terminal states map to the empty set (R16.6). `transition` stamps `updated_at` from the `VirtualClock` (R16.10).

### RiskDetector (R5)

```python
@dataclass(frozen=True)
class RiskAssessment:
    at_risk: bool
    reason: str
    amount_at_risk: int          # minor units
    failure_reason: FailureReason | None

class RiskDetector:
    def assess(self, payment: Payment) -> RiskAssessment: ...
    def detect_and_open_case(self, payment: Payment) -> RecoveryCase: ...
```

One detection path for every `FailureReason` (R5.1). `detect_and_open_case` reuses an existing non-terminal case for the payment rather than opening a second (R5.3) and writes `REVENUE_RISK_DETECTED` (R5.4). A successful payment returns `at_risk=False` with a populated `reason` (R5.5).

### RecoveryContextBuilder (R6)

```python
@dataclass(frozen=True)
class CustomerSnapshot:
    customer_id: str; total_payments: int; successful_payments: int
    failed_payments: int; success_rate: float; average_transaction_value: int
    subscription_status: SubscriptionStatus; history_available: bool

@dataclass(frozen=True)
class RecoveryContext:
    payment_id: str; case_id: str; amount: int; currency: str
    payment_method: PaymentMethod; payment_status: PaymentStatus
    failure_reason: FailureReason; attempt_count: int
    customer: CustomerSnapshot
    transaction_hour: int; is_returning_customer: bool
    days_since_previous_payment: int | None
    previous_recovery_attempt_count: int
    attempted_action_types: frozenset[ActionType]
    succeeded_action_types: frozenset[ActionType]
    failed_action_types: frozenset[ActionType]
    diagnosis: Diagnosis | None
    def features(self) -> dict[str, float | int | str | bool]: ...

class RecoveryContextBuilder:
    def build(self, case: RecoveryCase) -> RecoveryContext: ...
```

All reads for a run happen here, once (R6.1). `transaction_hour` and `days_since_previous_payment` derive from `VirtualClock.now()` and stored timestamps, never wall clock (R6.3), which is what makes repeated builds identical (R6.4). A missing customer yields documented neutral defaults — `success_rate=0.5`, zero counts — with `history_available=False` (R6.7).

`features()` is the single projection consumed by the predictor. Phase 1's dedicated `RecoveryFingerprint` component replaces this method without touching the decision engine.

### DiagnosisEngine (R7)

```python
@dataclass(frozen=True)
class Diagnosis:
    failure_reason: FailureReason
    category: FailureCategory      # TRANSIENT | CUSTOMER_ACTION | TIME_DEPENDENT | ENGAGEMENT | UNKNOWN
    transience: Transience         # TRANSIENT | PERSISTENT | UNKNOWN
    requires_escalation: bool
    explanation: str

class DiagnosisEngine(Protocol):
    def diagnose(self, context: RecoveryContext) -> Diagnosis: ...

class RuleBasedDiagnosisEngine(DiagnosisEngine): ...
```

Classification table (R7.2):

| Failure reason | Category | Transience | Escalate |
|---|---|---|---|
| `BANK_TIMEOUT` | `TRANSIENT` | `TRANSIENT` | no |
| `NETWORK_ERROR` | `TRANSIENT` | `TRANSIENT` | no |
| `EXPIRED_CARD` | `CUSTOMER_ACTION` | `PERSISTENT` | no |
| `INSUFFICIENT_FUNDS` | `TIME_DEPENDENT` | `TRANSIENT` | no |
| `CHECKOUT_ABANDONMENT` | `ENGAGEMENT` | `PERSISTENT` | no |
| `SUBSCRIPTION_FAILURE` | `ENGAGEMENT` | `TRANSIENT` | no |
| `UNKNOWN` / absent | `UNKNOWN` | `UNKNOWN` | **yes** (R7.3) |

Derived from the context alone, so repeated diagnosis of unchanged data is identical (R7.4). Declared as a `Protocol` so a Phase 1 LLM diagnoser drops in behind it (R7.6).

### CandidateGenerator (R8)

```python
class RecoveryActionCandidateGenerator:
    def generate(self, context: RecoveryContext, diagnosis: Diagnosis) -> list[ActionType]: ...
```

The **only** component containing per-`FailureReason` branching (R8.9):

| Failure reason | Candidates |
|---|---|
| `BANK_TIMEOUT` | `RETRY_NOW`, `RETRY_LATER`, `SEND_PAYMENT_LINK` |
| `EXPIRED_CARD` | `CHANGE_PAYMENT_METHOD`, `SEND_PAYMENT_LINK`, `ESCALATE_HUMAN` |
| `INSUFFICIENT_FUNDS` | `RETRY_LATER`, `SEND_PAYMENT_LINK`, `SEND_REMINDER` |
| `CHECKOUT_ABANDONMENT` | `SEND_REMINDER`, `SEND_PAYMENT_LINK` |
| `NETWORK_ERROR` | `RETRY_NOW`, `RETRY_LATER` |
| `SUBSCRIPTION_FAILURE` | `RETRY_LATER`, `SEND_REMINDER`, `SEND_PAYMENT_LINK` |
| `UNKNOWN` | `ESCALATE_HUMAN`, `STOP` |

Returns candidates only, never a selection (R8.1). Previously-failed action types are filtered out while at least one alternative survives (R8.10) — this is what makes the `EXPIRED_CARD` path move from `RETRY_NOW` to `CHANGE_PAYMENT_METHOD` on re-run.

### RecoveryPredictor (R9)

```python
@dataclass(frozen=True)
class PredictionResult:
    probability: float            # [0.0, 1.0]
    confidence: float             # [0.0, 1.0]
    model_version: str
    features_used: tuple[str, ...]
    explanation: tuple[ScoringFactor, ...]   # ordered by |influence|

class RecoveryPredictor(Protocol):
    def predict(self, context: RecoveryContext, action: ActionType) -> PredictionResult: ...

class DeterministicRecoveryScorer(RecoveryPredictor):
    MODEL_VERSION = "deterministic-scorer-v1"
```

Scoring is a pure function — no ML library, no network (R9.3), identical output for identical input (R9.4):

```
probability = clamp(
    BASE_RATE[failure_reason][action]
      * attempt_decay          # ATTEMPT_DECAY ** attempt_count, default 0.75
      * customer_factor        # 0.70 + 0.60 * customer_success_rate  → [0.70, 1.30]
      * subscription_factor    # 1.05 if subscribed else 1.00
      * history_factor,        # 1.15 if action previously succeeded; 0.60 if previously failed
    0.02, 0.97)
```

`BASE_RATE` lives in `scoring_tables.py`, explicitly labelled synthetic demonstration values:

| Failure reason | `RETRY_NOW` | `RETRY_LATER` | `PAYMENT_LINK` | `CHANGE_METHOD` | `REMINDER` | `ESCALATE` |
|---|---|---|---|---|---|---|
| `BANK_TIMEOUT` | 0.35 | **0.78** | 0.55 | — | — | — |
| `NETWORK_ERROR` | 0.55 | 0.70 | — | — | — | — |
| `INSUFFICIENT_FUNDS` | — | 0.45 | 0.40 | — | 0.35 | — |
| `EXPIRED_CARD` | 0.05 | — | 0.58 | **0.72** | — | 0.30 |
| `CHECKOUT_ABANDONMENT` | — | — | 0.42 | — | 0.30 | — |
| `SUBSCRIPTION_FAILURE` | — | 0.60 | 0.48 | — | 0.35 | — |
| `UNKNOWN` | — | — | — | — | — | 0.25 |

The bolded cells satisfy R9.7 directly: `RETRY_LATER` (0.78) outranks `RETRY_NOW` (0.35) for `BANK_TIMEOUT`, and `CHANGE_PAYMENT_METHOD` (0.72) outranks `RETRY_NOW` (0.05) for `EXPIRED_CARD`. `attempt_decay` falls with attempt count and `customer_factor` rises with success rate (R9.8).

Confidence is likewise deterministic, a data-completeness score:

```
confidence = clamp(0.50
    + 0.20 * customer.history_available
    + 0.15 * (attempt_count <= 2)
    + 0.15 * (failure_reason is not UNKNOWN), 0.0, 1.0)
```

Phase 0 records confidence but does not route on it; threshold routing is a Phase 1 non-goal.

### ExpectedRecoveryCalculator (R10)

```python
@dataclass(frozen=True)
class ExpectedValueBreakdown:
    recovery_probability: float
    payment_amount: int
    gross_expected_recovery: int
    intervention_cost: int
    customer_friction_penalty: int
    expected_recovery_value: int

class ExpectedRecoveryCalculator:
    def calculate(self, *, amount: int, probability: float,
                  action: ActionType) -> ExpectedValueBreakdown: ...
```

The **only** place the formula exists (R10.4). `gross = round(probability * amount)`; `erv = gross - intervention_cost - friction_penalty`, all in minor units (R10.1, R10.2).

Configured defaults per action, in paise:

| Action | Intervention cost | Friction penalty |
|---|---|---|
| `RETRY_NOW` | 500 | 2,000 |
| `RETRY_LATER` | **2,000** | **10,000** |
| `SEND_PAYMENT_LINK` | 3,000 | 15,000 |
| `CHANGE_PAYMENT_METHOD` | 3,000 | 20,000 |
| `SEND_REMINDER` | 1,000 | 8,000 |
| `ESCALATE_HUMAN` | 50,000 | 0 |
| `STOP` | 0 | 0 |

The `RETRY_LATER` row reproduces the worked example exactly (R10.3): amount 1,000,000 × 0.72 = gross 720,000, minus 2,000 minus 10,000 = **708,000** minor units, i.e. ₹10,000 at 0.72 with ₹20 cost and ₹100 friction gives ₹7,080.

### RecoveryDecisionEngine (R11, R12)

```python
@dataclass(frozen=True)
class ScoredCandidate:
    action: ActionType; prediction: PredictionResult
    breakdown: ExpectedValueBreakdown; risk_level: RiskLevel

@dataclass(frozen=True)
class RecoveryDecision:
    selected_action: ActionType
    probability: float; confidence: float
    expected_recovery_value: int
    breakdown: ExpectedValueBreakdown
    risk_level: RiskLevel
    ranked: tuple[ScoredCandidate, ...]
    explanation: DecisionExplanation

class RecoveryDecisionEngine:
    def decide(self, context, diagnosis, candidates) -> RecoveryDecision: ...
```

Scores every candidate, ranks by descending ERV, and selects the top one (R11.1–R11.3). **Tie-break rule:** equal ERV resolves by higher probability, then by lower intervention cost, then by the declaration order of the `ActionType` enum — fully deterministic (R11.2). Risk level derives from amount and action class: `ESCALATE_HUMAN`/`STOP` are `LOW`; retries below the high-value threshold are `LOW`; anything above it is `HIGH`; the rest `MEDIUM`.

Returns a data structure only — no execution, no payment mutation (R11.4, R27.5). An empty candidate list yields `ESCALATE_HUMAN` when the diagnosis permits human handling, else `STOP` (R11.5).

`DecisionExplanation` carries `selected_action`, `reason`, `probability`, `expected_recovery_value`, `confidence`, and `alternatives[]` of `{action, probability, expected_recovery_value}` (R12.1, R12.2). The reason sentence is templated: `"RETRY_LATER was selected because it has the highest expected recovery value (708000 paise) among the evaluated candidate actions."` (R12.3). The same structure is stored on `RecoveryAction.decision_explanation` and mirrored into audit metadata (R12.5).

### PolicyEngine (R13)

```python
@dataclass(frozen=True)
class PolicyResult:
    outcome: PolicyOutcome        # APPROVED | BLOCKED | ESCALATED
    rule_id: str
    reason: str

class PolicyRule(Protocol):
    rule_id: str
    def evaluate(self, ctx: RecoveryContext, decision: RecoveryDecision,
                 cfg: Settings) -> PolicyResult | None: ...

class PolicyEngine:
    def evaluate(self, context, decision) -> PolicyResult: ...
```

Rules live in `policy_rules.py` as an ordered list, never in route handlers (R13.11). Evaluation stops at the first rule returning non-`None` (R13.12):

| # | `rule_id` | Condition | Outcome |
|---|---|---|---|
| 1 | `invalid_payment_state` | payment status invalid for the action | `BLOCKED` (R13.6) |
| 2 | `unsupported_action` | executor does not support the action | `BLOCKED` (R13.7) |
| 3 | `retry_limit_reached` | `attempt_count >= MAX_AUTOMATIC_RETRIES` and action is a retry | `BLOCKED` (R13.3) |
| 4 | `recovery_budget_exhausted` | `attempt_count >= MAX_AUTOMATIC_RETRIES` and action is any non-terminal action | `BLOCKED` (R13.3a–3e) |
| 5 | `repeated_failure_limit` | unsuccessful outcomes `>= REPEATED_FAILURE_LIMIT` | `BLOCKED` (R13.8) |
| 6 | `unknown_failure` | `failure_reason is UNKNOWN` | `ESCALATED`, or `BLOCKED` if human handling disabled (R13.5) |
| 7 | `high_value_transaction` | `amount > HIGH_VALUE_ESCALATION_THRESHOLD` | `ESCALATED` (R13.4) |
| — | `default_approve` | no rule fired | `APPROVED` |

Blocking rules precede escalation rules deliberately: a case that has exhausted its retries should stop rather than page a human. Every result is persisted on the `RecoveryAction` and audited as `POLICY_APPROVED` / `POLICY_BLOCKED` / `POLICY_ESCALATED` (R13.10).

### The recovery budget is a global boundary, not a retry cap

**Recovery budget is a global automatic-recovery safety boundary. Once exhausted, no automatic recovery action may execute, regardless of action type.**

This is stated separately because the narrower reading is genuinely tempting and turned out to be wrong. Bounding only *retries* left the limit bypassable: once the retry budget was spent, a case could continue through non-retry channels — `SEND_PAYMENT_LINK`, then `SEND_REMINDER` — each an automatic action against a payment the system had already agreed to stop pushing. Observed behaviour before the fix, with `MAX_AUTOMATIC_RETRIES = 2`:

```
run  attempts_before  action              policy     rule                  executed?
1    1                RETRY_LATER         -          -                     yes
2    2                SEND_PAYMENT_LINK   APPROVED   default_approve       yes   <-- budget spent
3    3                SEND_REMINDER       APPROVED   default_approve       yes   <-- and again
4    4                RETRY_LATER         BLOCKED    retry_limit_reached   no

final attempt_count: 4, against a configured limit of 2
```

`repeated_failure_limit` did not save it, because the retry rule tripped first on run 4.

`RecoveryBudgetRule` closes the path. `RetryLimitRule` is kept ahead of it so a blocked retry retains its more specific `rule_id` and R13.3 stays literally satisfied; the budget rule then catches every other non-terminal action.

`ESCALATE_HUMAN` and `STOP` are exempt (R13.3c). Neither attempts a charge, and both are how an exhausted case is meant to end — blocking them would leave a case with no legal disposition.

**Component boundaries are unchanged by this rule** (R13.3e). The temptation was to filter exhausted-budget actions out of candidate generation, which would have been simpler and wrong: the refusal would vanish from the audit trail, and two components would then encode the same policy.

| Component | Responsibility | Knows about the budget? |
|---|---|---|
| `CandidateGenerator` | generates plausible actions for the diagnosis | **no** |
| `RecoveryDecisionEngine` | ranks candidates, selects the economically preferable one | **no** |
| `PolicyEngine` | decides whether the selected action is permitted | **yes** — sole owner |
| `ActionExecutor` | executes only policy-approved actions | never reached when blocked |
| `OutcomeVerifier` | independently verifies persisted payment state | not applicable |

Three tests hold this boundary in place: candidate sets are asserted identical before and after exhaustion, a source scan asserts `candidate_generator.py` contains no reference to the budget settings or the policy package, and a tripwire executor that raises on any call proves the executor is never invoked once the budget is spent.

### ActionExecutor and PaymentSimulatorExecutor (R14)

```python
@dataclass(frozen=True)
class ExecutionResult:
    action: ActionType
    status: ExecutionStatus       # SUCCEEDED | FAILED | SCHEDULED | ESCALATED | STOPPED
    provider_response: dict
    executed_at: datetime

class ActionExecutor(Protocol):
    def supports(self, action: ActionType) -> bool: ...
    def execute(self, action: ActionType, context: RecoveryContext) -> ExecutionResult: ...

class PaymentSimulatorExecutor(ActionExecutor): ...
```

Provider-independent by construction and resolved through the container from settings, so a Phase 1 `RazorpayTestExecutor` needs no change elsewhere (R14.11).

**Deterministic outcome derivation** (R14.8). A scripted table pins the outcomes the requirements mandate; everything else falls through to a seeded hash draw:

```python
SCRIPTED = {
    (BANK_TIMEOUT,        RETRY_LATER):           ALWAYS_SUCCEED,   # R14.5
    (EXPIRED_CARD,        RETRY_NOW):             ALWAYS_FAIL,      # R14.6
    (EXPIRED_CARD,        CHANGE_PAYMENT_METHOD): ALWAYS_SUCCEED,   # R14.6
    (INSUFFICIENT_FUNDS,  RETRY_NOW):             ALWAYS_FAIL,      # R14.7
    (INSUFFICIENT_FUNDS,  RETRY_LATER):           ALWAYS_FAIL,      # R14.7
}

def draw(seed, payment_id, action, attempt) -> float:
    digest = sha256(f"{seed}:{payment_id}:{action}:{attempt}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64
```

Unscripted pairs succeed when `draw < SCENARIO_SUCCESS_PROBABILITY[failure_reason][action]`, values read from settings and labelled synthetic (R14.9). Because the draw is a hash of stable inputs, results are reproducible across runs, processes, and machines.

Behaviour per action (R14.3): `RETRY_NOW` and `CHANGE_PAYMENT_METHOD` attempt immediately; `RETRY_LATER` returns `SCHEDULED` without touching the payment; `SEND_PAYMENT_LINK` and `SEND_REMINDER` simulate a recovery channel; `ESCALATE_HUMAN` returns `ESCALATED`; `STOP` returns `STOPPED`. On simulated success the payment status is updated and a successful `PaymentAttempt` is written (R14.10).

### OutcomeVerifier (R15)

```python
class OutcomeVerifier:
    def verify(self, action: RecoveryAction, previous_status: PaymentStatus) -> RecoveryOutcome: ...
```

Re-reads the persisted `Payment` and decides `recovered` from that state alone, never from `ExecutionResult.status` (R15.2). A failed → successful transition sets `recovered=True` with `recovered_amount = payment.amount`; anything else sets `recovered=False` and `recovered_amount = 0` (R15.3, R15.4). It holds no reference to the executor (R15.5). Writes `OUTCOME_VERIFIED`, plus `REVENUE_RECOVERED` when recovery is confirmed (R15.6).

This separation is what makes the recovered-revenue figure trustworthy: an executor that wrongly reports success still produces `recovered=False`, which R25.12 tests explicitly.

### AuditService (R19)

```python
class AuditService:
    def record(self, *, case_id: str, payment_id: str, stage: WorkflowStage,
               event_type: AuditEventType, message: str,
               metadata: dict, workflow_id: str) -> AuditEvent: ...
    def for_case(self, case_id: str) -> list[AuditEvent]: ...
```

The single writer of `AuditEvent` rows (R19.6); no other component touches the table. Append-only — no update or delete paths exist (R19.5). Every event carries the thirteen-type enum, case and payment ids, stage, message, metadata, and a `VirtualClock` timestamp (R19.2). `workflow_id` goes into metadata, which is what makes the R23.1 workflow record durably reconstructable without an eighth table. Payment method is recorded as a method type only, never instrument credentials (R19.8).

### AnalyticsService (R20)

```python
class AnalyticsService:
    def revenue(self) -> RevenueAnalytics: ...
    def recovery(self) -> RecoveryAnalytics: ...
```

Aggregates over persisted `Payment`, `RecoveryCase`, `RecoveryAction`, and `RecoveryOutcome` rows — no in-memory counters (R20.4). Recovered revenue sums verified outcomes only (R15.7). Recovery rate guards divide-by-zero by returning 0 (R20.3). Both payloads include a `data_source: "synthetic_simulation"` marker (R20.5).

### RevenueRecoveryWorkflow (R17)

```python
@dataclass(frozen=True)
class WorkflowRun:
    workflow_id: str; case_id: str; payment_id: str
    started_at: datetime; ended_at: datetime
    state: CaseState; selected_action: ActionType | None
    policy: PolicyResult | None; execution: ExecutionResult | None
    outcome: RecoveryOutcome | None; recovered_amount: int
    final_status: CaseState; waiting_until: datetime | None

class RevenueRecoveryWorkflow:
    def run(self, case_id: str) -> WorkflowRun: ...
```

One run performs exactly one decide → policy → execute → verify cycle (R17.2). Stage order:

1. Load case; reject terminal states with `CaseAlreadyTerminal` → HTTP 409 (R17.5, R24.9).
2. If a `SCHEDULED` action is not yet due, return early with `waiting_until` and execute nothing (R18.5).
3. `DIAGNOSING` → build context → diagnose → persist → `DIAGNOSED`.
4. `EVALUATING` → generate candidates → score → rank → select → `DECISION_READY`; persist `RecoveryAction`.
5. `POLICY_CHECK` → `PolicyEngine.evaluate`.
6. Branch on outcome: `BLOCKED` → `BLOCKED` → `STOPPED` + `WORKFLOW_STOPPED` (R17.6); `ESCALATED` → `ESCALATED`, nothing executed (R17.7); `APPROVED` → continue.
7. `RETRY_LATER` → set `scheduled_at`, state `SCHEDULED`, emit `ACTION_SCHEDULED`, return (R18.3).
8. Otherwise `EXECUTING` → `ActionExecutor.execute`.
9. `VERIFYING` → `OutcomeVerifier.verify`.
10. `recovered` → `RECOVERED` (terminal); else `FAILED`, which is re-runnable (R17.4).
11. Emit one log line per stage; return `WorkflowRun` (R23.2).

Any unhandled stage error is audited with the failing stage, leaves the case in a persisted recoverable state, and surfaces as the standard error envelope (R17.9).

## Data Models

Seven SQLAlchemy 2.0 entities, no more (R2.1). All money is integer minor units; currency defaults to `INR` (R2.8).

```
Customer ──1:N──> Payment ──1:N──> PaymentAttempt
                     │
                     └──1:N──> RecoveryCase ──1:N──> RecoveryAction ──1:1──> RecoveryOutcome
                                    │
                                    └──1:N──> AuditEvent
```

**Customer** (R2.3) — `customer_id` PK, `historical_payment_count`, `successful_payment_count`, `failed_payment_count`, `historical_success_rate` (float), `average_transaction_value` (int), `subscription_status` (enum), `metadata` (JSON), `is_synthetic` (bool), timestamps.

**Payment** (R2.2) — `payment_id` PK, `customer_id` FK→Customer, `amount` (int), `currency` (str, default `INR`), `payment_method` (enum), `status` (enum), `attempt_count` (int), `failure_reason` (enum, nullable), `merchant_id`, `metadata` (JSON), `is_synthetic`, `created_at`, `updated_at`. Indexed on `customer_id` and `status` (R2.10).

**PaymentAttempt** — `attempt_id` PK, `payment_id` FK, `attempt_number`, `status`, `failure_reason` (nullable), `action_type` (nullable — set when the attempt came from a recovery action), `provider_response` (JSON), `attempted_at`.

**RecoveryCase** (R2.4) — `case_id` PK, `payment_id` FK, `state` (enum), `amount_at_risk` (int), `diagnosis` (JSON), `terminal_outcome` (JSON, nullable), `created_at`, `updated_at`. Indexed on `payment_id` and `state`.

**RecoveryAction** (R2.5) — `action_id` PK, `case_id` FK, `payment_id` FK, `action_type` (enum), `estimated_probability` (float), `confidence` (float), `expected_recovery_value` (int), `erv_breakdown` (JSON), `risk_level` (enum), `policy_outcome` (enum), `policy_rule_id`, `policy_reason`, `decision_explanation` (JSON), `status` (enum), `model_version`, `created_at`, `scheduled_at` (nullable), `executed_at` (nullable). Indexed on `case_id`.

This single table absorbs what would otherwise be separate `RecoveryDecision` and `PolicyDecision` tables: the prediction, the ERV breakdown, the ranked alternatives inside `decision_explanation`, and the policy verdict all hang off the action they concern.

**RecoveryOutcome** (R2.6) — `outcome_id` PK, `action_id` FK unique, `previous_payment_status`, `new_payment_status`, `recovered` (bool), `recovered_amount` (int), `failure_reason` (nullable), `verification_timestamp`.

**AuditEvent** (R2.7) — `event_id` PK, `case_id` FK, `payment_id`, `stage` (enum), `event_type` (enum), `message` (str), `metadata` (JSON, carries `workflow_id`), `timestamp`. Indexed on `case_id`.

### Enumerations (R3)

`PaymentStatus`: `CREATED, PENDING, SUCCEEDED, FAILED, ABANDONED`. `CaseState`: the fifteen states above. `FailureReason`: `BANK_TIMEOUT, INSUFFICIENT_FUNDS, EXPIRED_CARD, NETWORK_ERROR, CHECKOUT_ABANDONMENT, SUBSCRIPTION_FAILURE, UNKNOWN` (R3.2). `ActionType`: `RETRY_NOW, RETRY_LATER, SEND_PAYMENT_LINK, CHANGE_PAYMENT_METHOD, SEND_REMINDER, ESCALATE_HUMAN, STOP` (R3.3). `PolicyOutcome`: `APPROVED, BLOCKED, ESCALATED` (R3.4). Plus `ActionStatus`, `RiskLevel`, `WorkflowStage`, `AuditEventType` (13 members), `PaymentMethod`, `SubscriptionStatus`, `FailureCategory`, `Transience`, `ExecutionStatus`.

## API Contract

All paths except `/health` sit under `API_PREFIX` (default `/api`) (R24.5). Money serializes as `{"amount": <int>, "currency": "INR"}` (R24.7). Errors use `{"error": {"code", "message"}}` (R1.8).

| Method | Path | Request | Response | Codes |
|---|---|---|---|---|
| GET | `/health` | — | app name, version, environment, `virtual_clock_time` | 200 |
| GET | `/payments` | `limit`, `offset`, `status?` | paginated payments | 200 |
| GET | `/payments/{payment_id}` | — | payment + attempt history | 200, 404 |
| POST | `/payments/simulate` | `customer_id?`, `amount`, `currency?`, `payment_method`, `status?`, `failure_reason?` | created payment | 201, 422 |
| POST | `/payments/{payment_id}/fail` | `failure_reason` | updated payment + opened case | 200, 404, 422 |
| GET | `/recovery/cases` | `limit`, `offset`, `state?` | paginated cases | 200 |
| GET | `/recovery/cases/{case_id}` | — | case, state, latest action, decision explanation, policy result | 200, 404 |
| POST | `/recovery/cases/{case_id}/run` | — | `WorkflowRun` projection | 200, 404, 409 |
| GET | `/recovery/cases/{case_id}/audit` | — | audit events, timestamp ascending | 200, 404 |
| POST | `/simulate/advance-clock` | `minutes?`, `hours?` | new `virtual_clock_time` | 200, 422 |
| GET | `/analytics/revenue` | — | at risk, recovered, rate, average | 200 |
| GET | `/analytics/recovery` | — | avg probability, action counts by disposition | 200 |

`POST /payments/{payment_id}/recover` from the earlier draft is deliberately absent; `POST /recovery/cases/{case_id}/run` is the single execution entry point.

## Data Flow

### Single run

```
POST /recovery/cases/{id}/run
  → RevenueRecoveryWorkflow.run(case_id)
      ├─ StateMachine: DETECTED → DIAGNOSING
      ├─ RecoveryContextBuilder.build(case)         [all DB reads happen here]
      ├─ DiagnosisEngine.diagnose(ctx)              → audit DIAGNOSIS_COMPLETED
      ├─ StateMachine: → DIAGNOSED → EVALUATING
      ├─ CandidateGenerator.generate(ctx, dx)
      ├─ for each candidate:
      │     RecoveryPredictor.predict(ctx, action)  → probability, confidence
      │     ExpectedRecoveryCalculator.calculate()  → ERV breakdown
      ├─ RecoveryDecisionEngine.decide()            → audit RECOVERY_OPTIONS_EVALUATED
      │                                             → audit RECOVERY_DECISION_SELECTED
      ├─ persist RecoveryAction; → DECISION_READY → POLICY_CHECK
      ├─ PolicyEngine.evaluate(ctx, decision)       → audit POLICY_{APPROVED|BLOCKED|ESCALATED}
      │     ├─ BLOCKED   → BLOCKED → STOPPED       → audit WORKFLOW_STOPPED   ⟂ ends
      │     ├─ ESCALATED → ESCALATED                                          ⟂ ends
      │     └─ APPROVED  ↓
      ├─ if RETRY_LATER: scheduled_at = now + delay; → SCHEDULED
      │                                             → audit ACTION_SCHEDULED  ⟂ ends
      ├─ → EXECUTING; ActionExecutor.execute()      → audit ACTION_{EXECUTED|FAILED}
      ├─ → VERIFYING; OutcomeVerifier.verify()      → audit OUTCOME_VERIFIED
      │                                             → audit REVENUE_RECOVERED (if recovered)
      └─ → RECOVERED (terminal) | FAILED (re-runnable)
```

### RETRY_LATER across the virtual clock (R18.9)

```
13:00  POST /payments/{id}/fail  {BANK_TIMEOUT}   → payment FAILED, case DETECTED
13:01  POST /recovery/cases/{id}/run
         diagnosis: TRANSIENT
         candidates: RETRY_NOW, RETRY_LATER, SEND_PAYMENT_LINK
         RETRY_LATER wins on ERV → policy APPROVED
         scheduled_at = 13:16 (13:01 + 15m); state SCHEDULED
13:01  POST /recovery/cases/{id}/run  → waiting_until 13:16, nothing executed
13:01  POST /simulate/advance-clock {minutes: 15}  → 13:16
13:16  POST /recovery/cases/{id}/run
         scheduled action due → EXECUTING
         simulator: (BANK_TIMEOUT, RETRY_LATER) is scripted ALWAYS_SUCCEED
         payment FAILED → SUCCEEDED
13:16  OutcomeVerifier: recovered=True, recovered_amount = payment.amount
         state RECOVERED; audit REVENUE_RECOVERED
```

## Error Handling

Domain errors in `app/core/errors.py`, each mapped to an HTTP status by a single handler registered in `create_app()`:

| Error | Status | Code |
|---|---|---|
| `RecordNotFound` | 404 | `NOT_FOUND` |
| `InvalidStateTransition` | 409 | `INVALID_STATE_TRANSITION` |
| `CaseAlreadyTerminal` | 409 | `CASE_TERMINAL` |
| `ActionNotDue` | 200 | returned as `waiting_until`, not an error |
| pydantic `ValidationError` | 422 | `VALIDATION_ERROR` |
| unhandled `Exception` | 500 | `INTERNAL_ERROR` |

Domain code raises domain errors and never imports `fastapi.HTTPException`, keeping services runnable outside HTTP (R27.8).

## Testing Strategy

### Correctness properties

These hold for all inputs and are the strongest signals worth asserting:

1. **Scorer purity** — `predict(ctx, a)` twice on the same context returns identical results, and probability stays within `[0.02, 0.97]` (R9.2, R9.4).
2. **Context determinism** — repeated `build()` over unchanged rows yields equal feature dicts (R6.4).
3. **Simulator reproducibility** — equal `(seed, payment_id, action, attempt)` yields equal outcomes (R14.8, R25.11).
4. **Transition safety** — no sequence of `transition` calls reaches `EXECUTING` without passing `DECISION_READY` and `POLICY_CHECK` (R16.9).
5. **Policy totality** — `evaluate` always returns one of the three outcomes with a non-empty `rule_id` (R13.1).
6. **Verification independence** — `recovered` is `True` only when the persisted payment status is successful, whatever the executor reported (R15.2, R25.12).
7. **Audit completeness** — every executed action and every verified outcome has a corresponding audit row (R27.6).
8. **ERV monotonicity** — with cost and penalty fixed, ERV rises strictly with probability (R10.1).

### Unit tests

Per-component files as listed in the folder structure, covering R25.1: models and schema init, payment creation, failure simulation, risk detection, diagnosis table, candidate sets for all seven failure reasons (R25.6), scorer ordering and bounds, the ERV worked example asserting exactly 708,000 (R25.7), decision ranking and tie-breaks (R25.8), each policy rule in isolation including approval and blocking, retry-limit stopping, state machine acceptance and the `DETECTED → EXECUTING` rejection (R25.10), clock advance arithmetic, simulator scripted pairs and hash reproducibility, verifier independence, audit append-only behaviour and the thirteen types, analytics arithmetic including the zero-at-risk guard.

### End-to-end tests (`test_workflow_e2e.py`)

**Successful recovery** (R25.2, R25.9) — `BANK_TIMEOUT` at 13:00, run schedules `RETRY_LATER` for 13:16, a run before that time executes nothing, `advance-clock` 15 minutes, next run executes and succeeds, verifier reports `recovered=True` with the full amount, case `RECOVERED`, and the audit trail contains `REVENUE_RISK_DETECTED`, `DIAGNOSIS_COMPLETED`, `RECOVERY_OPTIONS_EVALUATED`, `RECOVERY_DECISION_SELECTED`, `POLICY_APPROVED`, `ACTION_SCHEDULED`, `ACTION_EXECUTED`, `OUTCOME_VERIFIED`, `REVENUE_RECOVERED`.

**Stopped workflow** (R25.3) — `INSUFFICIENT_FUNDS`, repeated runs fail because the scripted table always fails those pairs, `attempt_count` reaches `MAX_AUTOMATIC_RETRIES`, `retry_limit_reached` blocks, case reaches `STOPPED`, `WORKFLOW_STOPPED` recorded, recovered revenue stays 0.

**Escalation** (R25.4) — payment above `HIGH_VALUE_ESCALATION_THRESHOLD`, `high_value_transaction` returns `ESCALATED`, case reaches `ESCALATED`, `POLICY_ESCALATED` recorded, and no `ACTION_EXECUTED` event exists.

**Alternative recovery** (R25.13) — `EXPIRED_CARD`, `RETRY_NOW` fails, re-run filters it out, `CHANGE_PAYMENT_METHOD` succeeds, case `RECOVERED`.

`conftest.py` provides a per-session temporary SQLite file, a fixed seed, a `VirtualClock` pointed at a `tmp_path` state file, and a FastAPI `TestClient`. No network access anywhere (R25.14).

## Local Setup

`.env.example` (R1.5):

```ini
APP_NAME=RevivePay API
VERSION=0.1.0
ENVIRONMENT=development
API_PREFIX=/api
LOG_LEVEL=INFO
DATABASE_URL=sqlite:///./revivepay.db
BACKEND_CORS_ORIGINS=http://localhost:5173

# --- Simulation (synthetic demo values) ---
SIMULATION_SEED=20260101
VIRTUAL_CLOCK_START=2026-01-01T13:00:00
VIRTUAL_CLOCK_STATE_PATH=./.revivepay_clock.json
RETRY_LATER_DELAY_MINUTES=15

# --- Policy ---
MAX_AUTOMATIC_RETRIES=2
REPEATED_FAILURE_LIMIT=3
HIGH_VALUE_ESCALATION_THRESHOLD=5000000   # paise = INR 50,000
ALLOW_HUMAN_ESCALATION=true
```

Commands, PowerShell on Windows (R26.2):

```powershell
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env

python scripts/init_db.py                        # create_all
python scripts/seed.py                           # synthetic scenarios
uvicorn app.main:app --reload                    # dev server, /docs
python scripts/demo.py                           # CLI walkthrough
python scripts/advance_clock.py --minutes 15     # CLI clock
pytest -q                                        # tests
```

## Example End-to-End Workflow

Seeded `BANK_TIMEOUT` case, ₹10,000 payment, customer success rate 0.94, attempt 1, subscriber:

```
Payment pay_0007   INR 10,000.00 (1,000,000 paise)   UPI   FAILED   BANK_TIMEOUT
Case    case_0007  DETECTED   amount at risk 1,000,000 paise

DIAGNOSIS      BANK_TIMEOUT · TRANSIENT · transient · escalation not required
               "Bank timeout is a transient infrastructure failure."

CANDIDATES     RETRY_NOW · RETRY_LATER · SEND_PAYMENT_LINK

SCORING        base × attempt_decay(0.75^1) × customer(0.70+0.60×0.94=1.264) × sub(1.05)
  RETRY_NOW           0.35 → 0.348   confidence 1.00
  RETRY_LATER         0.78 → 0.776   confidence 1.00
  SEND_PAYMENT_LINK   0.55 → 0.547   confidence 1.00

EXPECTED RECOVERY VALUE                    gross      cost   friction        ERV
  RETRY_NOW           p=0.348           348,000       500      2,000    345,500
  RETRY_LATER         p=0.776           776,000     2,000     10,000    764,000
  SEND_PAYMENT_LINK   p=0.547           547,000     3,000     15,000    529,000

SELECTED       RETRY_LATER
               "RETRY_LATER was selected because it has the highest expected
                recovery value (764000 paise) among the evaluated candidate actions."
               alternatives: SEND_PAYMENT_LINK 529,000 · RETRY_NOW 345,500

POLICY         APPROVED  rule=default_approve
               attempt_count 1 < 2 · 1,000,000 <= 5,000,000 · reason known

SCHEDULED      scheduled_at 13:16  (13:01 + 15m)   state SCHEDULED
               → advance-clock +15m → 13:16

EXECUTED       RETRY_LATER  SUCCEEDED  (scripted deterministic pair)
               payment pay_0007  FAILED → SUCCEEDED

VERIFIED       previous FAILED · new SUCCEEDED · recovered TRUE
               recovered_amount 1,000,000 paise (INR 10,000.00)

STATE          RECOVERED

AUDIT (9)      REVENUE_RISK_DETECTED · DIAGNOSIS_COMPLETED
               RECOVERY_OPTIONS_EVALUATED · RECOVERY_DECISION_SELECTED
               POLICY_APPROVED · ACTION_SCHEDULED · ACTION_EXECUTED
               OUTCOME_VERIFIED · REVENUE_RECOVERED

All figures are the result of a synthetic simulation. No real payment was processed.
```

The ₹10,000 × 0.72 → ₹7,080 case from R10.3 is the calculator unit test; the number above differs only because the live scorer produces 0.776 rather than a hardcoded 0.72.

## Requirements Coverage

| Requirement | Design element |
|---|---|
| R1 Foundation & config | `app/main.py` factory, `core/config.py`, `core/logging.py`, folder structure, `requirements.txt` |
| R2 Domain & persistence | Data Models section, 7 entities, relationships, indexes, `db/init_db.py` |
| R3 Enumerations | `core/enums.py`, Enumerations subsection |
| R4 Ingestion & failure sim | `services/payment_service.py`, `api/routes/payments.py` |
| R5 Risk detection | `services/risk_detector.py` |
| R6 Context building | `services/context_builder.py`, `RecoveryContext`, `features()` |
| R7 Diagnosis | `services/diagnosis_engine.py`, classification table, `Protocol` |
| R8 Candidate generation | `services/candidate_generator.py`, candidate table |
| R9 Deterministic prediction | `ml/predictor.py`, `ml/deterministic_scorer.py`, `ml/scoring_tables.py` |
| R10 Expected recovery value | `services/expected_value.py`, cost/penalty table, worked example |
| R11 Decision & ranking | `services/decision_engine.py`, tie-break rule |
| R12 Decision explanation | `DecisionExplanation`, `RecoveryAction.decision_explanation` |
| R13 Policy engine | `services/policy_engine.py`, `services/policy_rules.py`, rule table |
| R14 Execution & simulator | `integrations/action_executor.py`, `integrations/payment_simulator.py`, scripted table + hash draw |
| R15 Outcome verification | `services/outcome_verifier.py` |
| R16 State machine | `services/state_machine.py`, `TRANSITIONS` table |
| R17 Orchestration | `workflows/recovery_workflow.py`, stage order |
| R18 Virtual clock | `core/clock.py`, `api/routes/simulate.py`, `scripts/advance_clock.py`, timeline |
| R19 Audit trail | `services/audit_service.py`, 13 event types, `workflow_id` in metadata |
| R20 Analytics | `services/analytics_service.py` |
| R21 Scenario generation | `scripts/seed.py`, four deterministic scenarios |
| R22 CLI demo | `scripts/demo.py` |
| R23 Observability | `WorkflowRun`, per-stage logging, `core/logging.py` |
| R24 API contract | API Contract table, `app/schemas`, `app/api/routes` |
| R25 Test coverage | Testing Strategy, unit files, `test_workflow_e2e.py` |
| R26 Documentation | `README.md` outline in Local Setup |
| R27 Non-functional | `Protocol` interfaces, container injection, determinism properties |
| R28 Completion criteria | Verified by the 18 checks across unit, e2e, demo, and manual startup |

Every requirement maps to at least one design element, and every design element traces to a requirement.

## Deferred to Phase 1, and where it attaches

| Phase 1 capability | Attachment seam | Change required |
|---|---|---|
| ML recovery prediction | `RecoveryPredictor` Protocol in `app/ml` | new class + container registration |
| Dedicated `RecoveryFingerprint` | `RecoveryContext.features()` | extract to its own component |
| 10k training dataset, training script, model metrics | new `scripts/` entries + `app/ml` | additive |
| Batch evaluation and baseline comparison | reuses workflow, policy, executor, verifier unchanged | new script |
| LLM diagnosis | `DiagnosisEngine` Protocol | new class + registration |
| Confidence threshold routing | `PredictionResult.confidence` already populated | new policy rule + settings |
| Per-action analytics breakdown | `AnalyticsService` | new aggregate method |
| Human approve/reject loop | `StateMachine.TRANSITIONS` + `PolicyOutcome` | add `AWAITING_APPROVAL`, two endpoints |
| Razorpay test mode | `ActionExecutor` Protocol in `app/integrations` | new class + registration |
| Dashboard | existing HTTP API | frontend only |
| PostgreSQL | `DATABASE_URL` | configuration only |
