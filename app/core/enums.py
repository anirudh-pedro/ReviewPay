"""Shared enumerations for RevivePay.

Every status, action, and event type in the system is declared here. No component
compares free-text strings: members are referenced by symbol, and string
representations are confined to serialization boundaries and database storage
(Requirement 3.4, 3.5).

All enumerations subclass ``str`` so that SQLAlchemy persistence and pydantic
serialization produce stable, human-readable values.
"""

from enum import Enum


class PaymentStatus(str, Enum):
    """Lifecycle status of a payment."""

    CREATED = "CREATED"
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"

    @classmethod
    def successful(cls) -> frozenset["PaymentStatus"]:
        """Statuses that represent captured revenue."""
        return frozenset({cls.SUCCEEDED})

    @classmethod
    def unsuccessful(cls) -> frozenset["PaymentStatus"]:
        """Statuses that put revenue at risk."""
        return frozenset({cls.FAILED, cls.ABANDONED})


class PaymentMethod(str, Enum):
    """Payment instrument type.

    Recorded as a method type only. Instrument credentials are never stored or
    logged (Requirement 19.8).
    """

    UPI = "UPI"
    CARD = "CARD"
    NETBANKING = "NETBANKING"
    WALLET = "WALLET"
    EMI = "EMI"


class SubscriptionStatus(str, Enum):
    """Customer subscription standing."""

    NONE = "NONE"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


class FailureReason(str, Enum):
    """Why a payment did not succeed (Requirement 3.2).

    ``CHECKOUT_ABANDONMENT`` and ``SUBSCRIPTION_FAILURE`` are failure reasons on
    ordinary payments rather than separate entities: one unified pipeline handles
    every reason, and per-reason branching lives only in the candidate generator.
    """

    BANK_TIMEOUT = "BANK_TIMEOUT"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    EXPIRED_CARD = "EXPIRED_CARD"
    NETWORK_ERROR = "NETWORK_ERROR"
    CHECKOUT_ABANDONMENT = "CHECKOUT_ABANDONMENT"
    SUBSCRIPTION_FAILURE = "SUBSCRIPTION_FAILURE"
    UNKNOWN = "UNKNOWN"


class FailureCategory(str, Enum):
    """Diagnostic grouping of a failure reason."""

    TRANSIENT = "TRANSIENT"
    CUSTOMER_ACTION = "CUSTOMER_ACTION"
    TIME_DEPENDENT = "TIME_DEPENDENT"
    ENGAGEMENT = "ENGAGEMENT"
    UNKNOWN = "UNKNOWN"


class Transience(str, Enum):
    """Whether the failure cause is expected to clear on its own."""

    TRANSIENT = "TRANSIENT"
    PERSISTENT = "PERSISTENT"
    UNKNOWN = "UNKNOWN"


class ActionType(str, Enum):
    """Recovery actions (Requirement 3.3).

    Extensible: adding a member requires no change to the decision engine, policy
    engine, or action executor interfaces.
    """

    RETRY_NOW = "RETRY_NOW"
    RETRY_LATER = "RETRY_LATER"
    SEND_PAYMENT_LINK = "SEND_PAYMENT_LINK"
    CHANGE_PAYMENT_METHOD = "CHANGE_PAYMENT_METHOD"
    SEND_REMINDER = "SEND_REMINDER"
    ESCALATE_HUMAN = "ESCALATE_HUMAN"
    STOP = "STOP"

    @classmethod
    def retry_actions(cls) -> frozenset["ActionType"]:
        """Actions that consume a payment retry attempt."""
        return frozenset({cls.RETRY_NOW, cls.RETRY_LATER, cls.CHANGE_PAYMENT_METHOD})

    @classmethod
    def terminal_actions(cls) -> frozenset["ActionType"]:
        """Actions that end the workflow without attempting a payment."""
        return frozenset({cls.ESCALATE_HUMAN, cls.STOP})


class ActionStatus(str, Enum):
    """Lifecycle status of a recovery action record."""

    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    ESCALATED = "ESCALATED"
    SCHEDULED = "SCHEDULED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"


class ExecutionStatus(str, Enum):
    """Outcome reported by the action executor.

    Never treated as proof of recovery: the outcome verifier re-reads persisted
    payment state to decide that (Requirement 15.2).
    """

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SCHEDULED = "SCHEDULED"
    ESCALATED = "ESCALATED"
    STOPPED = "STOPPED"


class RiskLevel(str, Enum):
    """Risk classification of a proposed recovery action."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class PolicyOutcome(str, Enum):
    """Verdict from the policy engine (Requirement 3.4)."""

    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    ESCALATED = "ESCALATED"


class CaseState(str, Enum):
    """Recovery case lifecycle states (Requirement 16.1).

    Permitted transitions are declared in ``app.services.state_machine``; this
    enumeration only names the states.
    """

    DETECTED = "DETECTED"
    DIAGNOSING = "DIAGNOSING"
    DIAGNOSED = "DIAGNOSED"
    EVALUATING = "EVALUATING"
    DECISION_READY = "DECISION_READY"
    POLICY_CHECK = "POLICY_CHECK"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    SCHEDULED = "SCHEDULED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    RECOVERED = "RECOVERED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"
    STOPPED = "STOPPED"

    @classmethod
    def terminal(cls) -> frozenset["CaseState"]:
        """States from which no transition is permitted (Requirement 16.6)."""
        return frozenset({cls.RECOVERED, cls.ESCALATED, cls.STOPPED})


class WorkflowStage(str, Enum):
    """Named stage of a workflow run, recorded on every audit event."""

    DETECTION = "DETECTION"
    CONTEXT = "CONTEXT"
    DIAGNOSIS = "DIAGNOSIS"
    CANDIDATE_GENERATION = "CANDIDATE_GENERATION"
    EVALUATION = "EVALUATION"
    DECISION = "DECISION"
    POLICY = "POLICY"
    SCHEDULING = "SCHEDULING"
    EXECUTION = "EXECUTION"
    VERIFICATION = "VERIFICATION"
    COMPLETION = "COMPLETION"


class AuditEventType(str, Enum):
    """The thirteen auditable events of Phase 0 (Requirement 19.1)."""

    REVENUE_RISK_DETECTED = "REVENUE_RISK_DETECTED"
    DIAGNOSIS_COMPLETED = "DIAGNOSIS_COMPLETED"
    RECOVERY_OPTIONS_EVALUATED = "RECOVERY_OPTIONS_EVALUATED"
    RECOVERY_DECISION_SELECTED = "RECOVERY_DECISION_SELECTED"
    POLICY_APPROVED = "POLICY_APPROVED"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    POLICY_ESCALATED = "POLICY_ESCALATED"
    ACTION_SCHEDULED = "ACTION_SCHEDULED"
    ACTION_EXECUTED = "ACTION_EXECUTED"
    ACTION_FAILED = "ACTION_FAILED"
    OUTCOME_VERIFIED = "OUTCOME_VERIFIED"
    REVENUE_RECOVERED = "REVENUE_RECOVERED"
    WORKFLOW_STOPPED = "WORKFLOW_STOPPED"


__all__ = [
    "ActionStatus",
    "ActionType",
    "AuditEventType",
    "CaseState",
    "ExecutionStatus",
    "FailureCategory",
    "FailureReason",
    "PaymentMethod",
    "PaymentStatus",
    "PolicyOutcome",
    "RiskLevel",
    "SubscriptionStatus",
    "Transience",
    "WorkflowStage",
]
