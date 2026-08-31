"""Structural guards for the architectural invariants.

These tests do not check behaviour. They check that the boundaries the design
depends on have not eroded, which is what keeps Phase 1 additive:

- domain layers stay free of HTTP concerns (Requirement 27.8)
- the expected-recovery-value formula exists in exactly one module (10.4)
- only the audit service writes audit rows (19.6)
- per-failure-reason branching lives only in the candidate generator (8.9)
- no machine-learning or scheduler dependency is present (1.10, 18.2)
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
PROJECT_ROOT = Path(__file__).resolve().parents[1]

DOMAIN_PACKAGES = ("services", "ml", "workflows", "integrations", "models", "core")


def _python_files(*relative_dirs: str) -> list[Path]:
    files: list[Path] = []
    for relative in relative_dirs:
        files.extend(sorted((APP_ROOT / relative).rglob("*.py")))
    return files


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module.split(".")[0])
    return modules


def test_domain_layers_do_not_import_fastapi():
    """Requirement 27.8: domain logic runs without FastAPI."""
    offenders: list[str] = []
    for path in _python_files(*DOMAIN_PACKAGES):
        imported = _imported_modules(path)
        if {"fastapi", "starlette"} & imported:
            offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert offenders == [], f"domain modules importing HTTP framework: {offenders}"


def test_domain_layers_do_not_import_the_api_package():
    """Dependencies point inward: nothing imports app.api."""
    offenders: list[str] = []
    for path in _python_files(*DOMAIN_PACKAGES):
        source = path.read_text(encoding="utf-8")
        if "app.api" in source:
            offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert offenders == [], f"domain modules referencing app.api: {offenders}"


def test_no_machine_learning_or_scheduler_dependency_is_declared():
    """Requirement 1.10, 18.2: Phase 0 stays ML-free and scheduler-free."""
    manifest = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
    active = [
        line.strip().lower()
        for line in manifest.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    forbidden = (
        "scikit-learn",
        "sklearn",
        "numpy",
        "joblib",
        "pandas",
        "torch",
        "apscheduler",
        "celery",
        "redis",
        "openai",
        "anthropic",
        "langchain",
        "alembic",
        "psycopg2",
    )
    for package in forbidden:
        assert not any(
            line.startswith(package) for line in active
        ), f"{package} must not be a Phase 0 dependency"


def test_no_domain_module_imports_a_machine_learning_library():
    """Requirement 9.3: the predictor uses no ML library."""
    forbidden = {"sklearn", "numpy", "joblib", "pandas", "torch", "apscheduler", "celery"}
    offenders: list[str] = []
    for path in _python_files(*DOMAIN_PACKAGES):
        if forbidden & _imported_modules(path):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert offenders == [], f"modules importing a forbidden library: {offenders}"


def test_expected_recovery_value_formula_lives_in_one_module():
    """Requirement 10.4: exactly one implementation of the ERV arithmetic.

    Detects the arithmetic, not the vocabulary. Other modules may freely *read*
    breakdown fields (the decision engine copies them into audit metadata); what
    they may not do is recompute the value. Two signatures give that away:
    subtracting a cost component, or multiplying a probability by an amount.
    """
    calculator = APP_ROOT / "services" / "expected_value.py"
    assert calculator.exists()

    # Lowercase identifiers only, and no newline between the operator and the
    # operand, so that banner comments and UPPER_CASE constants cannot match.
    cost_subtraction = re.compile(
        r"(?<!-)-[ \t]*(?:self\.)?[a-z_]*(?:intervention_cost|friction_penalty)\b"
    )
    gross_product = re.compile(
        r"probability[ \t]*\*[ \t]*[a-z_.]*amount\b|[a-z_.]*amount[ \t]*\*[ \t]*[a-z_.]*probability\b"
    )

    offenders: list[str] = []
    for path in _python_files(*DOMAIN_PACKAGES):
        if path == calculator:
            continue
        source = path.read_text(encoding="utf-8")
        if cost_subtraction.search(source) or gross_product.search(source):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert offenders == [], f"modules recomputing expected recovery value: {offenders}"


def test_only_the_audit_service_constructs_audit_event_rows():
    """Requirement 19.6: all audit writes funnel through the audit service."""
    audit_service = APP_ROOT / "services" / "audit_service.py"
    assert audit_service.exists()

    offenders: list[str] = []
    for path in _python_files(*DOMAIN_PACKAGES):
        if path in {audit_service, APP_ROOT / "models" / "audit_event.py"}:
            continue
        if "AuditEvent(" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert offenders == [], f"modules constructing AuditEvent directly: {offenders}"


def test_per_failure_reason_branching_lives_only_in_the_candidate_generator():
    """Requirement 8.9, 9.9.

    The candidate generator and the diagnosis engine legitimately map failure
    reasons to behaviour. Scoring tables are declarative data. No other decision
    component may branch on a specific failure reason.
    """
    allowed = {
        APP_ROOT / "services" / "candidate_generator.py",
        APP_ROOT / "services" / "diagnosis_engine.py",
        APP_ROOT / "ml" / "scoring_tables.py",
        APP_ROOT / "core" / "enums.py",
        APP_ROOT / "core" / "config.py",
    }
    watched = {
        APP_ROOT / "services" / "risk_detector.py",
        APP_ROOT / "services" / "decision_engine.py",
        APP_ROOT / "ml" / "deterministic_scorer.py",
    }
    offenders: list[str] = []
    for path in watched:
        if not path.exists() or path in allowed:
            continue
        source = path.read_text(encoding="utf-8")
        for member in ("BANK_TIMEOUT", "EXPIRED_CARD", "INSUFFICIENT_FUNDS"):
            if f"FailureReason.{member}" in source:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)} branches on {member}")
    assert offenders == [], f"per-reason branching outside the candidate generator: {offenders}"
