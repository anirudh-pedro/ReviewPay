"""Schema, validator, and fail-closed classifier for the Cleanup Inventory.

The reviewed inventory lives in
[`docs/release/cleanup-inventory.md`](../docs/release/cleanup-inventory.md) as
fenced JSON after a marker comment, with
[`docs/release/cleanup-inventory.schema.json`](../docs/release/cleanup-inventory.schema.json)
as its machine-readable companion. This module is the executable authority for
the same contract: it validates each record and derives the candidate's
classification from the recorded evidence instead of trusting the proposed
disposition.

Classification fails closed. A candidate is eligible for removal review only
when every required reference search was performed and found nothing, the
candidate carries no public HTTP contract or Protected Capability relationship,
and no evidence gap, unreadable search, or conflicting record remains. Anything
else is retained with the reason recorded (Requirements 2.1-2.4, 2.6, 2.7).

This module only reads files. It removes nothing; approved removals happen later
under task 10.1 with this validated inventory as their input.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from scripts.release_evidence import (
    EvidenceDocumentError,
    is_iso_timestamp,
    is_non_empty_string,
    is_string_list,
    load_embedded_json,
)


SCHEMA_VERSION = 1
INVENTORY_MARKER = "revivepay:cleanup-inventory"

RETAINED = "RETAINED"
ELIGIBLE_FOR_REMOVAL_REVIEW = "ELIGIBLE_FOR_REMOVAL_REVIEW"
DISPOSITIONS = (ELIGIBLE_FOR_REMOVAL_REVIEW, RETAINED)

#: Cleanup candidate categories recorded by the inventory (Requirement 2.1).
CANDIDATE_CATEGORIES = (
    "ASSET",
    "CONFIGURATION_ENTRY",
    "DEPENDENCY",
    "FILE",
    "ROUTE",
    "SYMBOL",
)

#: Every reference class that must be searched before a candidate can be
#: eligible for removal review (Requirements 2.2, 2.3).
REQUIRED_REFERENCE_TYPES = (
    "CONFIGURATION",
    "DOCUMENTATION_COMMAND",
    "HTTP_ROUTE",
    "MIGRATION",
    "RUNTIME_IMPORT",
    "STATIC_ASSET",
    "SUPPORTED_RUNTIME",
    "TEMPLATE",
    "TEST",
)

#: Search outcomes ordered from most to least severe. When one reference type is
#: searched more than once, the most severe outcome wins, so a contradictory pair
#: such as FOUND and NONE_FOUND retains the candidate.
REFERENCE_RESULTS = ("FOUND", "UNREADABLE", "INCONCLUSIVE", "NONE_FOUND")

PUBLIC_CONTRACT_STATUSES = ("NONE", "PUBLIC_HTTP_CONTRACT", "UNKNOWN")
PROTECTED_CAPABILITY_STATUSES = ("NONE", "PROTECTED_CAPABILITY_DEPENDENCY", "UNKNOWN")

#: Dependency removal additionally requires proof of absence from every
#: supported path (Requirement 2.7).
DEPENDENCY_PATH_SCOPES = ("BUILD", "MIGRATION", "RUNTIME", "TEST")

#: Reasons a reviewer may offer for a removal. Navigation absence alone never
#: justifies removing a capability (Requirement 2.6).
REMOVAL_JUSTIFICATIONS = (
    "NAVIGATION_NOT_EXPOSED",
    "NO_REFERENCE_FOUND",
    "REPLACED_BY_APPROVED_CHANGE",
    "UNUSED_DEPENDENCY",
)
NAVIGATION_ONLY_JUSTIFICATION = "NAVIGATION_NOT_EXPOSED"

RECORD_REQUIRED_FIELDS = (
    "candidate",
    "category",
    "evidence_gaps",
    "proposed_disposition",
    "protected_capability_status",
    "public_contract_status",
    "references_searched",
    "reviewed_at",
    "reviewer",
    "test_coverage",
)
RECORD_OPTIONAL_FIELDS = (
    "dependency_path_scopes_checked",
    "notes",
    "removal_justification",
)
REFERENCE_REQUIRED_FIELDS = ("query", "reference_type", "result")
REFERENCE_OPTIONAL_FIELDS = ("locations", "notes")

#: Retention reasons that describe missing, unreadable, or contradictory
#: evidence rather than a live reference (Requirement 2.4).
_INCOMPLETE_EVIDENCE_PREFIXES = (
    "CONFLICTING_EVIDENCE",
    "DEPENDENCY_PATH_SCOPE_UNCHECKED",
    "EVIDENCE_GAP_RECORDED",
    "EVIDENCE_INCONCLUSIVE",
    "EVIDENCE_UNREADABLE",
    "MISSING_REVIEWER_EVIDENCE",
    "PROTECTED_CAPABILITY_STATUS_UNKNOWN",
    "PUBLIC_CONTRACT_STATUS_UNKNOWN",
    "RECORD_EVIDENCE_INVALID",
    "REFERENCE_SEARCH_MISSING",
)


def load_inventory_document(path: Path | str) -> Any:
    """Return the reviewed inventory records embedded in ``path``."""

    return load_embedded_json(path, marker=INVENTORY_MARKER)


def validate_reference_entry(entry: Any) -> list[str]:
    """Return sorted error codes for one recorded reference search."""

    if not isinstance(entry, dict):
        return ["REFERENCE_ENTRY_NOT_OBJECT"]

    errors = [f"REFERENCE_FIELD_MISSING:{name}" for name in REFERENCE_REQUIRED_FIELDS if name not in entry]
    allowed = set(REFERENCE_REQUIRED_FIELDS) | set(REFERENCE_OPTIONAL_FIELDS)
    errors.extend(f"REFERENCE_FIELD_UNKNOWN:{name}" for name in sorted(set(entry) - allowed))

    if "reference_type" in entry and entry["reference_type"] not in REQUIRED_REFERENCE_TYPES:
        errors.append("REFERENCE_TYPE_INVALID")
    if "result" in entry and entry["result"] not in REFERENCE_RESULTS:
        errors.append("REFERENCE_RESULT_INVALID")
    if "query" in entry and not is_non_empty_string(entry["query"]):
        errors.append("REFERENCE_QUERY_INVALID")
    if "locations" in entry and not is_string_list(entry["locations"], allow_empty=True):
        errors.append("REFERENCE_LOCATIONS_INVALID")
    if "notes" in entry and not is_string_list(entry["notes"], allow_empty=True):
        errors.append("REFERENCE_NOTES_INVALID")

    return sorted(set(errors))


def validate_record(record: Any) -> list[str]:
    """Return sorted error codes for one cleanup inventory record."""

    if not isinstance(record, dict):
        return ["RECORD_NOT_OBJECT"]

    errors = [f"RECORD_FIELD_MISSING:{name}" for name in RECORD_REQUIRED_FIELDS if name not in record]
    allowed = set(RECORD_REQUIRED_FIELDS) | set(RECORD_OPTIONAL_FIELDS)
    errors.extend(f"RECORD_FIELD_UNKNOWN:{name}" for name in sorted(set(record) - allowed))

    if "candidate" in record and not is_non_empty_string(record["candidate"]):
        errors.append("RECORD_CANDIDATE_INVALID")
    if "category" in record and record["category"] not in CANDIDATE_CATEGORIES:
        errors.append("RECORD_CATEGORY_INVALID")
    if "public_contract_status" in record and record["public_contract_status"] not in PUBLIC_CONTRACT_STATUSES:
        errors.append("RECORD_PUBLIC_CONTRACT_STATUS_INVALID")
    if (
        "protected_capability_status" in record
        and record["protected_capability_status"] not in PROTECTED_CAPABILITY_STATUSES
    ):
        errors.append("RECORD_PROTECTED_CAPABILITY_STATUS_INVALID")
    if "proposed_disposition" in record and record["proposed_disposition"] not in DISPOSITIONS:
        errors.append("RECORD_DISPOSITION_INVALID")
    if "test_coverage" in record and not is_string_list(record["test_coverage"], allow_empty=True):
        errors.append("RECORD_TEST_COVERAGE_INVALID")
    if "evidence_gaps" in record and not is_string_list(record["evidence_gaps"], allow_empty=True):
        errors.append("RECORD_EVIDENCE_GAPS_INVALID")
    if "notes" in record and not is_string_list(record["notes"], allow_empty=True):
        errors.append("RECORD_NOTES_INVALID")
    if "reviewer" in record and not is_non_empty_string(record["reviewer"]):
        errors.append("RECORD_REVIEWER_INVALID")
    if "reviewed_at" in record and not is_iso_timestamp(record["reviewed_at"]):
        errors.append("RECORD_REVIEWED_AT_INVALID")

    if "references_searched" in record:
        references = record["references_searched"]
        if not isinstance(references, list):
            errors.append("RECORD_REFERENCES_NOT_ARRAY")
        else:
            for entry in references:
                errors.extend(validate_reference_entry(entry))

    if "dependency_path_scopes_checked" in record:
        scopes = record["dependency_path_scopes_checked"]
        if not isinstance(scopes, list) or any(scope not in DEPENDENCY_PATH_SCOPES for scope in scopes):
            errors.append("RECORD_DEPENDENCY_PATH_SCOPES_INVALID")

    if "removal_justification" in record:
        justification = record["removal_justification"]
        if not isinstance(justification, list) or any(
            reason not in REMOVAL_JUSTIFICATIONS for reason in justification
        ):
            errors.append("RECORD_REMOVAL_JUSTIFICATION_INVALID")

    return sorted(set(errors))


def _effective_reference_results(references: Any) -> dict[str, str]:
    """Return the most severe recorded outcome for each searched reference type."""

    severity = {result: index for index, result in enumerate(REFERENCE_RESULTS)}
    effective: dict[str, str] = {}
    if not isinstance(references, list):
        return effective
    for entry in references:
        if not isinstance(entry, dict):
            continue
        reference_type = entry.get("reference_type")
        result = entry.get("result")
        if reference_type not in REQUIRED_REFERENCE_TYPES or result not in severity:
            continue
        current = effective.get(reference_type)
        if current is None or severity[result] < severity[current]:
            effective[reference_type] = result
    return effective


def _conflict_reasons(record: dict[str, Any], effective: dict[str, str]) -> list[str]:
    """Return contradictions between the record's own fields.

    A search that reports no reference while listing locations, or a candidate
    that claims no test reference while recording test coverage, is conflicting
    evidence and retains the candidate.
    """

    reasons: list[str] = []
    references = record.get("references_searched")
    if isinstance(references, list):
        for entry in references:
            if not isinstance(entry, dict):
                continue
            if entry.get("result") == "NONE_FOUND" and entry.get("locations"):
                reasons.append("CONFLICTING_EVIDENCE:REFERENCE_LOCATIONS_WITHOUT_REFERENCE")
    if record.get("test_coverage") and effective.get("TEST") == "NONE_FOUND":
        reasons.append("CONFLICTING_EVIDENCE:TEST_COVERAGE_WITHOUT_TEST_REFERENCE")
    return reasons


def classify_candidate(record: Any, *, index: int | None = None) -> dict[str, Any]:
    """Classify one cleanup candidate from its recorded evidence.

    The returned ``classification`` is derived, never copied from
    ``proposed_disposition``; ``disposition_conflict`` reports a proposal that
    the evidence does not support.
    """

    record_errors = validate_record(record)
    is_object = isinstance(record, dict)
    candidate = record.get("candidate") if is_object else None
    category = record.get("category") if is_object else None
    declared = record.get("proposed_disposition") if is_object else None

    reasons: list[str] = []
    if record_errors:
        reasons.append("RECORD_EVIDENCE_INVALID")

    if is_object:
        effective = _effective_reference_results(record.get("references_searched"))
        for reference_type in REQUIRED_REFERENCE_TYPES:
            result = effective.get(reference_type)
            if result is None:
                reasons.append(f"REFERENCE_SEARCH_MISSING:{reference_type}")
            elif result == "FOUND":
                reasons.append(f"REFERENCE_PRESENT:{reference_type}")
            elif result == "UNREADABLE":
                reasons.append(f"EVIDENCE_UNREADABLE:{reference_type}")
            elif result == "INCONCLUSIVE":
                reasons.append(f"EVIDENCE_INCONCLUSIVE:{reference_type}")

        public_contract = record.get("public_contract_status")
        if public_contract == "PUBLIC_HTTP_CONTRACT":
            reasons.append("PUBLIC_CONTRACT_REFERENCE")
        elif public_contract != "NONE":
            reasons.append("PUBLIC_CONTRACT_STATUS_UNKNOWN")

        protected = record.get("protected_capability_status")
        if protected == "PROTECTED_CAPABILITY_DEPENDENCY":
            reasons.append("PROTECTED_CAPABILITY_DEPENDENCY")
        elif protected != "NONE":
            reasons.append("PROTECTED_CAPABILITY_STATUS_UNKNOWN")

        if record.get("evidence_gaps"):
            reasons.append("EVIDENCE_GAP_RECORDED")

        if not is_non_empty_string(record.get("reviewer")) or not is_iso_timestamp(record.get("reviewed_at")):
            reasons.append("MISSING_REVIEWER_EVIDENCE")

        if category == "DEPENDENCY":
            checked = record.get("dependency_path_scopes_checked")
            checked_scopes = set(checked) if isinstance(checked, list) else set()
            for scope in DEPENDENCY_PATH_SCOPES:
                if scope not in checked_scopes:
                    reasons.append(f"DEPENDENCY_PATH_SCOPE_UNCHECKED:{scope}")

        justification = record.get("removal_justification")
        if isinstance(justification, list) and justification and set(justification) == {
            NAVIGATION_ONLY_JUSTIFICATION
        }:
            reasons.append("NAVIGATION_ONLY_JUSTIFICATION")

        reasons.extend(_conflict_reasons(record, effective))

    retention_reasons = sorted(set(reasons))
    classification = RETAINED if retention_reasons else ELIGIBLE_FOR_REMOVAL_REVIEW
    incomplete_evidence = [
        reason for reason in retention_reasons if reason.split(":", 1)[0] in _INCOMPLETE_EVIDENCE_PREFIXES
    ]

    return {
        "candidate": candidate if isinstance(candidate, str) else None,
        "category": category if category in CANDIDATE_CATEGORIES else None,
        "classification": classification,
        "declared_disposition": declared if declared in DISPOSITIONS else None,
        "disposition_conflict": declared == ELIGIBLE_FOR_REMOVAL_REVIEW and classification == RETAINED,
        "incomplete_evidence": incomplete_evidence,
        "index": index,
        "record_errors": record_errors,
        "retention_reasons": retention_reasons,
    }


def validate_inventory(records: Any) -> dict[str, Any]:
    """Validate and classify the whole reviewed inventory.

    ``status`` is ``fail`` when a record is invalid, a candidate identity repeats,
    or a proposed removal is not supported by its evidence. A retained candidate
    is a safe outcome and does not fail the inventory.
    """

    if not isinstance(records, list):
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "fail",
            "summary": {
                "candidates": 0,
                "disposition_conflicts": 0,
                "eligible": 0,
                "records_with_errors": 0,
                "retained": 0,
            },
            "records": [],
            "errors": ["INVENTORY_RECORDS_NOT_ARRAY"],
        }

    classified = [classify_candidate(record, index=index) for index, record in enumerate(records)]
    errors: list[str] = []
    seen: dict[str, int] = {}

    for item in classified:
        if item["record_errors"]:
            errors.append(f"INVENTORY_RECORD_INVALID:{item['index']}")
            errors.extend(item["record_errors"])
        if item["disposition_conflict"]:
            errors.append(f"INVENTORY_DISPOSITION_CONFLICT:{item['index']}")
        candidate = item["candidate"]
        if candidate is None:
            continue
        if candidate in seen:
            errors.append(f"INVENTORY_DUPLICATE_CANDIDATE:{item['index']}")
        else:
            seen[candidate] = item["index"]

    eligible = sum(item["classification"] == ELIGIBLE_FOR_REMOVAL_REVIEW for item in classified)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "fail" if errors else "pass",
        "summary": {
            "candidates": len(classified),
            "disposition_conflicts": sum(bool(item["disposition_conflict"]) for item in classified),
            "eligible": eligible,
            "records_with_errors": sum(bool(item["record_errors"]) for item in classified),
            "retained": len(classified) - eligible,
        },
        "records": classified,
        "errors": sorted(set(errors)),
    }


def validate_inventory_document(path: Path | str) -> dict[str, Any]:
    """Load and validate the reviewed inventory document at ``path``."""

    try:
        records = load_inventory_document(path)
    except EvidenceDocumentError as error:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "fail",
            "summary": {
                "candidates": 0,
                "disposition_conflicts": 0,
                "eligible": 0,
                "records_with_errors": 0,
                "retained": 0,
            },
            "records": [],
            "errors": [f"INVENTORY_DOCUMENT:{error.code}"],
        }
    return validate_inventory(records)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the reviewed Cleanup Inventory document.")
    parser.add_argument(
        "--document",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docs" / "release" / "cleanup-inventory.md",
        help="path to the reviewed cleanup inventory document",
    )
    args = parser.parse_args(argv)
    result = validate_inventory_document(args.document)
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
