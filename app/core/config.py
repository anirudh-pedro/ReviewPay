"""Centralized, environment-safe RevivePay configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from types import MappingProxyType
from typing import Literal, Mapping

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.enums import ActionType, FailureReason

DEFAULT_INTERVENTION_COST_MINOR = {ActionType.RETRY_NOW.value: 500, ActionType.RETRY_LATER.value: 2_000, ActionType.SEND_PAYMENT_LINK.value: 3_000, ActionType.CHANGE_PAYMENT_METHOD.value: 3_000, ActionType.SEND_REMINDER.value: 1_000, ActionType.ESCALATE_HUMAN.value: 50_000, ActionType.STOP.value: 0, ActionType.VOICE_CALL.value: 2_500}
DEFAULT_FRICTION_PENALTY_MINOR = {ActionType.RETRY_NOW.value: 2_000, ActionType.RETRY_LATER.value: 10_000, ActionType.SEND_PAYMENT_LINK.value: 15_000, ActionType.CHANGE_PAYMENT_METHOD.value: 20_000, ActionType.SEND_REMINDER.value: 8_000, ActionType.ESCALATE_HUMAN.value: 0, ActionType.STOP.value: 0, ActionType.VOICE_CALL.value: 12_000}
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

# ---------------------------------------------------------------------------
# Environment profiles (Requirement 9.1)
# ---------------------------------------------------------------------------
#
# ``ENVIRONMENT`` stays a free-text deployment label so existing values such as
# ``development`` keep working verbatim in responses and logs. Every supported
# label resolves to exactly one of five normalized profiles, and *policy* is read
# from the profile rather than from string comparisons scattered across modules.

PROFILE_LOCAL = "local"
PROFILE_DEMO = "demo"
PROFILE_TEST = "test"
PROFILE_STAGING = "staging"
PROFILE_PRODUCTION = "production"

ENVIRONMENT_PROFILES: tuple[str, ...] = (PROFILE_LOCAL, PROFILE_DEMO, PROFILE_TEST, PROFILE_STAGING, PROFILE_PRODUCTION)

#: Accepted ``ENVIRONMENT`` labels and the profile each one resolves to.
ENVIRONMENT_PROFILE_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "local": PROFILE_LOCAL,
        "development": PROFILE_LOCAL,
        "dev": PROFILE_LOCAL,
        "demo": PROFILE_DEMO,
        "test": PROFILE_TEST,
        "testing": PROFILE_TEST,
        "ci": PROFILE_TEST,
        "staging": PROFILE_STAGING,
        "stage": PROFILE_STAGING,
        "production": PROFILE_PRODUCTION,
        "prod": PROFILE_PRODUCTION,
    }
)

#: Profiles that carry real operational authority and therefore fail closed.
PROTECTED_PROFILES = frozenset({PROFILE_STAGING, PROFILE_PRODUCTION})
#: Profiles that may run the documented development authentication mode.
DEVELOPMENT_PROFILES = frozenset({PROFILE_LOCAL, PROFILE_DEMO, PROFILE_TEST})
#: Profiles in which destructive demo reset is permitted (Requirement 9.5).
RESETTABLE_PROFILES = frozenset({PROFILE_LOCAL, PROFILE_DEMO, PROFILE_TEST})
#: Profiles in which ``create_all``/``drop_all`` bootstrap is permitted.
#: Staging and production are excluded: Alembic is their only schema path
#: (Requirement 10.2).
SCHEMA_BOOTSTRAP_PROFILES = frozenset({PROFILE_LOCAL, PROFILE_DEMO, PROFILE_TEST})


@dataclass(frozen=True)
class ProfilePolicy:
    """Immutable, derived security and operational policy for one profile.

    Every field answers a question a caller would otherwise answer by comparing
    environment strings. Nothing here holds a secret, so the policy is safe to
    log or return in non-secret operational status evidence.
    """

    profile: str
    #: Local/demo/test may run the documented disabled-authentication demo mode.
    allows_disabled_authentication: bool
    #: Staging/production must be configured with approved secret authentication.
    requires_secret_authentication: bool
    #: Staging/production require an authenticated principal for every mutation.
    requires_authenticated_operational_principal: bool
    #: Wildcard CORS is never acceptable for a protected profile.
    allows_wildcard_cors_origins: bool
    #: ``create_all``/``drop_all`` bootstrap paths (Alembic is the only other path).
    allows_schema_bootstrap: bool
    #: Destructive demo reset.
    allows_destructive_reset: bool
    #: Startup/readiness must verify the supported schema revision.
    requires_schema_revision_check: bool
    #: Emit HSTS and expect TLS termination in front of the process.
    requires_transport_security: bool
    #: No profile enables a real-money provider executor (Requirement 7.7).
    allows_provider_action_executor: bool = False


def _build_profile_policy(profile: str) -> ProfilePolicy:
    protected = profile in PROTECTED_PROFILES
    return ProfilePolicy(
        profile=profile,
        allows_disabled_authentication=profile in DEVELOPMENT_PROFILES,
        requires_secret_authentication=protected,
        requires_authenticated_operational_principal=protected,
        allows_wildcard_cors_origins=not protected,
        allows_schema_bootstrap=profile in SCHEMA_BOOTSTRAP_PROFILES,
        allows_destructive_reset=profile in RESETTABLE_PROFILES,
        requires_schema_revision_check=protected,
        requires_transport_security=protected,
    )


#: One frozen policy per profile; profiles are a closed set, so this is complete.
PROFILE_POLICIES: Mapping[str, ProfilePolicy] = MappingProxyType(
    {profile: _build_profile_policy(profile) for profile in ENVIRONMENT_PROFILES}
)


def resolve_environment_profile(environment: str) -> str:
    """Normalize an ``ENVIRONMENT`` label to its profile, or fail closed."""
    candidate = (environment or "").strip().lower()
    try:
        return ENVIRONMENT_PROFILE_ALIASES[candidate]
    except KeyError:
        raise ValueError(
            "ENVIRONMENT must name a supported profile. Accepted values: "
            f"{', '.join(sorted(ENVIRONMENT_PROFILE_ALIASES))}."
        ) from None


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
    ai_copilot_provider: str = "local_mock"
    rate_limit_requests_per_minute: int = 120
    default_currency: str = "INR"

    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"

    # Razorpay is an opt-in Sandbox gateway path. Simulator execution remains the default.
    razorpay_enabled: bool = False
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_webhook_secret: str | None = None
    razorpay_api_base_url: str = "https://api.razorpay.com/v1"
    razorpay_timeout_seconds: int = 10

    # Live Email Delivery (Resend / SendGrid / SMTP)
    resend_api_key: str | None = None
    sendgrid_api_key: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    email_from: str = "RevivePay Recovery <onboarding@resend.dev>"

    # Exotel Voice Recovery Channel
    exotel_api_key: str | None = None
    exotel_api_password: str | None = None
    exotel_account_sid: str | None = None
    exotel_subdomain: str = "api.exotel.com"
    exotel_caller_id: str | None = None
    exotel_flow_id: str | None = None

    @field_validator("environment")
    @classmethod
    def _normalise_environment(cls, value: str) -> str:
        # Fail closed on an unrecognized label rather than guessing a policy for it.
        resolve_environment_profile(value)
        return value.strip().lower()

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def _validate_production_boundaries(self) -> "Settings":
        if self.razorpay_enabled and (
            not self.razorpay_key_id or not self.razorpay_key_secret
        ):
            raise ValueError(
                "RAZORPAY_ENABLED requires RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET"
            )
        policy = self.profile_policy
        if policy.requires_secret_authentication:
            # Requirement 9.3, 9.9: a protected profile cannot start without
            # approved secret authentication and explicit browser origins.
            if self.auth_mode != "api_key" or not self.api_key:
                raise ValueError(f"{policy.profile} requires AUTH_MODE=api_key and a non-empty API_KEY")
            if not self.auth_scopes:
                raise ValueError(f"{policy.profile} requires at least one API_KEY_SCOPES entry")
        if not policy.allows_wildcard_cors_origins and "*" in self.cors_origins:
            raise ValueError(f"{policy.profile} CORS origins must be explicit; '*' is not allowed")
        if self.is_production and self.execution_mode != "enqueue":
            raise ValueError("production requires EXECUTION_MODE=enqueue")
        return self

    @property
    def environment_profile(self) -> str:
        """The normalized profile (``local``, ``demo``, ``test``, ``staging``, ``production``)."""
        return resolve_environment_profile(self.environment)

    @property
    def profile_policy(self) -> ProfilePolicy:
        """Derived, immutable, secret-free policy for the resolved profile."""
        return PROFILE_POLICIES[self.environment_profile]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in PRODUCTION_ENVIRONMENTS

    @property
    def is_protected_profile(self) -> bool:
        """True for staging and production, which fail closed on security gaps."""
        return self.environment_profile in PROTECTED_PROFILES

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]

    @property
    def auth_scopes(self) -> frozenset[str]:
        return frozenset(scope.strip() for scope in self.api_key_scopes.split(",") if scope.strip())

    def profile_summary(self) -> dict[str, str]:
        """Non-secret startup/diagnostic summary.

        Deliberately excludes the API key, provider credentials, and the database
        URL so the summary can be logged verbatim (Requirement 9.7, 9.8).
        """
        policy = self.profile_policy
        return {
            "environment": self.environment,
            "environment_profile": policy.profile,
            "authentication_mode": self.auth_mode,
            "authenticated_principal_required": str(policy.requires_authenticated_operational_principal).lower(),
            "execution_mode": self.execution_mode,
            "action_executor": self.action_executor_impl,
            "cors_origin_count": str(len(self.cors_origins)),
            "schema_bootstrap_allowed": str(policy.allows_schema_bootstrap).lower(),
            "destructive_reset_allowed": str(policy.allows_destructive_reset).lower(),
        }

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
