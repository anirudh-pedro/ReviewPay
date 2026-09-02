"""Schemas and validators for the release evidence documents.

Two reviewed records live in [`docs/release/baseline-evidence.md`](../docs/release/baseline-evidence.md):

* the **baseline evidence record**, which pins the approved pre-remediation
  comparison point (595 passing backend tests plus a passing frontend typecheck
  and production build), and
* the **replacement-coverage records**, which are the only accepted
  justification for a later backend test count below that baseline.

Both records are embedded in the reviewed Markdown document as fenced JSON that
follows an explicit marker comment, so one document stays human-reviewable and
machine-checkable instead of drifting into two sources of truth.

Every validator returns sorted, stable error codes rather than free-form text.
Codes never echo a supplied value, so a report built from them can be retained
as release evidence without leaking configuration or secret material.

This module only reads files. It never writes, deletes, or mutates repository
state.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any


SCHEMA_VERSION = 1

BASELINE_MARKER = "revivepay:baseline-evidence"
REPLACEMENT_COVERAGE_MARKER = "revivepay:replacement-coverage"

#: The approved pre-remediation backend baseline (Requirement 1.6). A later
#: suite may report more passing tests; it may not report fewer without a
#: reviewed replacement-coverage record (Requirement 1.7).
BASELINE_MINIMUM_PASSING_BACKEND_TESTS = 595

BASELINE_REQUIRED_FIELDS = (
    "baseline_passing_backend_tests",
    "commands",
    "frontend_production_build",
    "frontend_typecheck",
    "recorded_at",
    "repository_revision",
    "schema_version",
)
BASELINE_OPTIONAL_FIELDS = ("notes", "observations")
BASELINE_REQUIRED_COMMANDS = ("backend_tests", "frontend_build", "frontend_typecheck")
CHECK_RESULTS = frozenset({"pass", "fail"})

REPLACEMENT_REQUIRED_FIELDS = (
    "removal_reason",
    "removed_test",
    "retained_coverage",
    "reviewed_at",
    "reviewer",
)
REPLACEMENT_OPTIONAL_FIELDS = ("notes",)

#: Limitations that a release record must retain even when every check passes
#: (Requirement 17.6). The release documentation template repeats these strings
#: verbatim so the generated record and the reviewed template cannot diverge.
REQUIRED_RELEASE_CAVEATS = (
    "Synthetic deterministic simulation results do not represent real payment recovery performance.",
    "Razorpay Sandbox verification observes provider test-environment state and does not move live money.",
    "Read-only synthetic projections and baseline comparisons are not actual recovered revenue.",
)

_REVISION_PATTERN = re.compile(r"\A[0-9a-f]{40}\Z")
_FENCE_PATTERN = re.compile(r"^```(?P<info>[^\n]*)\n(?P<body>.*?)^```", re.DOTALL | re.MULTILINE)


class EvidenceDocumentError(Exception):
    """Raised when an evidence document cannot supply a machine-readable record.

    The ``code`` is a stable identifier suitable for a release record; the
    document path is deliberately not embedded in it.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def read_document(path: Path | str) -> str:
    """Return the text of an evidence document, or raise ``EvidenceDocumentError``."""

    document = Path(path)
    if not document.is_file():
        raise EvidenceDocumentError("DOCUMENT_MISSING")
    try:
        return document.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise EvidenceDocumentError("DOCUMENT_UNREADABLE") from error


def extract_embedded_json(text: str, *, marker: str) -> Any:
    """Return the JSON document in the first fenced block after ``marker``.

    The marker is required so an illustrative example block elsewhere in the
    document can never be mistaken for the reviewed record.
    """

    marker_index = text.find(marker)
    if marker_index < 0:
        raise EvidenceDocumentError("MARKER_MISSING")
    match = _FENCE_PATTERN.search(text, marker_index)
    if match is None:
        raise EvidenceDocumentError("RECORD_BLOCK_MISSING")
    if match.group("info").strip().lower() != "json":
        raise EvidenceDocumentError("RECORD_BLOCK_NOT_JSON")
    try:
        return json.loads(match.group("body"))
    except json.JSONDecodeError as error:
        raise EvidenceDocumentError("RECORD_INVALID_JSON") from error


def load_embedded_json(path: Path | str, *, marker: str) -> Any:
    """Read ``path`` and return the reviewed record identified by ``marker``."""

    return extract_embedded_json(read_document(path), marker=marker)


def load_baseline_evidence(path: Path | str) -> Any:
    return load_embedded_json(path, marker=BASELINE_MARKER)


def load_replacement_coverage(path: Path | str) -> Any:
    return load_embedded_json(path, marker=REPLACEMENT_COVERAGE_MARKER)


def is_non_empty_string(value: Any) -> bool:
    """Return whether ``value`` is a string with non-whitespace content."""

    return isinstance(value, str) and bool(value.strip())


def is_string_list(value: Any, *, allow_empty: bool) -> bool:
    """Return whether ``value`` is a list of non-empty strings."""

    if not isinstance(value, list):
        return False
    if not value:
        return allow_empty
    return all(is_non_empty_string(item) for item in value)


def is_count(value: Any) -> bool:
    """Return whether ``value`` is a nonnegative integer count.

    ``bool`` is an ``int`` subclass, so a boolean is rejected as a review error
    rather than silently counted as 0 or 1.
    """

    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def is_iso_timestamp(value: Any) -> bool:
    """Return whether ``value`` is an ISO 8601 date or timestamp string."""

    if not is_non_empty_string(value):
        return False
    candidate = value.strip()
    if candidate.endswith(("Z", "z")):
        candidate = f"{candidate[:-1]}+00:00"
    try:
        datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return True


def _field_errors(
    record: dict[str, Any],
    *,
    required: Sequence[str],
    optional: Sequence[str],
    prefix: str,
) -> list[str]:
    errors = [f"{prefix}_FIELD_MISSING:{name}" for name in required if name not in record]
    allowed = set(required) | set(optional)
    errors.extend(f"{prefix}_FIELD_UNKNOWN:{name}" for name in sorted(set(record) - allowed))
    return errors


def validate_baseline_evidence(record: Any) -> list[str]:
    """Return sorted error codes for a baseline evidence record.

    An empty list means the record is a complete, usable comparison point. A
    record that claims a weaker baseline than the approved 595 passing backend
    tests is rejected, because accepting it would silently lower the release
    gate.
    """

    if not isinstance(record, dict):
        return ["BASELINE_RECORD_NOT_OBJECT"]

    errors = _field_errors(
        record,
        required=BASELINE_REQUIRED_FIELDS,
        optional=BASELINE_OPTIONAL_FIELDS,
        prefix="BASELINE",
    )

    if "schema_version" in record and record["schema_version"] != SCHEMA_VERSION:
        errors.append("BASELINE_SCHEMA_VERSION_UNSUPPORTED")

    if "baseline_passing_backend_tests" in record:
        count = record["baseline_passing_backend_tests"]
        if not is_count(count):
            errors.append("BASELINE_TEST_COUNT_INVALID")
        elif count < BASELINE_MINIMUM_PASSING_BACKEND_TESTS:
            errors.append("BASELINE_TEST_COUNT_BELOW_APPROVED_MINIMUM")

    for field, code in (
        ("frontend_typecheck", "BASELINE_FRONTEND_TYPECHECK"),
        ("frontend_production_build", "BASELINE_FRONTEND_BUILD"),
    ):
        if field not in record:
            continue
        value = record[field]
        if value not in CHECK_RESULTS:
            errors.append(f"{code}_INVALID")
        elif value != "pass":
            errors.append(f"{code}_NOT_PASSING")

    if "repository_revision" in record and not _REVISION_PATTERN.match(
        record["repository_revision"] if isinstance(record["repository_revision"], str) else ""
    ):
        errors.append("BASELINE_REPOSITORY_REVISION_INVALID")

    if "recorded_at" in record and not is_iso_timestamp(record["recorded_at"]):
        errors.append("BASELINE_RECORDED_AT_INVALID")

    if "commands" in record:
        commands = record["commands"]
        if not isinstance(commands, dict):
            errors.append("BASELINE_COMMANDS_INVALID")
        else:
            for name in BASELINE_REQUIRED_COMMANDS:
                if name not in commands:
                    errors.append(f"BASELINE_COMMAND_MISSING:{name}")
                elif not is_non_empty_string(commands[name]):
                    errors.append(f"BASELINE_COMMAND_INVALID:{name}")

    if "observations" in record:
        errors.extend(_observation_errors(record["observations"]))

    if "notes" in record and not is_string_list(record["notes"], allow_empty=True):
        errors.append("BASELINE_NOTES_INVALID")

    return sorted(set(errors))


def _observation_errors(observations: Any) -> list[str]:
    """Validate later measured counts, which are evidence but never the baseline."""

    if not isinstance(observations, list):
        return ["BASELINE_OBSERVATIONS_INVALID"]
    errors: list[str] = []
    for observation in observations:
        if not isinstance(observation, dict) or not is_non_empty_string(observation.get("label")):
            errors.append("BASELINE_OBSERVATION_INVALID")
            continue
        if "passing_backend_tests" in observation and not is_count(observation["passing_backend_tests"]):
            errors.append("BASELINE_OBSERVATION_INVALID")
    return errors


def validate_replacement_coverage_record(record: Any) -> list[str]:
    """Return sorted error codes for one reviewed replacement-coverage record.

    A record is accepted only when it identifies the removed test, the reason it
    was removed, the retained coverage that replaces it, and the reviewer who
    approved the substitution (Requirement 1.7).
    """

    if not isinstance(record, dict):
        return ["REPLACEMENT_RECORD_NOT_OBJECT"]

    errors = _field_errors(
        record,
        required=REPLACEMENT_REQUIRED_FIELDS,
        optional=REPLACEMENT_OPTIONAL_FIELDS,
        prefix="REPLACEMENT",
    )

    if "removed_test" in record and not is_non_empty_string(record["removed_test"]):
        errors.append("REPLACEMENT_REMOVED_TEST_INVALID")
    if "removal_reason" in record and not is_non_empty_string(record["removal_reason"]):
        errors.append("REPLACEMENT_REMOVAL_REASON_INVALID")
    if "retained_coverage" in record and not is_string_list(record["retained_coverage"], allow_empty=False):
        errors.append("REPLACEMENT_RETAINED_COVERAGE_INVALID")
    if "reviewer" in record and not is_non_empty_string(record["reviewer"]):
        errors.append("REPLACEMENT_REVIEWER_INVALID")
    if "reviewed_at" in record and not is_iso_timestamp(record["reviewed_at"]):
        errors.append("REPLACEMENT_REVIEWED_AT_INVALID")
    if "notes" in record and not is_string_list(record["notes"], allow_empty=True):
        errors.append("REPLACEMENT_NOTES_INVALID")

    return sorted(set(errors))


def summarize_replacement_coverage(records: Any) -> dict[str, Any]:
    """Validate the replacement-coverage record set and list accepted removals.

    Only complete records are accepted, and each accepted record justifies
    exactly one removed test. An identity repeated across records is a review
    error rather than a second justification.
    """

    if not isinstance(records, list):
        return {"accepted": [], "errors": ["REPLACEMENT_RECORDS_NOT_ARRAY"], "records": 0}

    errors: list[str] = []
    accepted: list[str] = []
    seen: set[str] = set()

    for index, record in enumerate(records):
        record_errors = validate_replacement_coverage_record(record)
        if record_errors:
            errors.append(f"REPLACEMENT_RECORD_INVALID:{index}")
            errors.extend(record_errors)
            continue
        identity = record["removed_test"].strip()
        if identity in seen:
            errors.append(f"REPLACEMENT_RECORD_DUPLICATE:{index}")
            continue
        seen.add(identity)
        accepted.append(identity)

    return {
        "accepted": sorted(accepted),
        "errors": sorted(set(errors)),
        "records": len(records),
    }


def missing_caveats(text: str, caveats: Iterable[str] = REQUIRED_RELEASE_CAVEATS) -> list[str]:
    """Return the required release limitations absent from ``text``."""

    return [caveat for caveat in caveats if caveat not in text]
