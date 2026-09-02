"""Recovery action model.

This table deliberately absorbs what would otherwise be separate
``RecoveryDecision`` and ``PolicyDecision`` tables. The prediction, the expected
recovery value breakdown, the ranked alternatives, and the policy verdict all
concern one proposed action, so they live on the action they describe
(Requirement 2.5).

Nothing here executes anything. The action is a record of intent plus the verdict
on that intent; execution authority belongs to the action executor alone.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Text
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ActionStatus, ActionType, PolicyOutcome, RiskLevel
from app.db.base import Base, IdColumn, MoneyMinorUnits, ShortText, enum_column
from app.db.integrity import ACTION_PAYMENT_FOREIGN_KEY

if TYPE_CHECKING:
    from app.models.recovery_case import RecoveryCase
    from app.models.recovery_outcome import RecoveryOutcome


class RecoveryAction(Base):
    """A recovery action proposed for a case, with its valuation and verdict."""

    __tablename__ = "recovery_actions"
    __table_args__ = (
        Index("ix_recovery_actions_case_id", "case_id"),
        Index("ix_recovery_actions_payment_id", "payment_id"),
        Index("ix_recovery_actions_action_type", "action_type"),
    )

    action_id: Mapped[str] = mapped_column(IdColumn, primary_key=True)
    case_id: Mapped[str] = mapped_column(
        IdColumn, ForeignKey("recovery_cases.case_id"), nullable=False
    )
    # Denormalised from the case for query convenience, but still a real
    # relationship: an action may never reference a payment that is not persisted
    # (Requirement 10.6).
    payment_id: Mapped[str] = mapped_column(
        IdColumn,
        ForeignKey("payments.payment_id", name=ACTION_PAYMENT_FOREIGN_KEY),
        nullable=False,
    )

    action_type: Mapped[ActionType] = mapped_column(enum_column(ActionType), nullable=False)

    # --- Prediction (Requirement 9) ---
    estimated_probability: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    model_version: Mapped[str] = mapped_column(ShortText, nullable=False)

    # --- Valuation (Requirement 10) ---
    # Minor units. May be negative when intervention cost exceeds gross recovery.
    expected_recovery_value: Mapped[int] = mapped_column(MoneyMinorUnits, nullable=False)
    erv_breakdown: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    risk_level: Mapped[RiskLevel] = mapped_column(
        enum_column(RiskLevel), default=RiskLevel.LOW, nullable=False
    )

    # --- Decision explanation (Requirement 12) ---
    # Holds selected_action, reason, probability, expected_recovery_value,
    # confidence, and the alternatives array.
    decision_explanation: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )

    # --- Policy verdict (Requirement 13.10) ---
    policy_outcome: Mapped[PolicyOutcome | None] = mapped_column(
        enum_column(PolicyOutcome), nullable=True
    )
    policy_rule_id: Mapped[str | None] = mapped_column(ShortText, nullable=True)
    policy_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[ActionStatus] = mapped_column(
        enum_column(ActionStatus), default=ActionStatus.PROPOSED, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Set for RETRY_LATER: the simulation time at which the retry becomes due
    # (Requirement 18.3).
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    case: Mapped["RecoveryCase"] = relationship(back_populates="actions")
    outcome: Mapped["RecoveryOutcome | None"] = relationship(
        back_populates="action",
        cascade="all, delete-orphan",
        uselist=False,
    )

    @property
    def requires_human_approval(self) -> bool:
        """True when policy routed this action to a human instead of executing it."""
        return self.policy_outcome == PolicyOutcome.ESCALATED

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<RecoveryAction {self.action_id} {self.action_type.value} "
            f"p={self.estimated_probability:.3f} erv={self.expected_recovery_value} "
            f"policy={self.policy_outcome.value if self.policy_outcome else None}>"
        )
