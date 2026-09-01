"""Centralized, environment-safe RevivePay configuration."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.enums import ActionType, FailureReason

DEFAULT_INTERVENTION_COST_MINOR = {ActionType.RETRY_NOW.value: 500, ActionType.RETRY_LATER.value: 2_000, ActionType.SEND_PAYMENT_LINK.value: 3_000, ActionType.CHANGE_PAYMENT_METHOD.value: 3_000, ActionType.SEND_REMINDER.value: 1_000, ActionType.ESCALATE_HUMAN.value: 50_000, ActionType.STOP.value: 0}
DEFAULT_FRICTION_PENALTY_MINOR = {ActionType.RETRY_NOW.value: 2_000, ActionType.RETRY_LATER.value: 10_000, ActionType.SEND_PAYMENT_LINK.value: 15_000, ActionType.CHANGE_PAYMENT_METHOD.value: 20_000, ActionType.SEND_REMINDER.value: 8_000, ActionType.ESCALATE_HUMAN.value: 0, ActionType.STOP.value: 0}
DEFAULT_SIMULATOR_SUCCESS_PROBABILITY = {
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
PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod"})


class Settings(BaseSettings):
    """Typed runtime configuration; undeclared values fail rather than silently drift."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="forbid")

    app_name: str = "RevivePay API"
    app_description: str = "Deterministic synthetic revenue recovery operations platform."
    version: str = "0.4.0"
    environment: str = "development"
    api_prefix: str = "/api"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./revivepay.db"
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout_seconds: int = 30

    backend_cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_request_body_bytes: int = 1_048_576
    max_page_limit: int = 100
    max_page_offset: int = 10_000

    # disabled is local/demo/test only; production validation enforces api_key.
    auth_mode: Literal["disabled", "api_key"] = "disabled"
    api_key: str | None = None
    api_key_scopes: str = "operations:write,demo:reset"

    execution_mode: Literal["synchronous", "enqueue"] = "synchronous"
    worker_lease_seconds: int = 60
    worker_max_attempts: int = 3

    simulation_seed: int = 20260101
    virtual_clock_start: datetime = datetime(2026, 1, 1, 13, 0, 0)
    virtual_clock_state_path: str = "./.revivepay_clock.json"
    retry_later_delay_minutes: int = 15
    max_automatic_retries: int = 2
    repeated_failure_limit: int = 3
    high_value_escalation_threshold: int = 5_000_000
    allow_human_escalation: bool = True
    intervention_cost_minor: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_INTERVENTION_COST_MINOR))
    friction_penalty_minor: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_FRICTION_PENALTY_MINOR))
    simulator_success_probability: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_SIMULATOR_SUCCESS_PROBABILITY))
    simulator_fallback_probability: float = DEFAULT_SIMULATOR_FALLBACK_PROBABILITY
    diagnosis_engine_impl: str = "rule_based"
    recovery_predictor_impl: str = "deterministic"
    action_executor_impl: str = "simulator"
    local_model_artifact_path: str = "./artifacts/recovery_logistic_model.json"
    local_model_training_steps: int = 240
    local_model_learning_rate: float = 0.12
    ai_diagnosis_provider: str = "local_mock"
    default_currency: str = "INR"

    @field_validator("environment", "log_level")
    @classmethod
    def _normalise_text(cls, value: str) -> str:
        return value.strip().lower() if value.strip().lower() in {"production", "prod", "development", "demo", "local", "test"} else value.strip().upper()

    @model_validator(mode="after")
    def _validate_production_boundaries(self) -> "Settings":
        if self.is_production:
            if self.auth_mode != "api_key" or not self.api_key:
                raise ValueError("production requires AUTH_MODE=api_key and a non-empty API_KEY")
            if "*" in self.cors_origins:
                raise ValueError("production CORS origins must be explicit; '*' is not allowed")
            if self.execution_mode != "enqueue":
                raise ValueError("production requires EXECUTION_MODE=enqueue")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in PRODUCTION_ENVIRONMENTS

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]

    @property
    def auth_scopes(self) -> frozenset[str]:
        return frozenset(scope.strip() for scope in self.api_key_scopes.split(",") if scope.strip())

    def intervention_cost(self, action: ActionType) -> int:
        return int(self.intervention_cost_minor.get(action.value, DEFAULT_INTERVENTION_COST_MINOR.get(action.value, 0)))

    def friction_penalty(self, action: ActionType) -> int:
        return int(self.friction_penalty_minor.get(action.value, DEFAULT_FRICTION_PENALTY_MINOR.get(action.value, 0)))

    def scenario_success_probability(self, reason: FailureReason, action: ActionType) -> float:
        return float(self.simulator_success_probability.get(f"{reason.value}:{action.value}", self.simulator_fallback_probability))


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
