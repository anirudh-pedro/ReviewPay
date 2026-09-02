"""Focused coverage for the non-mutating release-input report."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import source_tracking_guard
from scripts.cleanup_inventory import INVENTORY_MARKER
from scripts.release_evidence import (
    BASELINE_MARKER,
    BASELINE_MINIMUM_PASSING_BACKEND_TESTS,
    REPLACEMENT_COVERAGE_MARKER,
    REQUIRED_RELEASE_CAVEATS,
    load_baseline_evidence,
    missing_caveats,
    validate_baseline_evidence,
)
from scripts.release_inputs import MANDATORY_CHECKS, build_release_input_report

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RELEASE_DOCS = REPOSITORY_ROOT / "docs" / "release"

BASELINE_RECORD: dict[str, Any] = {
    "schema_version": 1,
    "recorded_at": "2026-09-02",
    "repository_revision": "ef05745d7d35a14182730a095df0c62f78b5d56d",
    "baseline_passing_backend_tests": BASELINE_MINIMUM_PASSING_BACKEND_TESTS,
    "frontend_typecheck": "pass",
    "frontend_production_build": "pass",
    "commands": {
        "backend_tests": "python -m pytest -q",
        "frontend_typecheck": "npm --prefix frontend run typecheck",
        "frontend_build": "npm --prefix frontend run build",
    },
}


def _check(report: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in report["checks"] if item["name"] == name)


def _tracking_report(*, failing: list[dict[str, Any]] | None = None, **overrides: Any) -> dict[str, Any]:
    """A Source Tracking Guard report shaped like the real guard's output."""

    required_files = [
        {
            "discovery_evidence": [{"kind": "python_startup", "origin": "app/main.py"}],
            "errors": [],
            "exists": True,
            "ignored": False,
            "matching_ignore_rule": None,
            "path": "app/main.py",
            "readable": True,
            "required": True,
            "tracked": True,
        },
        *(failing or []),
    ]
    failed = sum(bool(item["errors"]) for item in required_files)
    report = {
        "schema_version": source_tracking_guard.SCHEMA_VERSION,
        "status": "pass" if failed == 0 else "fail",
        "git": {"available": True},
        "required_files": required_files,
        "summary": {"failed": failed, "required": len(required_files)},
        "tool_errors": [],
    }
    report.update(overrides)
    return report


def _untracked_finding(path: str) -> dict[str, Any]:
    return {
        "discovery_evidence": [{"kind": "application_models", "origin": "app/models"}],
        "errors": ["IGNORED", "UNTRACKED"],
        "exists": True,
        "ignored": True,
        "matching_ignore_rule": {"line": 1, "pattern": "/models/", "source": ".gitignore"},
        "path": path,
        "readable": True,
        "required": True,
        "tracked": False,
    }


def _write_release_docs(
    root: Path,
    *,
    baseline: Any = None,
    replacements: Any = None,
    inventory: Any = None,
) -> Path:
    """Write a temporary docs/release directory with both reviewed documents."""

    docs = root / "docs" / "release"
    docs.mkdir(parents=True, exist_ok=True)
    baseline_record = BASELINE_RECORD if baseline is None else baseline
    (docs / "baseline-evidence.md").write_text(
        f"# Baseline\n\n<!-- {BASELINE_MARKER} -->\n\n"
        f"```json\n{json.dumps(baseline_record, indent=2)}\n```\n\n"
        f"## Replacement coverage\n\n<!-- {REPLACEMENT_COVERAGE_MARKER} -->\n\n"
        f"```json\n{json.dumps(replacements if replacements is not None else [], indent=2)}\n```\n",
        encoding="utf-8",
    )
    (docs / "cleanup-inventory.md").write_text(
        f"# Inventory\n\n<!-- {INVENTORY_MARKER} -->\n\n"
        f"```json\n{json.dumps(inventory if inventory is not None else [], indent=2)}\n```\n",
        encoding="utf-8",
    )
    return docs


def _replacement_record(removed_test: str) -> dict[str, Any]:
    return {
        "removed_test": removed_test,
        "removal_reason": "the behavior it described was superseded by an approved change",
        "retained_coverage": ["tests/test_example.py::test_equivalent_case"],
        "reviewer": "release reviewer",
        "reviewed_at": "2026-09-02",
    }


# ---------------------------------------------------------------------------
# Reviewed repository documents
# ---------------------------------------------------------------------------


def test_repository_baseline_document_is_a_complete_comparison_point():
    record = load_baseline_evidence(RELEASE_DOCS / "baseline-evidence.md")

    assert validate_baseline_evidence(record) == []
    assert record["baseline_passing_backend_tests"] == BASELINE_MINIMUM_PASSING_BACKEND_TESTS
    assert record["frontend_typecheck"] == "pass"
    assert record["frontend_production_build"] == "pass"


def test_release_validation_template_declares_the_required_limitations():
    template = (RELEASE_DOCS / "release-validation-template.md").read_text(encoding="utf-8")

    assert missing_caveats(template) == []


def test_reviewed_repository_documents_pass_every_input_check_but_tracking():
    report = build_release_input_report(
        REPOSITORY_ROOT,
        observed_passing_backend_tests=BASELINE_MINIMUM_PASSING_BACKEND_TESTS,
        tracking_report=_tracking_report(),
    )

    assert report["status"] == "ready"
    assert report["blocking_reasons"] == []
    assert [check["name"] for check in report["checks"]] == list(MANDATORY_CHECKS)
    assert all(check["status"] == "pass" for check in report["checks"])
    assert report["caveats"] == list(REQUIRED_RELEASE_CAVEATS)


# ---------------------------------------------------------------------------
# Source tracking input
# ---------------------------------------------------------------------------


def test_untracked_required_source_blocks_the_release_inputs(tmp_path: Path):
    docs = _write_release_docs(tmp_path)

    report = build_release_input_report(
        tmp_path,
        observed_passing_backend_tests=601,
        tracking_report=_tracking_report(failing=[_untracked_finding("app/models/payment.py")]),
        release_docs_root=docs,
    )
    tracking = _check(report, "source_tracking")

    assert report["status"] == "not_ready"
    assert "source_tracking:REQUIRED_RUNTIME_SOURCE_NOT_RELEASE_TRACKED" in report["blocking_reasons"]
    assert tracking["findings"][0]["path"] == "app/models/payment.py"
    assert tracking["findings"][0]["errors"] == ["IGNORED", "UNTRACKED"]
    assert tracking["findings"][0]["matching_ignore_rule"]["pattern"] == "/models/"
    assert tracking["findings"][0]["discovery_evidence"]


def test_guard_tool_error_blocks_the_release_inputs(tmp_path: Path):
    docs = _write_release_docs(tmp_path)

    report = build_release_input_report(
        tmp_path,
        observed_passing_backend_tests=601,
        tracking_report=_tracking_report(status="fail", tool_errors=["GIT_UNAVAILABLE"]),
        release_docs_root=docs,
    )

    assert report["status"] == "not_ready"
    assert "source_tracking:TRACKING_TOOL_ERROR:GIT_UNAVAILABLE" in report["blocking_reasons"]


@pytest.mark.parametrize(
    ("report_value", "expected_reason"),
    [
        ("not-a-report", "TRACKING_REPORT_INVALID"),
        ({"schema_version": 999, "status": "pass"}, "TRACKING_REPORT_SCHEMA_UNSUPPORTED"),
        ({"schema_version": source_tracking_guard.SCHEMA_VERSION, "status": "pass"}, "TRACKING_REPORT_INVALID"),
    ],
)
def test_unusable_tracking_report_fails_closed(tmp_path: Path, report_value: Any, expected_reason: str):
    docs = _write_release_docs(tmp_path)

    report = build_release_input_report(
        tmp_path,
        observed_passing_backend_tests=601,
        tracking_report=report_value,
        release_docs_root=docs,
    )

    assert report["status"] == "not_ready"
    assert f"source_tracking:{expected_reason}" in report["blocking_reasons"]


def test_report_runs_the_guard_when_no_tracking_report_is_injected(tmp_path: Path):
    # A bare directory is not a Git work tree, so the guard reports the tool error
    # rather than a passing tracking result. This confirms the report consumes the
    # real guard instead of re-implementing discovery.
    docs = _write_release_docs(tmp_path)

    report = build_release_input_report(
        tmp_path,
        observed_passing_backend_tests=601,
        release_docs_root=docs,
    )
    tracking = _check(report, "source_tracking")

    assert tracking["status"] == "fail"
    assert "TRACKING_TOOL_ERROR:GIT_UNAVAILABLE" in tracking["reasons"]


# ---------------------------------------------------------------------------
# Baseline test-count gate
# ---------------------------------------------------------------------------


def test_missing_observed_test_count_is_not_ready(tmp_path: Path):
    docs = _write_release_docs(tmp_path)

    report = build_release_input_report(
        tmp_path,
        tracking_report=_tracking_report(),
        release_docs_root=docs,
    )

    assert report["status"] == "not_ready"
    assert "backend_test_baseline:BACKEND_TEST_COUNT_NOT_SUPPLIED" in report["blocking_reasons"]


def test_count_at_or_above_the_baseline_passes(tmp_path: Path):
    docs = _write_release_docs(tmp_path)

    report = build_release_input_report(
        tmp_path,
        observed_passing_backend_tests=601,
        tracking_report=_tracking_report(),
        release_docs_root=docs,
    )

    assert report["status"] == "ready"
    assert _check(report, "backend_test_baseline")["deficit"] == 0


def test_count_below_the_baseline_without_replacement_coverage_fails(tmp_path: Path):
    docs = _write_release_docs(tmp_path)

    report = build_release_input_report(
        tmp_path,
        observed_passing_backend_tests=BASELINE_MINIMUM_PASSING_BACKEND_TESTS - 2,
        tracking_report=_tracking_report(),
        release_docs_root=docs,
    )
    gate = _check(report, "backend_test_baseline")

    assert report["status"] == "not_ready"
    assert gate["reasons"] == ["BACKEND_TEST_COUNT_BELOW_BASELINE"]
    assert gate["deficit"] == 2
    assert gate["justified_removals"] == 0


def test_count_below_the_baseline_with_reviewed_replacement_coverage_passes(tmp_path: Path):
    docs = _write_release_docs(
        tmp_path,
        replacements=[
            _replacement_record("tests/test_example.py::test_first"),
            _replacement_record("tests/test_example.py::test_second"),
        ],
    )

    report = build_release_input_report(
        tmp_path,
        observed_passing_backend_tests=BASELINE_MINIMUM_PASSING_BACKEND_TESTS - 2,
        tracking_report=_tracking_report(),
        release_docs_root=docs,
    )

    assert report["status"] == "ready"
    assert _check(report, "backend_test_baseline")["justified_removals"] == 2


def test_replacement_coverage_must_account_for_the_whole_shortfall(tmp_path: Path):
    docs = _write_release_docs(tmp_path, replacements=[_replacement_record("tests/test_example.py::test_first")])

    report = build_release_input_report(
        tmp_path,
        observed_passing_backend_tests=BASELINE_MINIMUM_PASSING_BACKEND_TESTS - 3,
        tracking_report=_tracking_report(),
        release_docs_root=docs,
    )

    assert report["status"] == "not_ready"
    assert "backend_test_baseline:BACKEND_TEST_COUNT_BELOW_BASELINE" in report["blocking_reasons"]


def test_incomplete_replacement_record_justifies_nothing(tmp_path: Path):
    incomplete = _replacement_record("tests/test_example.py::test_first")
    del incomplete["retained_coverage"]
    docs = _write_release_docs(tmp_path, replacements=[incomplete])

    report = build_release_input_report(
        tmp_path,
        observed_passing_backend_tests=BASELINE_MINIMUM_PASSING_BACKEND_TESTS - 1,
        tracking_report=_tracking_report(),
        release_docs_root=docs,
    )

    assert report["status"] == "not_ready"
    assert "replacement_coverage:REPLACEMENT_FIELD_MISSING:retained_coverage" in report["blocking_reasons"]
    assert "backend_test_baseline:BACKEND_TEST_COUNT_BELOW_BASELINE" in report["blocking_reasons"]
    assert _check(report, "replacement_coverage")["accepted_removed_tests"] == []


def test_repeated_removed_test_identity_is_a_review_error(tmp_path: Path):
    duplicate = _replacement_record("tests/test_example.py::test_first")
    docs = _write_release_docs(tmp_path, replacements=[duplicate, dict(duplicate)])

    report = build_release_input_report(
        tmp_path,
        observed_passing_backend_tests=BASELINE_MINIMUM_PASSING_BACKEND_TESTS - 2,
        tracking_report=_tracking_report(),
        release_docs_root=docs,
    )

    assert report["status"] == "not_ready"
    assert "replacement_coverage:REPLACEMENT_RECORD_DUPLICATE:1" in report["blocking_reasons"]


@pytest.mark.parametrize("observed", [-1, True, "601", 2.0])
def test_invalid_observed_test_count_fails_closed(tmp_path: Path, observed: Any):
    docs = _write_release_docs(tmp_path)

    report = build_release_input_report(
        tmp_path,
        observed_passing_backend_tests=observed,
        tracking_report=_tracking_report(),
        release_docs_root=docs,
    )

    assert report["status"] == "not_ready"
    assert "backend_test_baseline:BACKEND_TEST_COUNT_INVALID" in report["blocking_reasons"]


# ---------------------------------------------------------------------------
# Evidence document handling
# ---------------------------------------------------------------------------


def test_baseline_record_claiming_a_weaker_baseline_is_rejected(tmp_path: Path):
    weak = dict(BASELINE_RECORD, baseline_passing_backend_tests=100)
    docs = _write_release_docs(tmp_path, baseline=weak)

    report = build_release_input_report(
        tmp_path,
        observed_passing_backend_tests=200,
        tracking_report=_tracking_report(),
        release_docs_root=docs,
    )

    assert report["status"] == "not_ready"
    assert "baseline_evidence:BASELINE_TEST_COUNT_BELOW_APPROVED_MINIMUM" in report["blocking_reasons"]
    # The approved minimum still gates the count, so a weak record cannot lower it.
    assert _check(report, "backend_test_baseline")["baseline"] == BASELINE_MINIMUM_PASSING_BACKEND_TESTS
    assert "backend_test_baseline:BACKEND_TEST_COUNT_BELOW_BASELINE" in report["blocking_reasons"]


@pytest.mark.parametrize(
    ("baseline_override", "expected_reason"),
    [
        ({"frontend_typecheck": "fail"}, "BASELINE_FRONTEND_TYPECHECK_NOT_PASSING"),
        ({"frontend_production_build": "fail"}, "BASELINE_FRONTEND_BUILD_NOT_PASSING"),
        ({"repository_revision": "not-a-revision"}, "BASELINE_REPOSITORY_REVISION_INVALID"),
        ({"recorded_at": "yesterday"}, "BASELINE_RECORDED_AT_INVALID"),
        ({"schema_version": 99}, "BASELINE_SCHEMA_VERSION_UNSUPPORTED"),
    ],
)
def test_invalid_baseline_record_blocks_the_release_inputs(
    tmp_path: Path, baseline_override: dict[str, Any], expected_reason: str
):
    docs = _write_release_docs(tmp_path, baseline=dict(BASELINE_RECORD, **baseline_override))

    report = build_release_input_report(
        tmp_path,
        observed_passing_backend_tests=601,
        tracking_report=_tracking_report(),
        release_docs_root=docs,
    )

    assert report["status"] == "not_ready"
    assert f"baseline_evidence:{expected_reason}" in report["blocking_reasons"]


def test_missing_evidence_documents_fail_closed(tmp_path: Path):
    report = build_release_input_report(
        tmp_path,
        observed_passing_backend_tests=601,
        tracking_report=_tracking_report(),
        release_docs_root=tmp_path / "docs" / "release",
    )

    assert report["status"] == "not_ready"
    assert "baseline_evidence:BASELINE_DOCUMENT:DOCUMENT_MISSING" in report["blocking_reasons"]
    assert "replacement_coverage:REPLACEMENT_DOCUMENT:DOCUMENT_MISSING" in report["blocking_reasons"]
    assert "cleanup_inventory:INVENTORY_DOCUMENT:DOCUMENT_MISSING" in report["blocking_reasons"]


def test_unsupported_cleanup_proposal_blocks_the_release_inputs(tmp_path: Path):
    unsupported = {
        "candidate": "app/api/routes/gateway.py",
        "category": "FILE",
        "references_searched": [
            {"reference_type": "HTTP_ROUTE", "query": "router inclusion", "result": "FOUND"},
        ],
        "public_contract_status": "PUBLIC_HTTP_CONTRACT",
        "protected_capability_status": "PROTECTED_CAPABILITY_DEPENDENCY",
        "test_coverage": ["tests/test_razorpay_gateway.py"],
        "proposed_disposition": "ELIGIBLE_FOR_REMOVAL_REVIEW",
        "reviewer": "release reviewer",
        "reviewed_at": "2026-09-02",
        "evidence_gaps": [],
    }
    docs = _write_release_docs(tmp_path, inventory=[unsupported])

    report = build_release_input_report(
        tmp_path,
        observed_passing_backend_tests=601,
        tracking_report=_tracking_report(),
        release_docs_root=docs,
    )
    inventory = report["cleanup_inventory"]

    assert report["status"] == "not_ready"
    assert "cleanup_inventory:INVENTORY_DISPOSITION_CONFLICT:0" in report["blocking_reasons"]
    assert inventory["records"][0]["classification"] == "RETAINED"
    assert "PUBLIC_CONTRACT_REFERENCE" in inventory["records"][0]["retention_reasons"]


# ---------------------------------------------------------------------------
# Report safety
# ---------------------------------------------------------------------------


def test_report_is_deterministic_non_mutating_and_path_safe(tmp_path: Path):
    docs = _write_release_docs(tmp_path)
    before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(docs.rglob("*")) if path.is_file()
    }

    first = build_release_input_report(
        tmp_path,
        observed_passing_backend_tests=601,
        tracking_report=_tracking_report(),
        release_docs_root=docs,
    )
    second = build_release_input_report(
        tmp_path,
        observed_passing_backend_tests=601,
        tracking_report=_tracking_report(),
        release_docs_root=docs,
    )
    after = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(docs.rglob("*")) if path.is_file()
    }

    assert first == second
    assert before == after
    assert str(tmp_path) not in json.dumps(first)
