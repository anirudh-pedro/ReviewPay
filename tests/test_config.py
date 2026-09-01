"""Configuration and logging tests (Requirement 1.3-1.6, 10.5)."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.config import (
    DEFAULT_FRICTION_PENALTY_MINOR,
    DEFAULT_INTERVENTION_COST_MINOR,
    Settings,
    get_settings,
)
from app.core.enums import ActionType, FailureReason
from app.core.logging import configure_logging, get_logger

ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"

_ASSIGNMENT = re.compile(r"^\s*(?:#\s*)?([A-Z][A-Z0-9_]*)\s*=")


def _env_example_keys() -> tuple[set[str], set[str]]:
    """Return (active keys, commented keys) declared in .env.example."""
    active: set[str] = set()
    commented: set[str] = set()
    for raw in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        match = _ASSIGNMENT.match(raw)
        if not match:
            continue
        if raw.lstrip().startswith("#"):
            commented.add(match.group(1))
        else:
            active.add(match.group(1))
    return active, commented


def test_settings_load_with_no_env_file(monkeypatch, tmp_path):
    """Requirement 1.3: defaults work with no .env present."""
    monkeypatch.chdir(tmp_path)
    # `_env_file=None` excludes dotenv input, not inherited process variables.
    monkeypatch.delenv("API_PREFIX", raising=False)
    settings = Settings(_env_file=None)
    assert settings.app_name
    assert settings.api_prefix == "/api"
    assert settings.database_url.startswith("sqlite")
    assert settings.default_currency == "INR"


def test_get_settings_is_cached():
    assert get_settings() is get_settings()


def test_env_example_keys_all_map_to_settings_fields():
    """No dead or misspelled keys in .env.example."""
    active, commented = _env_example_keys()
    field_names = {name.upper() for name in Settings.model_fields}
    unknown = (active | commented) - field_names
    assert unknown == set(), f"keys in .env.example with no Settings field: {sorted(unknown)}"


def test_every_settings_field_is_documented_in_env_example():
    """Requirement 1.5: every variable the app reads is listed."""
    active, commented = _env_example_keys()
    documented = active | commented
    field_names = {name.upper() for name in Settings.model_fields}
    missing = field_names - documented
    assert missing == set(), f"Settings fields absent from .env.example: {sorted(missing)}"


def test_log_level_is_normalised_to_upper_case():
    assert Settings(_env_file=None, log_level="debug").log_level == "DEBUG"


def test_cors_origins_parsed_from_comma_separated_string():
    settings = Settings(_env_file=None, backend_cors_origins="http://a.test, http://b.test")
    assert settings.cors_origins == ["http://a.test", "http://b.test"]


def test_intervention_cost_and_friction_defined_for_every_action():
    """Requirement 10.5: documented defaults exist for every action."""
    settings = Settings(_env_file=None)
    for action in ActionType:
        assert settings.intervention_cost(action) >= 0
        assert settings.friction_penalty(action) >= 0
        assert action.value in DEFAULT_INTERVENTION_COST_MINOR
        assert action.value in DEFAULT_FRICTION_PENALTY_MINOR


def test_retry_later_costs_match_the_worked_example():
    """Requirement 10.3: RETRY_LATER costs 2000 with a 10000 friction penalty."""
    settings = Settings(_env_file=None)
    assert settings.intervention_cost(ActionType.RETRY_LATER) == 2_000
    assert settings.friction_penalty(ActionType.RETRY_LATER) == 10_000


def test_intervention_cost_is_overridable():
    settings = Settings(_env_file=None, intervention_cost_minor={"RETRY_NOW": 777})
    assert settings.intervention_cost(ActionType.RETRY_NOW) == 777
    # Unlisted actions still resolve through the documented defaults.
    assert settings.intervention_cost(ActionType.RETRY_LATER) == 2_000


def test_scenario_success_probability_falls_back_when_pair_absent():
    settings = Settings(_env_file=None, simulator_fallback_probability=0.11)
    probability = settings.scenario_success_probability(
        FailureReason.UNKNOWN, ActionType.SEND_REMINDER
    )
    assert probability == 0.11


def test_policy_defaults_match_the_specification():
    settings = Settings(_env_file=None)
    assert settings.max_automatic_retries == 2
    assert settings.repeated_failure_limit == 3
    assert settings.high_value_escalation_threshold == 5_000_000
    assert settings.allow_human_escalation is True
    assert settings.retry_later_delay_minutes == 15


def test_configure_logging_is_idempotent():
    configure_logging("INFO")
    configure_logging("DEBUG")
    assert get_logger("test").isEnabledFor(10)
