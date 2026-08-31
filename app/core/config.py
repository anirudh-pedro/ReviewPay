"""Application configuration.

All runtime configuration is loaded here and reached through ``get_settings()``.
No component reads ``os.environ`` directly, and no tunable value is embedded as a
literal in business logic (Requirement 1.3, 1.4).

Monetary settings are expressed in **minor currency units** (paise for INR)
throughout, matching the rest of the system.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.enums import ActionType, FailureReason

# ---------------------------------------------------------------------------
# Documented defaults (Requirement 10.5, 14.9)
#
# SYNTHETIC DEMONSTRATION VALUES. These costs, penalties, and probabilities are
# invented for a hackathon simulation. They are not measured from real payment
# traffic and must not be presented as such.
# ---------------------------------------------------------------------------

DEFAULT_INTERVENTION_COST_MINOR: dict[str, int] = {
    ActionType.RETRY_NOW.value: 500,  # INR 5
    ActionType.RETRY_LATER.value: 2_000,  # INR 20
    ActionType.SEND_PAYMENT_LINK.value: 3_000,  # INR 30
    ActionType.CHANGE_PAYMENT_METHOD.value: 3_000,  # INR 30
    ActionType.SEND_REMINDER.value: 1_000,  # INR 10
    ActionType.ESCALATE_HUMAN.value: 50_000,  # INR 500 (human time)
    ActionType.STOP.value: 0,
}

DEFAULT_FRICTION_PENALTY_MINOR: dict[str, int] = {
    ActionType.RETRY_NOW.value: 2_000,  # INR 20
    ActionType.RETRY_LATER.value: 10_000,  # INR 100
    ActionType.SEND_PAYMENT_LINK.value: 15_000,  # INR 150
    ActionType.CHANGE_PAYMENT_METHOD.value: 20_000,  # INR 200
    ActionType.SEND_REMINDER.value: 8_000,  # INR 80
    ActionType.ESCALATE_HUMAN.value: 0,
    ActionType.STOP.value: 0,
}

# Success probability for simulator pairs that are not deterministically scripted.
# Keyed "FAILURE_REASON:ACTION_TYPE". SYNTHETIC DEMONSTRATION VALUES.
DEFAULT_SIMULATOR_SUCCESS_PROBABILITY: dict[str, float] = {
    f"{FailureReason.BANK_TIMEOUT.value}:{ActionType.RETRY_NOW.value}": 0.35,
    f"{FailureReason.BANK_TIMEOUT.value}:{ActionType.SEND_PAYMENT_LINK.value}": 0.55,
    f"{FailureReason.NETWORK_ERROR.value}:{ActionType.RETRY_NOW.value}": 0.60,
    f"{FailureReason.NETWORK_ERROR.value}:{ActionType.RETRY_LATER.value}": 0.75,
    f"{FailureReason.INSUFFICIENT_FUNDS.value}:{ActionType.SEND_PAYMENT_LINK.value}": 0.40,
    f"{FailureReason.INSUFFICIENT_FUNDS.value}:{ActionType.SEND_REMINDER.value}": 0.35,
    f"{FailureReason.EXPIRED_CARD.value}:{ActionType.SEND_PAYMENT_LINK.value}": 0.58,
    f"{FailureReason.CHECKOUT_ABANDONMENT.value}:{ActionType.SEND_REMINDER.value}": 0.30,
    f"{FailureReason.CHECKOUT_ABANDONMENT.value}:{ActionType.SEND_PAYMENT_LINK.value}": 0.45,
    f"{FailureReason.SUBSCRIPTION_FAILURE.value}:{ActionType.RETRY_LATER.value}": 0.62,
    f"{FailureReason.SUBSCRIPTION_FAILURE.value}:{ActionType.SEND_REMINDER.value}": 0.35,
    f"{FailureReason.SUBSCRIPTION_FAILURE.value}:{ActionType.SEND_PAYMENT_LINK.value}": 0.48,
}

DEFAULT_SIMULATOR_FALLBACK_PROBABILITY = 0.30


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment variables and ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application metadata ---
    app_name: str = "RevivePay API"
    app_description: str = (
        "Autonomous revenue recovery for merchants. Phase 0 foundation: "
        "deterministic recovery intelligence over simulated payments."
    )
    version: str = "0.1.0"
    environment: str = "development"
    api_prefix: str = "/api"
    log_level: str = "INFO"

    # --- Database ---
    database_url: str = "sqlite:///./revivepay.db"
    db_echo: bool = False

    # --- CORS ---
    backend_cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Simulation (synthetic demo values) ---
    simulation_seed: int = 20260101
    virtual_clock_start: datetime = datetime(2026, 1, 1, 13, 0, 0)
    virtual_clock_state_path: str = "./.revivepay_clock.json"
    retry_later_delay_minutes: int = 15

    # --- Policy ---
    max_automatic_retries: int = 2
    repeated_failure_limit: int = 3
    high_value_escalation_threshold: int = 5_000_000  # paise = INR 50,000
    allow_human_escalation: bool = True

    # --- Expected recovery value (minor units) ---
    intervention_cost_minor: dict[str, int] = Field(
        default_factory=lambda: dict(DEFAULT_INTERVENTION_COST_MINOR)
    )
    friction_penalty_minor: dict[str, int] = Field(
        default_factory=lambda: dict(DEFAULT_FRICTION_PENALTY_MINOR)
    )

    # --- Payment simulator (synthetic demo values) ---
    simulator_success_probability: dict[str, float] = Field(
        default_factory=lambda: dict(DEFAULT_SIMULATOR_SUCCESS_PROBABILITY)
    )
    simulator_fallback_probability: float = DEFAULT_SIMULATOR_FALLBACK_PROBABILITY

    # --- Pluggable component implementations (Requirement 27.7) ---
    diagnosis_engine_impl: str = "rule_based"
    recovery_predictor_impl: str = "deterministic"
    action_executor_impl: str = "simulator"

    # --- Provenance ---
    default_currency: str = "INR"

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()

    @property
    def cors_origins(self) -> list[str]:
        """CORS origins parsed from the comma-separated setting."""
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]

    def intervention_cost(self, action: ActionType) -> int:
        """Intervention cost for an action, in minor units (Requirement 10.5)."""
        return int(
            self.intervention_cost_minor.get(
                action.value, DEFAULT_INTERVENTION_COST_MINOR.get(action.value, 0)
            )
        )

    def friction_penalty(self, action: ActionType) -> int:
        """Customer friction penalty for an action, in minor units."""
        return int(
            self.friction_penalty_minor.get(
                action.value, DEFAULT_FRICTION_PENALTY_MINOR.get(action.value, 0)
            )
        )

    def scenario_success_probability(self, reason: FailureReason, action: ActionType) -> float:
        """Simulator success probability for an unscripted pair (Requirement 14.9)."""
        key = f"{reason.value}:{action.value}"
        return float(
            self.simulator_success_probability.get(key, self.simulator_fallback_probability)
        )


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()


def reset_settings_cache() -> None:
    """Clear the settings cache. Used by tests that patch the environment."""
    get_settings.cache_clear()
