"""Property-based coverage for the fail-closed Cleanup Inventory classifier.

The example-based contract lives in
[`test_cleanup_inventory.py`](test_cleanup_inventory.py). This module generates
candidate records across every category, reference class, search outcome,
contract/Protected Capability status, dependency path scope, reviewer-evidence
state, and malformed-record shape, then asserts the classification invariant
rather than individual cases.

The invariant under test is that a candidate is classified
``ELIGIBLE_FOR_REMOVAL_REVIEW`` only when every required reference search was
performed and found nothing, the candidate carries no public HTTP contract or
Protected Capability relationship, dependency candidates were checked against
every supported path, and no evidence gap, unreadable search, conflicting
record, or navigation-only justification remains. Every other record is
``RETAINED`` with the reason recorded.

Each generated case is built from a clean base record plus an explicit set of
injected evidence flaws, so the generator itself is the oracle: the expected
classification is derived from the flaws that were injected, never from the
classifier being tested. All cases are in-memory dictionaries; no test here
reads the network, a database, or the working tree.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.6, 2.7**
"""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from scripts.cleanup_inventory import (
    CANDIDATE_CATEGORIES,
    DEPENDENCY_PATH_SCOPES,
    DISPOSITIONS,
    ELIGIBLE_FOR_REMOVAL_REVIEW,
    NAVIGATION_ONLY_JUSTIFICATION,
    REFERENCE_RESULTS,
    REQUIRED_REFERENCE_TYPES,
    RETAINED,
    classify_candidate,
    validate_inventory,
)

#: Every property in this module runs at least this many generated cases
#: (Requirement 15.11).
GENERATED_CASES = 120

CANDIDATE_IDENTITIES = (
    "app/example/unused_module.py",
    "app/example/legacy_helper.py",
    "app/services/legacy_service.py::retire_case",
    "frontend/src/legacy/OldPanel.tsx",
    "requirements.txt::example-package",
    "GET /api/v1/legacy/report",
    "docs/assets/unused-diagram.svg",
    "settings.legacy_feature_flag",
)
CLEAN_REVIEWERS = ("release reviewer", "second release reviewer")
UNUSABLE_REVIEWERS = ("", "   ", None, 7)
CLEAN_TIMESTAMPS = (
    "2026-09-02",
    "2026-09-02T10:15:00",
    "2026-09-02T10:15:00Z",
    "2026-09-02T10:15:00+05:30",
)
UNUSABLE_TIMESTAMPS = ("", "   ", "not-a-date", "2026-13-45", None, 20260902)
EVIDENCE_GAP_TEXTS = (
    "frontend import graph not searched",
    "generated migration output unreadable",
    "reviewer could not reach the deployment manifest",
)
CLEAN_JUSTIFICATIONS = (
    None,
    [],
    ["NO_REFERENCE_FOUND"],
    ["UNUSED_DEPENDENCY"],
    ["REPLACED_BY_APPROVED_CHANGE"],
    # Navigation absence is only safe alongside a reference-based reason.
    ["NAVIGATION_NOT_EXPOSED", "NO_REFERENCE_FOUND"],
)

#: Flaws that replace one reference class's recorded search. Each is assigned a
#: distinct reference class so one flaw's expected reason cannot be masked by
#: another flaw's more severe outcome for the same class.
REFERENCE_FLAWS = (
    "REFERENCE_FOUND",
    "REFERENCE_UNREADABLE",
    "REFERENCE_INCONCLUSIVE",
    "REFERENCE_SEARCH_MISSING",
    "CONFLICTING_DUPLICATE_SEARCH",
    "LOCATIONS_WITHOUT_REFERENCE",
)
RECORD_FLAWS = (
    "PUBLIC_CONTRACT_REFERENCE",
    "PUBLIC_CONTRACT_STATUS_UNKNOWN",
    "PROTECTED_CAPABILITY_DEPENDENCY",
    "PROTECTED_CAPABILITY_STATUS_UNKNOWN",
    "TEST_COVERAGE_WITHOUT_TEST_REFERENCE",
    "EVIDENCE_GAP_RECORDED",
    "MISSING_REVIEWER",
    "MISSING_REVIEWED_AT",
    "DEPENDENCY_SCOPE_UNCHECKED",
    "NAVIGATION_ONLY_JUSTIFICATION",
)
ALL_FLAWS = REFERENCE_FLAWS + RECORD_FLAWS

#: Flaws describing a live reference or an unsafe justification rather than an
#: evidence gap (Requirements 2.2, 2.6).
LIVE_REFERENCE_FLAWS = (
    "REFERENCE_FOUND",
    "CONFLICTING_DUPLICATE_SEARCH",
    "PUBLIC_CONTRACT_REFERENCE",
    "PROTECTED_CAPABILITY_DEPENDENCY",
    "NAVIGATION_ONLY_JUSTIFICATION",
)

#: Flaws describing incomplete, conflicting, or unreadable evidence
#: (Requirements 2.4, 2.7).
INCOMPLETE_EVIDENCE_FLAWS = (
    "REFERENCE_UNREADABLE",
    "REFERENCE_INCONCLUSIVE",
    "REFERENCE_SEARCH_MISSING",
    "LOCATIONS_WITHOUT_REFERENCE",
    "TEST_COVERAGE_WITHOUT_TEST_REFERENCE",
    "PUBLIC_CONTRACT_STATUS_UNKNOWN",
    "PROTECTED_CAPABILITY_STATUS_UNKNOWN",
    "EVIDENCE_GAP_RECORDED",
    "MISSING_REVIEWER",
    "MISSING_REVIEWED_AT",
    "DEPENDENCY_SCOPE_UNCHECKED",
)

#: Flaw pairs that write the same record field. Keeping both would make the
#: expected reason depend on application order, so the second is dropped.
_EXCLUSIVE_FLAW_PAIRS = (
    ("PUBLIC_CONTRACT_REFERENCE", "PUBLIC_CONTRACT_STATUS_UNKNOWN"),
    ("PROTECTED_CAPABILITY_DEPENDENCY", "PROTECTED_CAPABILITY_STATUS_UNKNOWN"),
)


def _search(reference_type: str, result: str, *, locations: list[str] | None = None, label: str = "repository") -> dict[str, Any]:
    """Return one recorded reference search."""

    entry: dict[str, Any] = {
        "reference_type": reference_type,
        "query": f"{label} search for {reference_type.lower()} references",
        "result": result,
    }
    if locations is not None:
        entry["locations"] = locations
    return entry


def _without_exclusive_conflicts(flaws: list[str]) -> list[str]:
    """Drop the second flaw of any pair that writes the same record field."""

    kept = list(flaws)
    for first, second in _EXCLUSIVE_FLAW_PAIRS:
        if first in kept and second in kept:
            kept.remove(second)
    return kept


@st.composite
def candidate_records(
    draw: st.DrawFn,
    *,
    flaw_pool: tuple[str, ...] = ALL_FLAWS,
    min_flaws: int = 0,
    max_flaws: int = 4,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Generate a candidate record with a known set of injected evidence flaws.

    Returns the record and an expectation describing the flaws that were
    injected, the retention reason codes those flaws must produce, and the
    subset of those reasons that must be reported as incomplete evidence.
    """

    flaws = _without_exclusive_conflicts(
        draw(st.lists(st.sampled_from(flaw_pool), unique=True, min_size=min_flaws, max_size=max_flaws))
    )
    expected_reasons: set[str] = set()
    expected_incomplete: set[str] = set()

    category = draw(st.sampled_from(CANDIDATE_CATEGORIES))
    if "DEPENDENCY_SCOPE_UNCHECKED" in flaws:
        category = "DEPENDENCY"

    # A candidate that records test coverage is only conflicting evidence while
    # its TEST search reports no reference, so no reference flaw may claim TEST.
    assignable = [
        reference_type
        for reference_type in REQUIRED_REFERENCE_TYPES
        if not ("TEST_COVERAGE_WITHOUT_TEST_REFERENCE" in flaws and reference_type == "TEST")
    ]
    targets = draw(
        st.lists(
            st.sampled_from(assignable),
            unique=True,
            min_size=len(REFERENCE_FLAWS),
            max_size=len(REFERENCE_FLAWS),
        )
    )
    target_for = dict(zip(REFERENCE_FLAWS, targets))

    # Clean baseline: every required class searched, nothing found. A repeated
    # clean search for one class must stay eligible.
    searches: dict[str, list[dict[str, Any]]] = {}
    for reference_type in REQUIRED_REFERENCE_TYPES:
        entries = [_search(reference_type, "NONE_FOUND")]
        if draw(st.integers(min_value=0, max_value=4)) == 0:
            entries.append(_search(reference_type, "NONE_FOUND", label="second"))
        searches[reference_type] = entries

    if "REFERENCE_FOUND" in flaws:
        target = target_for["REFERENCE_FOUND"]
        searches[target] = [_search(target, "FOUND", locations=["app/main.py:12"])]
        expected_reasons.add(f"REFERENCE_PRESENT:{target}")
    if "REFERENCE_UNREADABLE" in flaws:
        target = target_for["REFERENCE_UNREADABLE"]
        searches[target] = [_search(target, "UNREADABLE")]
        expected_reasons.add(f"EVIDENCE_UNREADABLE:{target}")
        expected_incomplete.add(f"EVIDENCE_UNREADABLE:{target}")
    if "REFERENCE_INCONCLUSIVE" in flaws:
        target = target_for["REFERENCE_INCONCLUSIVE"]
        searches[target] = [_search(target, "INCONCLUSIVE")]
        expected_reasons.add(f"EVIDENCE_INCONCLUSIVE:{target}")
        expected_incomplete.add(f"EVIDENCE_INCONCLUSIVE:{target}")
    if "REFERENCE_SEARCH_MISSING" in flaws:
        target = target_for["REFERENCE_SEARCH_MISSING"]
        searches.pop(target, None)
        expected_reasons.add(f"REFERENCE_SEARCH_MISSING:{target}")
        expected_incomplete.add(f"REFERENCE_SEARCH_MISSING:{target}")
    if "CONFLICTING_DUPLICATE_SEARCH" in flaws:
        target = target_for["CONFLICTING_DUPLICATE_SEARCH"]
        searches[target] = [
            _search(target, "NONE_FOUND"),
            _search(target, "FOUND", label="second"),
        ]
        expected_reasons.add(f"REFERENCE_PRESENT:{target}")
    if "LOCATIONS_WITHOUT_REFERENCE" in flaws:
        target = target_for["LOCATIONS_WITHOUT_REFERENCE"]
        searches[target] = [_search(target, "NONE_FOUND", locations=["app/api/router.py:41"])]
        expected_reasons.add("CONFLICTING_EVIDENCE:REFERENCE_LOCATIONS_WITHOUT_REFERENCE")
        expected_incomplete.add("CONFLICTING_EVIDENCE:REFERENCE_LOCATIONS_WITHOUT_REFERENCE")

    references = draw(
        st.permutations(
            [entry for reference_type in REQUIRED_REFERENCE_TYPES for entry in searches.get(reference_type, [])]
        )
    )

    record: dict[str, Any] = {
        "candidate": draw(st.sampled_from(CANDIDATE_IDENTITIES)),
        "category": category,
        "references_searched": list(references),
        "public_contract_status": "NONE",
        "protected_capability_status": "NONE",
        "test_coverage": [],
        "evidence_gaps": [],
        "proposed_disposition": draw(st.sampled_from(DISPOSITIONS)),
        "reviewer": draw(st.sampled_from(CLEAN_REVIEWERS)),
        "reviewed_at": draw(st.sampled_from(CLEAN_TIMESTAMPS)),
    }

    justification = draw(st.sampled_from(CLEAN_JUSTIFICATIONS))
    if justification is not None:
        record["removal_justification"] = list(justification)
    if draw(st.booleans()):
        record["notes"] = ["reviewed against the current repository revision"]

    scopes_checked = list(DEPENDENCY_PATH_SCOPES)
    if category == "DEPENDENCY" or draw(st.booleans()):
        # A non-dependency candidate may record scopes; they are informational
        # there and must not change its classification.
        if category != "DEPENDENCY":
            scopes_checked = draw(st.lists(st.sampled_from(DEPENDENCY_PATH_SCOPES), unique=True))
        record["dependency_path_scopes_checked"] = scopes_checked

    if "PUBLIC_CONTRACT_REFERENCE" in flaws:
        record["public_contract_status"] = "PUBLIC_HTTP_CONTRACT"
        expected_reasons.add("PUBLIC_CONTRACT_REFERENCE")
    if "PUBLIC_CONTRACT_STATUS_UNKNOWN" in flaws:
        record["public_contract_status"] = "UNKNOWN"
        expected_reasons.add("PUBLIC_CONTRACT_STATUS_UNKNOWN")
        expected_incomplete.add("PUBLIC_CONTRACT_STATUS_UNKNOWN")
    if "PROTECTED_CAPABILITY_DEPENDENCY" in flaws:
        record["protected_capability_status"] = "PROTECTED_CAPABILITY_DEPENDENCY"
        expected_reasons.add("PROTECTED_CAPABILITY_DEPENDENCY")
    if "PROTECTED_CAPABILITY_STATUS_UNKNOWN" in flaws:
        record["protected_capability_status"] = "UNKNOWN"
        expected_reasons.add("PROTECTED_CAPABILITY_STATUS_UNKNOWN")
        expected_incomplete.add("PROTECTED_CAPABILITY_STATUS_UNKNOWN")
    if "TEST_COVERAGE_WITHOUT_TEST_REFERENCE" in flaws:
        record["test_coverage"] = ["tests/test_example.py::test_case"]
        expected_reasons.add("CONFLICTING_EVIDENCE:TEST_COVERAGE_WITHOUT_TEST_REFERENCE")
        expected_incomplete.add("CONFLICTING_EVIDENCE:TEST_COVERAGE_WITHOUT_TEST_REFERENCE")
    if "EVIDENCE_GAP_RECORDED" in flaws:
        record["evidence_gaps"] = draw(
            st.lists(st.sampled_from(EVIDENCE_GAP_TEXTS), unique=True, min_size=1, max_size=2)
        )
        expected_reasons.add("EVIDENCE_GAP_RECORDED")
        expected_incomplete.add("EVIDENCE_GAP_RECORDED")
    if "MISSING_REVIEWER" in flaws:
        record["reviewer"] = draw(st.sampled_from(UNUSABLE_REVIEWERS))
        expected_reasons.add("MISSING_REVIEWER_EVIDENCE")
        expected_incomplete.add("MISSING_REVIEWER_EVIDENCE")
    if "MISSING_REVIEWED_AT" in flaws:
        record["reviewed_at"] = draw(st.sampled_from(UNUSABLE_TIMESTAMPS))
        expected_reasons.add("MISSING_REVIEWER_EVIDENCE")
        expected_incomplete.add("MISSING_REVIEWER_EVIDENCE")
    if "DEPENDENCY_SCOPE_UNCHECKED" in flaws:
        omitted = draw(st.sampled_from(DEPENDENCY_PATH_SCOPES))
        record["dependency_path_scopes_checked"] = [
            scope for scope in DEPENDENCY_PATH_SCOPES if scope != omitted
        ]
        expected_reasons.add(f"DEPENDENCY_PATH_SCOPE_UNCHECKED:{omitted}")
        expected_incomplete.add(f"DEPENDENCY_PATH_SCOPE_UNCHECKED:{omitted}")
    if "NAVIGATION_ONLY_JUSTIFICATION" in flaws:
        record["removal_justification"] = [NAVIGATION_ONLY_JUSTIFICATION]
        expected_reasons.add("NAVIGATION_ONLY_JUSTIFICATION")

    expectation = {
        "flaws": sorted(flaws),
        "reasons": sorted(expected_reasons),
        "incomplete": sorted(expected_incomplete),
    }
    return record, expectation


def _clean_record() -> dict[str, Any]:
    """A minimal record whose evidence supports removal review."""

    return {
        "candidate": "app/example/unused_module.py",
        "category": "FILE",
        "references_searched": [
            _search(reference_type, "NONE_FOUND") for reference_type in REQUIRED_REFERENCE_TYPES
        ],
        "public_contract_status": "NONE",
        "protected_capability_status": "NONE",
        "test_coverage": [],
        "evidence_gaps": [],
        "proposed_disposition": ELIGIBLE_FOR_REMOVAL_REVIEW,
        "reviewer": "release reviewer",
        "reviewed_at": "2026-09-02",
    }


@st.composite
def malformed_records(draw: st.DrawFn) -> Any:
    """Generate records the reviewer contract cannot read as valid evidence."""

    mutation = draw(
        st.sampled_from(
            (
                "not_an_object",
                "drop_required_field",
                "unknown_field",
                "invalid_category",
                "invalid_disposition",
                "empty_candidate",
                "references_not_array",
                "reference_entry_not_object",
                "reference_field_missing",
                "invalid_reference_type",
                "invalid_reference_result",
                "test_coverage_not_array",
                "evidence_gap_not_string",
                "invalid_dependency_scope",
                "invalid_removal_justification",
            )
        )
    )

    if mutation == "not_an_object":
        return draw(
            st.one_of(
                st.none(),
                st.booleans(),
                st.integers(),
                st.text(max_size=12),
                st.lists(st.integers(), max_size=3),
            )
        )

    record = _clean_record()
    if mutation == "drop_required_field":
        del record[draw(st.sampled_from(sorted(record)))]
    elif mutation == "unknown_field":
        record[draw(st.sampled_from(("owner", "ticket", "reviewed_by_team")))] = "value"
    elif mutation == "invalid_category":
        record["category"] = draw(st.sampled_from(("MYSTERY", "", None, 3)))
    elif mutation == "invalid_disposition":
        record["proposed_disposition"] = draw(st.sampled_from(("MAYBE", "", None)))
    elif mutation == "empty_candidate":
        record["candidate"] = draw(st.sampled_from(("", "   ", None, 5)))
    elif mutation == "references_not_array":
        record["references_searched"] = draw(st.sampled_from(("not-a-list", 4, None)))
    elif mutation == "reference_entry_not_object":
        record["references_searched"].append(draw(st.sampled_from(("RUNTIME_IMPORT", 7, None))))
    elif mutation == "reference_field_missing":
        entry = dict(record["references_searched"][0])
        del entry[draw(st.sampled_from(("query", "reference_type", "result")))]
        record["references_searched"][0] = entry
    elif mutation == "invalid_reference_type":
        record["references_searched"][0] = {
            **record["references_searched"][0],
            "reference_type": draw(st.sampled_from(("FRONTEND_IMPORT", "", None))),
        }
    elif mutation == "invalid_reference_result":
        record["references_searched"][0] = {
            **record["references_searched"][0],
            "result": draw(st.sampled_from(("MAYBE", "", None))),
        }
    elif mutation == "test_coverage_not_array":
        record["test_coverage"] = draw(st.sampled_from(("tests/test_example.py", 1, None)))
    elif mutation == "evidence_gap_not_string":
        record["evidence_gaps"] = draw(st.sampled_from(([""], [None], [3], "gap")))
    elif mutation == "invalid_dependency_scope":
        record["dependency_path_scopes_checked"] = draw(st.sampled_from((["DOCS"], "RUNTIME", [1])))
    elif mutation == "invalid_removal_justification":
        record["removal_justification"] = draw(st.sampled_from((["BECAUSE"], "NO_REFERENCE_FOUND", [None])))
    return record


# Feature: production-readiness-cleanup, Property 2: Cleanup classification fails closed
@settings(max_examples=200, deadline=None)
@given(case=candidate_records())
def test_classification_is_eligible_only_for_complete_and_clean_evidence(
    case: tuple[dict[str, Any], dict[str, Any]],
):
    """Removal review requires complete, clean evidence; anything else is retained.

    **Validates: Requirements 2.2, 2.3, 2.4, 2.6, 2.7**
    """

    record, expectation = case

    result = classify_candidate(record, index=7)

    assert result["index"] == 7
    assert result["candidate"] == record["candidate"]
    if expectation["flaws"]:
        assert result["classification"] == RETAINED
        # A retained candidate always records why it was retained.
        assert result["retention_reasons"]
        assert set(expectation["reasons"]) <= set(result["retention_reasons"])
        assert set(expectation["incomplete"]) <= set(result["incomplete_evidence"])
    else:
        assert result["classification"] == ELIGIBLE_FOR_REMOVAL_REVIEW
        assert result["retention_reasons"] == []
        assert result["incomplete_evidence"] == []
        assert result["record_errors"] == []
    assert result["disposition_conflict"] is (
        record["proposed_disposition"] == ELIGIBLE_FOR_REMOVAL_REVIEW
        and result["classification"] == RETAINED
    )


# Feature: production-readiness-cleanup, Property 2: Cleanup classification fails closed
@settings(max_examples=GENERATED_CASES, deadline=None)
@given(case=candidate_records(flaw_pool=LIVE_REFERENCE_FLAWS, min_flaws=1))
def test_live_reference_or_protected_capability_retains_the_candidate(
    case: tuple[dict[str, Any], dict[str, Any]],
):
    """A found reference, public contract, Protected Capability dependency, or
    navigation-only justification retains the candidate as a live reference
    rather than an evidence gap.

    **Validates: Requirements 2.2, 2.6**
    """

    record, expectation = case

    result = classify_candidate(record)

    assert result["classification"] == RETAINED
    assert set(expectation["reasons"]) <= set(result["retention_reasons"])
    # These reasons describe present references and unsafe justifications, not
    # missing or unreadable evidence.
    assert result["incomplete_evidence"] == []
    assert result["record_errors"] == []


# Feature: production-readiness-cleanup, Property 2: Cleanup classification fails closed
@settings(max_examples=GENERATED_CASES, deadline=None)
@given(case=candidate_records(flaw_pool=INCOMPLETE_EVIDENCE_FLAWS, min_flaws=1))
def test_incomplete_conflicting_or_unreadable_evidence_is_recorded(
    case: tuple[dict[str, Any], dict[str, Any]],
):
    """Missing, unreadable, inconclusive, conflicting, and unchecked-scope
    evidence retains the candidate and is reported as incomplete evidence.

    **Validates: Requirements 2.1, 2.4, 2.7**
    """

    record, expectation = case

    result = classify_candidate(record)

    assert result["classification"] == RETAINED
    assert set(expectation["reasons"]) <= set(result["retention_reasons"])
    assert set(expectation["incomplete"]) <= set(result["incomplete_evidence"])
    assert result["incomplete_evidence"]


# Feature: production-readiness-cleanup, Property 2: Cleanup classification fails closed
@settings(max_examples=GENERATED_CASES, deadline=None)
@given(
    reference_type=st.sampled_from(REQUIRED_REFERENCE_TYPES),
    result_value=st.sampled_from(REFERENCE_RESULTS),
    searched=st.booleans(),
)
def test_every_reference_class_and_search_outcome_is_classified(
    reference_type: str, result_value: str, searched: bool
):
    """Each required reference class must be searched, and only a search that
    found nothing keeps the candidate eligible.

    **Validates: Requirements 2.2, 2.3, 2.4**
    """

    record = _clean_record()
    record["references_searched"] = [
        entry for entry in record["references_searched"] if entry["reference_type"] != reference_type
    ]
    if searched:
        record["references_searched"].append(_search(reference_type, result_value))

    result = classify_candidate(record)

    if not searched:
        assert result["classification"] == RETAINED
        assert f"REFERENCE_SEARCH_MISSING:{reference_type}" in result["incomplete_evidence"]
    elif result_value == "NONE_FOUND":
        assert result["classification"] == ELIGIBLE_FOR_REMOVAL_REVIEW
        assert result["retention_reasons"] == []
    elif result_value == "FOUND":
        assert result["classification"] == RETAINED
        assert f"REFERENCE_PRESENT:{reference_type}" in result["retention_reasons"]
        assert result["incomplete_evidence"] == []
    else:
        expected = {
            "UNREADABLE": f"EVIDENCE_UNREADABLE:{reference_type}",
            "INCONCLUSIVE": f"EVIDENCE_INCONCLUSIVE:{reference_type}",
        }[result_value]
        assert result["classification"] == RETAINED
        assert expected in result["incomplete_evidence"]


# Feature: production-readiness-cleanup, Property 2: Cleanup classification fails closed
@settings(max_examples=GENERATED_CASES, deadline=None)
@given(record=malformed_records())
def test_unreadable_record_evidence_fails_closed(record: Any):
    """A record the reviewer contract cannot read is retained and reported.

    **Validates: Requirements 2.1, 2.4**
    """

    result = classify_candidate(record)

    assert result["classification"] == RETAINED
    assert result["record_errors"]
    assert "RECORD_EVIDENCE_INVALID" in result["incomplete_evidence"]
    assert "RECORD_EVIDENCE_INVALID" in result["retention_reasons"]


# Feature: production-readiness-cleanup, Property 2: Cleanup classification fails closed
@settings(max_examples=GENERATED_CASES, deadline=None)
@given(cases=st.lists(candidate_records(), min_size=1, max_size=4))
def test_inventory_rejects_every_removal_its_evidence_does_not_support(
    cases: list[tuple[dict[str, Any], dict[str, Any]]],
):
    """An inventory proposing removal fails while any candidate's evidence
    retains it, and its summary counts match the derived classifications.

    **Validates: Requirements 2.1, 2.3, 2.4**
    """

    records = []
    for index, (record, _) in enumerate(cases):
        proposed = dict(record)
        # Keep candidate identities unique so duplicate-identity errors cannot
        # be confused with disposition conflicts.
        proposed["candidate"] = f"{index}::{record['candidate']}"
        proposed["proposed_disposition"] = ELIGIBLE_FOR_REMOVAL_REVIEW
        records.append(proposed)

    flawed = [index for index, (_, expectation) in enumerate(cases) if expectation["flaws"]]

    result = validate_inventory(records)

    assert result["summary"]["candidates"] == len(records)
    assert result["summary"]["retained"] == len(flawed)
    assert result["summary"]["eligible"] == len(records) - len(flawed)
    assert result["summary"]["disposition_conflicts"] == len(flawed)
    if flawed:
        assert result["status"] == "fail"
        for index in flawed:
            assert f"INVENTORY_DISPOSITION_CONFLICT:{index}" in result["errors"]
    else:
        assert result["status"] == "pass"
        assert result["errors"] == []
