"""Non-mutating release-input report for the production-readiness release gate.

The report answers one question: are the *inputs* a release record depends on
complete and passing? It consumes

* the Source Tracking Guard report from
  [`scripts/source_tracking_guard.py`](source_tracking_guard.py) (reused as-is;
  discovery logic is not duplicated here),
* the reviewed baseline evidence and replacement-coverage records from
  [`docs/release/baseline-evidence.md`](../docs/release/baseline-evidence.md), and
* the reviewed Cleanup Inventory from
  [`docs/release/cleanup-inventory.md`](../docs/release/cleanup-inventory.md).

``status`` is ``ready`` only when every mandatory input check passes, so a missing
input is never silently treated as a pass. The report is a pure function of its
inputs: it reads repository files and Git metadata, writes nothing, deletes
nothing, and contains no timestamp, absolute path, or configuration value that
would make retained evidence unstable or unsafe (Requirements 17.1, 17.2, 17.5,
17.7).

The full release record, including the executed test/build commands and the
validation timestamp, is produced later by ``scripts/release_validate.py``
(task 11.2). This module supplies that record's preconditions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from scripts import source_tracking_guard
from scripts.cleanup_inventory import validate_inventory_document
from scripts.release_evidence import (
    BASELINE_MINIMUM_PASSING_BACKEND_TESTS,
    REQUIRED_RELEASE_CAVEATS,
    EvidenceDocumentError,
    is_count,
    load_baseline_evidence,
    load_replacement_coverage,
    summarize_replacement_coverage,
    validate_baseline_evidence,
)


SCHEMA_VERSION = 1

BASELINE_DOCUMENT_NAME = "baseline-evidence.md"
INVENTORY_DOCUMENT_NAME = "cleanup-inventory.md"

#: Every mandatory release-input check, in report order. All of them must pass
#: before the release-input status can be ``ready``.
MANDATORY_CHECKS = (
    "source_tracking",
    "baseline_evidence",
    "replacement_coverage",
    "cleanup_inventory",
    "backend_test_baseline",
)

#: Failing source-tracking findings are reported in full up to this bound so a
#: retained report stays a reviewable size on a badly untracked checkout.
MAX_REPORTED_TRACKING_FINDINGS = 50


def _check(name: str, status: str, **details: Any) -> dict[str, Any]:
    return {"name": name, "mandatory": name in MANDATORY_CHECKS, "status": status, **details}


def _source_tracking_check(report: Any) -> dict[str, Any]:
    """Convert a Source Tracking Guard report into a release-input check."""

    if not isinstance(report, dict):
        return _check("source_tracking", "fail", reasons=["TRACKING_REPORT_INVALID"], findings=[])
    if report.get("schema_version") != source_tracking_guard.SCHEMA_VERSION:
        return _check("source_tracking", "fail", reasons=["TRACKING_REPORT_SCHEMA_UNSUPPORTED"], findings=[])

    required_files = report.get("required_files")
    if not isinstance(required_files, list):
        return _check("source_tracking", "fail", reasons=["TRACKING_REPORT_INVALID"], findings=[])

    failing = [
        item
        for item in required_files
        if isinstance(item, dict) and item.get("errors")
    ]
    findings = [
        {
            "discovery_evidence": item.get("discovery_evidence", []),
            "errors": item.get("errors", []),
            "matching_ignore_rule": item.get("matching_ignore_rule"),
            "path": item.get("path"),
        }
        for item in failing[:MAX_REPORTED_TRACKING_FINDINGS]
    ]

    reasons: list[str] = []
    tool_errors = report.get("tool_errors")
    if isinstance(tool_errors, list) and tool_errors:
        reasons.extend(f"TRACKING_TOOL_ERROR:{error}" for error in tool_errors)
    if failing:
        reasons.append("REQUIRED_RUNTIME_SOURCE_NOT_RELEASE_TRACKED")
    if report.get("status") != "pass" and not reasons:
        reasons.append("TRACKING_REPORT_NOT_PASSING")

    return _check(
        "source_tracking",
        "pass" if not reasons else "fail",
        findings=findings,
        findings_truncated=len(failing) > len(findings),
        reasons=sorted(set(reasons)),
        summary=report.get("summary", {}),
    )


def _baseline_check(document: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Return the baseline evidence check and the accepted record, if any."""

    try:
        record = load_baseline_evidence(document)
    except EvidenceDocumentError as error:
        return _check("baseline_evidence", "fail", reasons=[f"BASELINE_DOCUMENT:{error.code}"]), None

    errors = validate_baseline_evidence(record)
    if errors:
        return _check("baseline_evidence", "fail", reasons=errors), None

    return (
        _check(
            "baseline_evidence",
            "pass",
            reasons=[],
            baseline_passing_backend_tests=record["baseline_passing_backend_tests"],
            frontend_production_build=record["frontend_production_build"],
            frontend_typecheck=record["frontend_typecheck"],
            recorded_at=record["recorded_at"],
            repository_revision=record["repository_revision"],
        ),
        record,
    )


def _replacement_coverage_check(document: Path) -> tuple[dict[str, Any], list[str]]:
    """Return the replacement-coverage check and the accepted removed-test set."""

    try:
        records = load_replacement_coverage(document)
    except EvidenceDocumentError as error:
        return _check("replacement_coverage", "fail", reasons=[f"REPLACEMENT_DOCUMENT:{error.code}"]), []

    summary = summarize_replacement_coverage(records)
    return (
        _check(
            "replacement_coverage",
            "pass" if not summary["errors"] else "fail",
            accepted_removed_tests=summary["accepted"],
            reasons=summary["errors"],
            records=summary["records"],
        ),
        summary["accepted"] if not summary["errors"] else [],
    )


def _backend_test_baseline_check(
    observed: int | None,
    *,
    baseline: int,
    justified_removals: int,
) -> dict[str, Any]:
    """Compare the observed passing backend test count against the baseline.

    A count at or above the baseline passes. A lower count passes only when the
    reviewed replacement-coverage records account for the whole shortfall
    (Requirement 1.7); an unsupplied count never passes.
    """

    if observed is None:
        return _check(
            "backend_test_baseline",
            "fail",
            baseline=baseline,
            observed_passing_backend_tests=None,
            reasons=["BACKEND_TEST_COUNT_NOT_SUPPLIED"],
        )
    if not is_count(observed):
        return _check(
            "backend_test_baseline",
            "fail",
            baseline=baseline,
            observed_passing_backend_tests=None,
            reasons=["BACKEND_TEST_COUNT_INVALID"],
        )

    deficit = max(baseline - observed, 0)
    reasons: list[str] = []
    if deficit and justified_removals < deficit:
        reasons.append("BACKEND_TEST_COUNT_BELOW_BASELINE")

    return _check(
        "backend_test_baseline",
        "pass" if not reasons else "fail",
        baseline=baseline,
        deficit=deficit,
        justified_removals=justified_removals,
        observed_passing_backend_tests=observed,
        reasons=reasons,
    )


def build_release_input_report(
    root: Path | str,
    *,
    observed_passing_backend_tests: int | None = None,
    tracking_report: dict[str, Any] | None = None,
    release_docs_root: Path | str | None = None,
) -> dict[str, Any]:
    """Build the release-input report for ``root``.

    ``tracking_report`` may be injected by a caller that already ran the Source
    Tracking Guard; otherwise the guard runs here against ``root``. Either way
    the guard remains the single owner of discovery.
    """

    repository_root = Path(root).resolve()
    docs_root = Path(release_docs_root) if release_docs_root else repository_root / "docs" / "release"

    guard_report = (
        tracking_report if tracking_report is not None else source_tracking_guard.build_report(repository_root)
    )
    baseline_document = docs_root / BASELINE_DOCUMENT_NAME
    inventory_document = docs_root / INVENTORY_DOCUMENT_NAME

    tracking_check = _source_tracking_check(guard_report)
    baseline_check, baseline_record = _baseline_check(baseline_document)
    replacement_check, accepted_removals = _replacement_coverage_check(baseline_document)
    inventory_result = validate_inventory_document(inventory_document)
    inventory_check = _check(
        "cleanup_inventory",
        inventory_result["status"],
        reasons=inventory_result["errors"],
        summary=inventory_result["summary"],
    )

    # Fail closed on the baseline used for comparison: an unusable baseline record
    # falls back to the approved minimum rather than to no gate at all.
    recorded_baseline = baseline_record["baseline_passing_backend_tests"] if baseline_record else 0
    baseline = max(recorded_baseline, BASELINE_MINIMUM_PASSING_BACKEND_TESTS)
    test_check = _backend_test_baseline_check(
        observed_passing_backend_tests,
        baseline=baseline,
        justified_removals=len(accepted_removals),
    )

    checks = [tracking_check, baseline_check, replacement_check, inventory_check, test_check]
    blocking_reasons = sorted(
        {
            f"{check['name']}:{reason}"
            for check in checks
            if check["mandatory"] and check["status"] != "pass"
            for reason in (check.get("reasons") or ["CHECK_FAILED"])
        }
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ready" if not blocking_reasons else "not_ready",
        "blocking_reasons": blocking_reasons,
        "caveats": list(REQUIRED_RELEASE_CAVEATS),
        "checks": checks,
        "cleanup_inventory": inventory_result,
        "mandatory_checks": list(MANDATORY_CHECKS),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report whether the release inputs (tracking, baseline, inventory) are complete and passing.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root to inspect (defaults to the repository containing this script)",
    )
    parser.add_argument(
        "--passing-tests",
        type=int,
        default=None,
        help="passing backend test count observed by the release test run",
    )
    args = parser.parse_args(argv)
    report = build_release_input_report(args.root, observed_passing_backend_tests=args.passing_tests)
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
