"""Centralized, leakage-safe feature engineering for local recovery modeling.

Only facts available before a proposed recovery action are encoded here.  In
particular, the current action's execution state, outcome, recovered amount, and
case terminal state are deliberately absent.  The same inspectable projection is
used for synthetic training and live local-model inference.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import log1p
from typing import Mapping

from app.core.enums import ActionType, FailureReason, PaymentMethod, SubscriptionStatus
from app.services.context_builder import RecoveryContext

FEATURE_SCHEMA_VERSION = "recovery-pre-action-v1"


@dataclass(frozen=True)
class FeatureVector:
    """An inspectable numeric projection with stable feature ordering."""

    values: Mapping[str, float]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self.values)

    def as_dict(self) -> dict[str, float]:
        return dict(self.values)


class RecoveryFeatureEngineer:
    """Encode only persisted, pre-action recovery context into numeric features."""

    schema_version = FEATURE_SCHEMA_VERSION

    def feature_names(self) -> tuple[str, ...]:
        names = (
            "log_payment_amount",
            "attempt_count",
            "customer_success_rate",
            "log_customer_total_payments",
            "log_customer_failed_payments",
            "log_customer_average_transaction_value",
            "is_subscriber",
            "is_returning_customer",
            "customer_history_available",
            "previous_recovery_attempt_count",
            "unsuccessful_outcome_count",
            "transaction_hour_normalized",
            "days_since_previous_payment_known",
            "days_since_previous_payment_capped",
        )
        reason = tuple(f"failure_reason__{item.value}" for item in FailureReason)
        method = tuple(f"payment_method__{item.value}" for item in PaymentMethod)
        subscription = tuple(
            f"subscription_status__{item.value}" for item in SubscriptionStatus
        )
        action = tuple(f"candidate_action__{item.value}" for item in ActionType)
        return (*names, *reason, *method, *subscription, *action)

    def transform(self, context: RecoveryContext, action: ActionType) -> FeatureVector:
        """Return a deterministic feature vector for one proposed action.

        ``action`` is an input candidate, not an observed action result.  This is
        how one model can score each candidate separately without outcome leakage.
        """

        days = context.days_since_previous_payment
        values: dict[str, float] = {
            "log_payment_amount": round(log1p(max(context.amount, 0)), 8),
            "attempt_count": float(max(context.attempt_count, 0)),
            "customer_success_rate": round(
                min(max(context.customer.success_rate, 0.0), 1.0), 8
            ),
            "log_customer_total_payments": round(
                log1p(max(context.customer.total_payments, 0)), 8
            ),
            "log_customer_failed_payments": round(
                log1p(max(context.customer.failed_payments, 0)), 8
            ),
            "log_customer_average_transaction_value": round(
                log1p(max(context.customer.average_transaction_value, 0)), 8
            ),
            "is_subscriber": float(context.customer.is_subscriber),
            "is_returning_customer": float(context.is_returning_customer),
            "customer_history_available": float(context.customer.history_available),
            "previous_recovery_attempt_count": float(
                max(context.previous_recovery_attempt_count, 0)
            ),
            "unsuccessful_outcome_count": float(max(context.unsuccessful_outcome_count, 0)),
            "transaction_hour_normalized": round(
                min(max(context.transaction_hour, 0), 23) / 23.0, 8
            ),
            "days_since_previous_payment_known": float(days is not None),
            "days_since_previous_payment_capped": float(min(max(days or 0, 0), 365)),
        }
        values.update(
            {
                f"failure_reason__{item.value}": float(item is context.failure_reason)
                for item in FailureReason
            }
        )
        values.update(
            {
                f"payment_method__{item.value}": float(item is context.payment_method)
                for item in PaymentMethod
            }
        )
        values.update(
            {
                f"subscription_status__{item.value}": float(
                    item is context.customer.subscription_status
                )
                for item in SubscriptionStatus
            }
        )
        values.update(
            {
                f"candidate_action__{item.value}": float(item is action)
                for item in ActionType
            }
        )
        return FeatureVector({name: values[name] for name in self.feature_names()})


__all__ = ["FEATURE_SCHEMA_VERSION", "FeatureVector", "RecoveryFeatureEngineer"]
