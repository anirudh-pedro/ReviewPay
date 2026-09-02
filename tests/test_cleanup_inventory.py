"""Focused coverage for the fail-closed Cleanup Inventory contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.cleanup_inventory import (
    CANDIDATE_CATEGORIES,
    DEPENDENCY_PATH_SCOPES,
    DISPOSITIONS,
    ELIGIBLE_FOR_REMOVAL_REVIEW,
    INVENTORY_MARKER,
    PROTECTED_CAPABILITY_STATUSES,
    PUBLIC_CONTRACT_STATUSES,
    RECORD_OPTIONAL_FIELDS,
    RECORD_REQUIRED_FIELDS,
    REFERENCE_OPTIONAL_FIELDS,
    REFERENCE_REQUIRED_FIELDS,
    REFERENCE_RESULTS,
    REMOVAL_JUSTIFICATIONS,
    REQUIRED_REFERENCE_TYPES,
    RETAINED,
    classify_candidate,
    validate_inventory,
    validate_inventory_document,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RELEASE_DOCS = REPOSITORY_ROOT / "docs" / "release"


def _searches(**results: str) -> list[dict[str, Any]]:
    """Return one recorded search per required reference class.

    Every class defaults to ``NONE_FOUND`` so a test only states the evidence it
    is actually about.
    """

    return [
        {
            "reference_type": reference_type,
            "query": f"repository search for {reference_type.lower()} references",
            "result": results.get(reference_type, "NONE_FOUND"),
        }
        for reference_type in REQUIRED_REFERENCE_TYPES
    ]


def _record(**overrides: Any) -> dict[str, Any]:
    """A complete record whose evidence supports removal review."""

    record: dict[str, Any] = {
        "candidate": "app/example/unused_module.py",
        "category": "FILE",
        "references_searched": _searches(),
        "public_contract_status": "NONE",
        "protected_capability_status": "NONE",
        "test_coverage": [],
        "removal_justification": ["NO_REFERENCE_FOUND"],
        "proposed_disposition": ELIGIBLE_FOR_REMOVAL_REVIEW,
        "reviewer": "release reviewer",
        "reviewed_at": "2026-09-02",
        "evidence_gaps": [],
    }
    record.update(overrides)
    return record


def test_complete_evidence_with_no_reference_is_eligible_for_removal_review():
    result = classify_candidate(_record())

    assert result["classification"] == ELIGIBLE_FOR_REMOVAL_REVIEW
    assert result["retention_reasons"] == []
    assert result["incomplete_evidence"] == []
    assert result["disposition_conflict"] is False


@pytest.mark.parametrize("reference_type", REQUIRED_REFERENCE_TYPES)
def test_any_present_reference_retains_the_candidate(reference_type: str):
    result = classify_candidate(_record(references_searched=_searches(**{reference_type: "FOUND"})))

    assert result["classification"] == RETAINED
    assert f"REFERENCE_PRESENT:{reference_type}" in result["retention_reasons"]


@pytest.mark.parametrize("reference_type", REQUIRED_REFERENCE_TYPES)
def test_unsearched_reference_class_retains_the_candidate(reference_type: str):
    searches = [entry for entry in _searches() if entry["reference_type"] != reference_type]

    result = classify_candidate(_record(references_searched=searches))

    assert result["classification"] == RETAINED
    assert f"REFERENCE_SEARCH_MISSING:{reference_type}" in result["retention_reasons"]
    assert f"REFERENCE_SEARCH_MISSING:{reference_type}" in result["incomplete_evidence"]


@pytest.mark.parametrize(
    ("result_value", "expected_reason"),
    [("UNREADABLE", "EVIDENCE_UNREADABLE:TEST"), ("INCONCLUSIVE", "EVIDENCE_INCONCLUSIVE:TEST")],
)
def test_unreadable_or_inconclusive_evidence_retains_the_candidate(result_value: str, expected_reason: str):
    result = classify_candidate(_record(references_searched=_searches(TEST=result_value)))

    assert result["classification"] == RETAINED
    assert expected_reason in result["retention_reasons"]
    assert expected_reason in result["incomplete_evidence"]


def test_contradictory_results_for_one_reference_class_retain_the_candidate():
    searches = _searches()
    searches.append(
        {
            "reference_type": "RUNTIME_IMPORT",
            "query": "second import search",
            "result": "FOUND",
        }
    )

    result = classify_candidate(_record(references_searched=searches))

    # The most severe recorded outcome wins, so a contradiction cannot be
    # resolved in favour of removal.
    assert result["classification"] == RETAINED
    assert "REFERENCE_PRESENT:RUNTIME_IMPORT" in result["retention_reasons"]


def test_reported_locations_without_a_reference_are_conflicting_evidence():
    searches = _searches()
    searches[0]["locations"] = ["app/main.py:12"]

    result = classify_candidate(_record(references_searched=searches))

    assert result["classification"] == RETAINED
    assert "CONFLICTING_EVIDENCE:REFERENCE_LOCATIONS_WITHOUT_REFERENCE" in result["incomplete_evidence"]


def test_test_coverage_without_a_test_reference_is_conflicting_evidence():
    result = classify_candidate(_record(test_coverage=["tests/test_example.py::test_case"]))

    assert result["classification"] == RETAINED
    assert "CONFLICTING_EVIDENCE:TEST_COVERAGE_WITHOUT_TEST_REFERENCE" in result["incomplete_evidence"]


def test_recorded_evidence_gap_retains_the_candidate():
    result = classify_candidate(_record(evidence_gaps=["frontend import graph not searched"]))

    assert result["classification"] == RETAINED
    assert "EVIDENCE_GAP_RECORDED" in result["incomplete_evidence"]


@pytest.mark.parametrize(
    ("field", "value", "expected_reason"),
    [
        ("public_contract_status", "PUBLIC_HTTP_CONTRACT", "PUBLIC_CONTRACT_REFERENCE"),
        ("public_contract_status", "UNKNOWN", "PUBLIC_CONTRACT_STATUS_UNKNOWN"),
        ("protected_capability_status", "PROTECTED_CAPABILITY_DEPENDENCY", "PROTECTED_CAPABILITY_DEPENDENCY"),
        ("protected_capability_status", "UNKNOWN", "PROTECTED_CAPABILITY_STATUS_UNKNOWN"),
    ],
)
def test_contract_and_protected_capability_status_retain_the_candidate(
    field: str, value: str, expected_reason: str
):
    result = classify_candidate(_record(**{field: value}))

    assert result["classification"] == RETAINED
    assert expected_reason in result["retention_reasons"]


def test_navigation_absence_alone_never_justifies_removal():
    result = classify_candidate(_record(removal_justification=["NAVIGATION_NOT_EXPOSED"]))

    assert result["classification"] == RETAINED
    assert "NAVIGATION_ONLY_JUSTIFICATION" in result["retention_reasons"]


def test_navigation_absence_with_a_reference_based_justification_stays_eligible():
    result = classify_candidate(
        _record(removal_justification=["NAVIGATION_NOT_EXPOSED", "NO_REFERENCE_FOUND"])
    )

    assert result["classification"] == ELIGIBLE_FOR_REMOVAL_REVIEW


@pytest.mark.parametrize("omitted_scope", DEPENDENCY_PATH_SCOPES)
def test_dependency_requires_every_supported_path_scope(omitted_scope: str):
    checked = [scope for scope in DEPENDENCY_PATH_SCOPES if scope != omitted_scope]

    result = classify_candidate(
        _record(
            candidate="requirements.txt::example-package",
            category="DEPENDENCY",
            dependency_path_scopes_checked=checked,
            removal_justification=["UNUSED_DEPENDENCY"],
        )
    )

    assert result["classification"] == RETAINED
    assert f"DEPENDENCY_PATH_SCOPE_UNCHECKED:{omitted_scope}" in result["retention_reasons"]


def test_dependency_with_every_path_scope_checked_is_eligible():
    result = classify_candidate(
        _record(
            candidate="requirements.txt::example-package",
            category="DEPENDENCY",
            dependency_path_scopes_checked=list(DEPENDENCY_PATH_SCOPES),
            removal_justification=["UNUSED_DEPENDENCY"],
        )
    )

    assert result["classification"] == ELIGIBLE_FOR_REMOVAL_REVIEW


@pytest.mark.parametrize(
    ("field", "value"),
    [("reviewer", ""), ("reviewer", None), ("reviewed_at", "not-a-date")],
)
def test_missing_reviewer_evidence_retains_the_candidate(field: str, value: Any):
    result = classify_candidate(_record(**{field: value}))

    assert result["classification"] == RETAINED
    assert "MISSING_REVIEWER_EVIDENCE" in result["incomplete_evidence"]


@pytest.mark.parametrize(
    "record",
    [
        "not-an-object",
        {"candidate": "app/example.py"},
        _record(unexpected_field="value"),
        _record(category="MYSTERY"),
        _record(references_searched="not-a-list"),
        _record(references_searched=[{"reference_type": "RUNTIME_IMPORT", "result": "NONE_FOUND"}]),
    ],
)
def test_invalid_record_is_retained_and_reported(record: Any):
    result = classify_candidate(record)

    assert result["classification"] == RETAINED
    assert result["record_errors"]
    assert "RECORD_EVIDENCE_INVALID" in result["incomplete_evidence"]


def test_inventory_reports_a_proposal_the_evidence_does_not_support():
    unsupported = _record(
        candidate="app/example/still_referenced.py",
        references_searched=_searches(HTTP_ROUTE="FOUND"),
        proposed_disposition=ELIGIBLE_FOR_REMOVAL_REVIEW,
    )

    result = validate_inventory([unsupported])

    assert result["status"] == "fail"
    assert "INVENTORY_DISPOSITION_CONFLICT:0" in result["errors"]
    assert result["summary"] == {
        "candidates": 1,
        "disposition_conflicts": 1,
        "eligible": 0,
        "records_with_errors": 0,
        "retained": 1,
    }


def test_retained_proposal_for_retained_evidence_is_not_a_failure():
    conservative = _record(
        references_searched=_searches(TEST="FOUND"),
        test_coverage=["tests/test_example.py::test_case"],
        proposed_disposition=RETAINED,
        removal_justification=[],
    )

    result = validate_inventory([conservative])

    assert result["status"] == "pass"
    assert result["summary"]["retained"] == 1


def test_duplicate_candidate_identity_fails_the_inventory():
    result = validate_inventory([_record(), _record()])

    assert result["status"] == "fail"
    assert "INVENTORY_DUPLICATE_CANDIDATE:1" in result["errors"]


def test_non_array_inventory_fails_closed():
    result = validate_inventory({"candidate": "app/example.py"})

    assert result["status"] == "fail"
    assert result["errors"] == ["INVENTORY_RECORDS_NOT_ARRAY"]


def test_empty_inventory_is_valid():
    result = validate_inventory([])

    assert result["status"] == "pass"
    assert result["summary"]["candidates"] == 0


def test_reviewed_repository_inventory_document_validates():
    result = validate_inventory_document(RELEASE_DOCS / "cleanup-inventory.md")

    assert result["status"] == "pass"
    assert result["summary"]["disposition_conflicts"] == 0


@pytest.mark.parametrize(
    ("content", "expected_error"),
    [
        ("# No marker here\n", "INVENTORY_DOCUMENT:MARKER_MISSING"),
        (f"<!-- {INVENTORY_MARKER} -->\n\nno fenced block\n", "INVENTORY_DOCUMENT:RECORD_BLOCK_MISSING"),
        (f"<!-- {INVENTORY_MARKER} -->\n\n```json\n[oops\n```\n", "INVENTORY_DOCUMENT:RECORD_INVALID_JSON"),
        (f"<!-- {INVENTORY_MARKER} -->\n\n```text\n[]\n```\n", "INVENTORY_DOCUMENT:RECORD_BLOCK_NOT_JSON"),
    ],
)
def test_unusable_inventory_document_fails_closed(tmp_path: Path, content: str, expected_error: str):
    document = tmp_path / "cleanup-inventory.md"
    document.write_text(content, encoding="utf-8")

    result = validate_inventory_document(document)

    assert result["status"] == "fail"
    assert result["errors"] == [expected_error]


def test_missing_inventory_document_fails_closed(tmp_path: Path):
    result = validate_inventory_document(tmp_path / "absent.md")

    assert result["status"] == "fail"
    assert result["errors"] == ["INVENTORY_DOCUMENT:DOCUMENT_MISSING"]


def test_schema_companion_matches_the_validator_contract():
    schema = json.loads((RELEASE_DOCS / "cleanup-inventory.schema.json").read_text(encoding="utf-8"))
    candidate = schema["$defs"]["candidate"]
    reference = schema["$defs"]["reference_search"]
    properties = candidate["properties"]

    assert candidate["required"] == sorted(RECORD_REQUIRED_FIELDS)
    assert set(properties) == set(RECORD_REQUIRED_FIELDS) | set(RECORD_OPTIONAL_FIELDS)
    assert candidate["additionalProperties"] is False
    assert set(properties["category"]["enum"]) == set(CANDIDATE_CATEGORIES)
    assert set(properties["public_contract_status"]["enum"]) == set(PUBLIC_CONTRACT_STATUSES)
    assert set(properties["protected_capability_status"]["enum"]) == set(PROTECTED_CAPABILITY_STATUSES)
    assert set(properties["proposed_disposition"]["enum"]) == set(DISPOSITIONS)
    assert set(properties["dependency_path_scopes_checked"]["items"]["enum"]) == set(DEPENDENCY_PATH_SCOPES)
    assert set(properties["removal_justification"]["items"]["enum"]) == set(REMOVAL_JUSTIFICATIONS)

    assert reference["required"] == sorted(REFERENCE_REQUIRED_FIELDS)
    assert set(reference["properties"]) == set(REFERENCE_REQUIRED_FIELDS) | set(REFERENCE_OPTIONAL_FIELDS)
    assert reference["additionalProperties"] is False
    assert set(reference["properties"]["reference_type"]["enum"]) == set(REQUIRED_REFERENCE_TYPES)
    assert set(reference["properties"]["result"]["enum"]) == set(REFERENCE_RESULTS)
