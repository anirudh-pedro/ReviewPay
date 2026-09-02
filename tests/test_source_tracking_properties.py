"""Property-based coverage for release-input closure.

# Feature: production-readiness-cleanup, Property 1: Runtime source and release baseline are closed

Two universal statements are generated and checked here:

1. For any supported startup, API-route, migration, script, test, or frontend
   build manifest, the discovered Runtime Source set is exactly the closure of
   those manifests, every discovered input is reported with discovery evidence,
   and the release inputs are ready only when every discovered input is tracked
   by Git without an effective ignore rule.
2. For any observed passing backend test count below the approved 595 baseline,
   release readiness is false unless complete, reviewed, distinct
   replacement-coverage records account for the whole shortfall.

Each generated repository is deliberately tiny and deterministic. One temporary
Git repository is initialized per example, so the case shapes vary while the cost
per example stays close to the cost of the Git calls the guard itself makes. No
test here reaches the network.

Unreadability is generated portably. A file whose bytes are not valid UTF-8
cannot be read as source on any platform, and a required input that is absent
cannot be opened at all; the guard reports both as an ``UNREADABLE`` discovery
failure. Filesystem permission bits are deliberately not used, because clearing
them does not deny read access to the owning process on Windows.

**Validates: Requirements 1.1–1.7, 15.1, 17.1–17.2, 17.5, 17.7**
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from hypothesis import given, settings, strategies as st
import pytest

from scripts.cleanup_inventory import INVENTORY_MARKER
from scripts.release_evidence import (
    BASELINE_MARKER,
    BASELINE_MINIMUM_PASSING_BACKEND_TESTS,
    REPLACEMENT_COVERAGE_MARKER,
)
from scripts.release_inputs import build_release_input_report
from scripts.source_tracking_guard import SCHEMA_VERSION, build_report


BASELINE = BASELINE_MINIMUM_PASSING_BACKEND_TESTS

#: How a generated input becomes required, mapped to the manifest that imports
#: it. ``models`` and ``frontend_build`` are handled separately because the guard
#: also reaches them through the models tree and the frontend source tree.
PYTHON_IMPORTERS = {
    "startup": "app/main.py",
    "api_route": "app/api/router.py",
    "migration": "alembic/env.py",
    "script": "scripts/check.py",
    "test": "tests/test_runtime.py",
}
ORIGINS = (*PYTHON_IMPORTERS, "models", "frontend_build")

#: Version-control and readability states a required input can be generated in.
STATES = ("TRACKED", "UNTRACKED", "IGNORED", "LATENT_IGNORED", "MISSING", "UNDECODABLE")

#: The error set the guard must report for each generated state.
EXPECTED_ERRORS = {
    "TRACKED": [],
    "LATENT_IGNORED": [],
    "UNTRACKED": ["UNTRACKED"],
    "IGNORED": ["IGNORED", "UNTRACKED"],
    "MISSING": ["MISSING", "UNREADABLE", "UNTRACKED"],
    "UNDECODABLE": ["UNREADABLE"],
}

#: Ignore rules every generated repository carries, mirroring the real
#: repository. ``/models/`` is anchored at the root and must never be treated as
#: an exclusion of the ``app/models/`` application package (Requirement 1.2).
BASE_IGNORE_RULES = ("__pycache__/", "*.log", "/models/", "artifacts/")

#: The required inputs the base repository always contributes, one per supported
#: manifest kind. Discovery must report exactly these plus the generated inputs.
BASE_REQUIRED_PATHS = frozenset(
    {
        "alembic.ini",
        "alembic/env.py",
        "alembic/script.py.mako",
        "alembic/versions/20260101_01_initial.py",
        "app/api/router.py",
        "app/main.py",
        "app/models/__init__.py",
        "frontend/index.html",
        "frontend/package.json",
        "frontend/src/main.ts",
        "requirements.txt",
        "scripts/check.py",
        "tests/test_runtime.py",
    }
)

#: A leading 0xFF byte is not a legal UTF-8 sequence start, so this payload is
#: undecodable source on every platform.
UNDECODABLE_BYTES = b"# \xff\xfe not utf-8\n"

BASELINE_RECORD: dict[str, Any] = {
    "schema_version": 1,
    "recorded_at": "2026-09-02",
    "repository_revision": "ef05745d7d35a14182730a095df0c62f78b5d56d",
    "baseline_passing_backend_tests": BASELINE,
    "frontend_typecheck": "pass",
    "frontend_production_build": "pass",
    "commands": {
        "backend_tests": "python -m pytest -q",
        "frontend_typecheck": "npm --prefix frontend run typecheck",
        "frontend_build": "npm --prefix frontend run build",
    },
}


# ---------------------------------------------------------------------------
# Generated repository model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GeneratedInput:
    """One required runtime input, its discovery origin, and its repository state."""

    index: int
    origin: str
    state: str

    @property
    def path(self) -> str:
        if self.origin == "models":
            return f"app/models/generated_{self.index}.py"
        if self.origin == "frontend_build":
            return f"frontend/src/generated_{self.index}.ts"
        return f"app/generated_{self.index}.py"

    @property
    def import_line(self) -> str:
        if self.origin == "models":
            return f"import app.models.generated_{self.index}\n"
        if self.origin == "frontend_build":
            return f"import './generated_{self.index}';\n"
        return f"import app.generated_{self.index}\n"

    @property
    def content(self) -> str:
        if self.origin == "frontend_build":
            return f"export const value = {self.index};\n"
        return f"VALUE = {self.index}\n"

    @property
    def expected_evidence(self) -> set[tuple[str, str]]:
        """The (kind, origin) evidence pairs the guard must record for this input."""

        if self.origin == "models":
            # Reached both by the models tree walk and by the package import.
            evidence = {("python_import", "app/models/__init__.py")}
            if self.state != "MISSING":
                evidence.add(("application_models", "app/models"))
            return evidence
        if self.origin == "frontend_build":
            evidence = {("frontend_import", self.path)}
            if self.state != "MISSING":
                evidence.add(("frontend_source_tree", self.path))
            return evidence
        return {("python_import", PYTHON_IMPORTERS[self.origin])}


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_bytes(root: Path, relative: str, payload: bytes) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _git(root: Path, *args: str) -> None:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def _imports(generated: Sequence[GeneratedInput], origin: str) -> str:
    return "".join(item.import_line for item in generated if item.origin == origin)


def _build_repository(root: Path, generated: Sequence[GeneratedInput]) -> dict[str, int]:
    """Create a small Git repository whose manifests require ``generated``.

    Returns the ``.gitignore`` line number of each rule written for a generated
    input, so the guard's reported rule provenance can be checked exactly.
    """

    rules = list(BASE_IGNORE_RULES)
    ignore_lines: dict[str, int] = {}
    for item in generated:
        if item.state == "IGNORED":
            rules.append(f"/{item.path}")
            ignore_lines[item.path] = len(rules)
    _write(root, ".gitignore", "\n".join(rules) + "\n")

    _write(root, "requirements.txt", "pytest==8.4.2\n")
    _write(root, "app/__init__.py", "")
    _write(root, "app/main.py", _imports(generated, "startup"))
    _write(root, "app/api/__init__.py", "")
    _write(root, "app/api/router.py", _imports(generated, "api_route"))
    _write(root, "app/models/__init__.py", _imports(generated, "models"))
    _write(root, "alembic.ini", "[alembic]\nscript_location = alembic\n")
    _write(root, "alembic/env.py", _imports(generated, "migration"))
    _write(root, "alembic/script.py.mako", "revision = None\n")
    _write(root, "alembic/versions/20260101_01_initial.py", "revision = '20260101_01'\ndown_revision = None\n")
    _write(root, "scripts/check.py", _imports(generated, "script"))
    _write(root, "tests/test_runtime.py", _imports(generated, "test"))
    _write(root, "frontend/package.json", '{"name": "ui", "scripts": {"build": "vite build"}}\n')
    _write(root, "frontend/index.html", '<script type="module" src="/src/main.ts"></script>\n')
    _write(root, "frontend/src/main.ts", _imports(generated, "frontend_build"))

    for item in generated:
        if item.state in {"TRACKED", "LATENT_IGNORED"}:
            _write(root, item.path, item.content)
        elif item.state == "UNDECODABLE":
            _write_bytes(root, item.path, UNDECODABLE_BYTES)

    _git(root, "init", "--quiet")
    _git(root, "add", "--all")

    # A latent rule is added only after its file is already tracked: Git keeps a
    # tracked path in every checkout, so such a rule is evidence rather than an
    # effective exclusion (Requirement 1.3).
    latent = [item for item in generated if item.state == "LATENT_IGNORED"]
    if latent:
        for item in latent:
            rules.append(f"/{item.path}")
            ignore_lines[item.path] = len(rules)
        _write(root, ".gitignore", "\n".join(rules) + "\n")

    for item in generated:
        if item.state in {"UNTRACKED", "IGNORED"}:
            _write(root, item.path, item.content)

    return ignore_lines


# ---------------------------------------------------------------------------
# Release evidence documents
# ---------------------------------------------------------------------------


def _replacement_record(removed_test: str) -> dict[str, Any]:
    return {
        "removed_test": removed_test,
        "removal_reason": "the behavior it described was superseded by an approved change",
        "retained_coverage": ["tests/test_example.py::test_equivalent_case"],
        "reviewer": "release reviewer",
        "reviewed_at": "2026-09-02",
    }


def _write_release_docs(root: Path, *, replacements: list[dict[str, Any]] | None = None) -> Path:
    """Write a reviewed docs/release pair with a valid baseline and empty inventory."""

    docs = root / "docs" / "release"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "baseline-evidence.md").write_text(
        f"# Baseline\n\n<!-- {BASELINE_MARKER} -->\n\n"
        f"```json\n{json.dumps(BASELINE_RECORD, indent=2)}\n```\n\n"
        f"## Replacement coverage\n\n<!-- {REPLACEMENT_COVERAGE_MARKER} -->\n\n"
        f"```json\n{json.dumps(replacements or [], indent=2)}\n```\n",
        encoding="utf-8",
    )
    (docs / "cleanup-inventory.md").write_text(
        f"# Inventory\n\n<!-- {INVENTORY_MARKER} -->\n\n```json\n[]\n```\n",
        encoding="utf-8",
    )
    return docs


def _passing_tracking_report() -> dict[str, Any]:
    """A Source Tracking Guard report in which every required input is tracked."""

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "pass",
        "git": {"available": True},
        "required_files": [
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
            }
        ],
        "summary": {"failed": 0, "required": 1},
        "tool_errors": [],
    }


def _check(report: dict[str, Any], name: str) -> dict[str, Any]:
    return next(item for item in report["checks"] if item["name"] == name)


@pytest.fixture(scope="module")
def release_docs(tmp_path_factory) -> Path:
    """One reviewed evidence pair shared by every generated repository case."""

    return _write_release_docs(tmp_path_factory.mktemp("release-docs"))


# ---------------------------------------------------------------------------
# Property 1, first half: discovered runtime source is closed and release-tracked
# ---------------------------------------------------------------------------


@given(
    plan=st.lists(
        st.tuples(st.sampled_from(ORIGINS), st.sampled_from(STATES)),
        max_size=4,
    )
)
@settings(max_examples=100, deadline=None)
def test_discovered_runtime_source_is_reported_with_evidence_and_must_be_release_tracked(
    release_docs: Path, plan: list[tuple[str, str]]
):
    """Discovery is closed over the manifests, and any gap blocks the release inputs.

    # Feature: production-readiness-cleanup, Property 1: Runtime source and release baseline are closed
    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 15.1, 17.1, 17.5, 17.7**
    """

    generated = [GeneratedInput(index=index, origin=origin, state=state) for index, (origin, state) in enumerate(plan)]

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        ignore_lines = _build_repository(root, generated)
        report = build_report(root)

        findings = {item["path"]: item for item in report["required_files"]}

        # Discovery is exactly the closure of the supported manifests.
        assert set(findings) == BASE_REQUIRED_PATHS | {item.path for item in generated}

        for finding in report["required_files"]:
            # Every required input carries discovery evidence, and no evidence
            # item is anonymous (Requirements 1.1, 1.4, 1.5).
            assert finding["required"] is True
            assert finding["discovery_evidence"]
            assert all(item["kind"] and item["origin"] for item in finding["discovery_evidence"])

            # Reported paths stay repository-relative so the report is safe to
            # retain as release evidence (Requirement 17.1).
            assert not Path(finding["path"]).is_absolute()
            assert ".." not in finding["path"].split("/")

            # Failure reporting is exhaustive and self-consistent.
            assert (not finding["tracked"]) == ("UNTRACKED" in finding["errors"])
            assert (not finding["exists"]) == ("MISSING" in finding["errors"])
            assert finding["ignored"] == (finding["matching_ignore_rule"] is not None and not finding["tracked"])
            assert finding["ignored"] == ("IGNORED" in finding["errors"])

        assert (report["status"] == "pass") == all(not item["errors"] for item in report["required_files"])
        assert report["summary"]["failed"] == sum(bool(item["errors"]) for item in report["required_files"])
        assert report["summary"]["required"] == len(report["required_files"])
        assert root.as_posix() not in json.dumps(report)

        # The base manifests themselves are always tracked and rule-free. The
        # root-anchored /models/ artefact rule never touches app/models/.
        for path in BASE_REQUIRED_PATHS:
            assert findings[path]["errors"] == []
            assert findings[path]["matching_ignore_rule"] is None

        for item in generated:
            finding = findings[item.path]
            evidence = {(entry["kind"], entry["origin"]) for entry in finding["discovery_evidence"]}

            assert item.expected_evidence <= evidence
            assert finding["errors"] == EXPECTED_ERRORS[item.state]

            if item.state in {"IGNORED", "LATENT_IGNORED"}:
                assert finding["matching_ignore_rule"] == {
                    "line": ignore_lines[item.path],
                    "pattern": f"/{item.path}",
                    "source": ".gitignore",
                }
            else:
                assert finding["matching_ignore_rule"] is None

        # An untracked, ignored, missing, or unreadable required input keeps the
        # release inputs from being ready (Requirements 1.5, 17.5, 17.7).
        release = build_release_input_report(
            root,
            observed_passing_backend_tests=BASELINE,
            tracking_report=report,
            release_docs_root=release_docs,
        )
        tracking_check = _check(release, "source_tracking")

        assert (release["status"] == "ready") == (report["status"] == "pass")
        assert (tracking_check["status"] == "pass") == (report["status"] == "pass")
        if report["status"] != "pass":
            assert "source_tracking:REQUIRED_RUNTIME_SOURCE_NOT_RELEASE_TRACKED" in release["blocking_reasons"]
            failing = {item["path"] for item in report["required_files"] if item["errors"]}
            assert {item["path"] for item in tracking_check["findings"]} == failing
            assert all(item["discovery_evidence"] for item in tracking_check["findings"])


# ---------------------------------------------------------------------------
# Property 1, second half: the 595 baseline gate needs replacement coverage
# ---------------------------------------------------------------------------


@given(
    observed=st.one_of(
        st.integers(min_value=BASELINE - 8, max_value=BASELINE + 8),
        st.sampled_from([0, 1, BASELINE // 2, BASELINE * 2]),
    ),
    complete=st.integers(min_value=0, max_value=6),
    incomplete=st.integers(min_value=0, max_value=2),
    duplicated=st.booleans(),
)
@settings(max_examples=200, deadline=None)
def test_backend_test_count_below_the_baseline_needs_complete_replacement_coverage(
    observed: int, complete: int, incomplete: int, duplicated: bool
):
    """Readiness below 595 requires reviewed replacement coverage for the whole shortfall.

    # Feature: production-readiness-cleanup, Property 1: Runtime source and release baseline are closed
    **Validates: Requirements 1.6, 1.7, 15.1, 17.2, 17.5**
    """

    records = [_replacement_record(f"tests/test_removed.py::test_case_{index}") for index in range(complete)]
    if duplicated and records:
        records.append(dict(records[0]))
    for index in range(incomplete):
        broken = _replacement_record(f"tests/test_removed.py::test_incomplete_{index}")
        del broken["retained_coverage"]
        records.append(broken)

    coverage_is_complete = incomplete == 0 and not (duplicated and complete)
    justified = complete if coverage_is_complete else 0
    deficit = max(BASELINE - observed, 0)
    gate_passes = deficit == 0 or justified >= deficit

    with tempfile.TemporaryDirectory() as temporary:
        docs = _write_release_docs(Path(temporary), replacements=records)
        report = build_release_input_report(
            temporary,
            observed_passing_backend_tests=observed,
            tracking_report=_passing_tracking_report(),
            release_docs_root=docs,
        )

    gate = _check(report, "backend_test_baseline")
    coverage = _check(report, "replacement_coverage")

    # The approved baseline is the comparison point and cannot be lowered, and the
    # observed count is retained in the record (Requirements 1.6, 17.2).
    assert gate["baseline"] == BASELINE
    assert gate["observed_passing_backend_tests"] == observed
    assert gate["deficit"] == deficit
    assert gate["justified_removals"] == justified
    assert (gate["status"] == "pass") == gate_passes
    assert (coverage["status"] == "pass") == coverage_is_complete

    # Per-record acceptance counts a repeated identity once and never accepts an
    # incomplete record. It stays diagnostic: while any review error stands, the
    # gate credits no removal at all, which is what ``justified_removals`` shows.
    assert coverage["records"] == len(records)
    assert coverage["accepted_removed_tests"] == sorted(
        f"tests/test_removed.py::test_case_{index}" for index in range(complete)
    )

    assert (report["status"] == "ready") == (gate_passes and coverage_is_complete)
    if not gate_passes:
        assert "backend_test_baseline:BACKEND_TEST_COUNT_BELOW_BASELINE" in report["blocking_reasons"]
    if observed < BASELINE and justified < deficit:
        assert report["status"] == "not_ready"


# ---------------------------------------------------------------------------
# The portable unreadable-input case, stated once as an example
# ---------------------------------------------------------------------------


def test_required_source_that_cannot_be_decoded_is_reported_unreadable(tmp_path: Path):
    """An imported file that is not valid UTF-8 is an unreadable required input.

    The file is tracked and its bytes are readable, so only the decode failure
    can explain the finding (Requirement 1.5).
    """

    generated = [GeneratedInput(index=0, origin="startup", state="UNDECODABLE")]
    _build_repository(tmp_path, generated)

    report = build_report(tmp_path)
    finding = next(item for item in report["required_files"] if item["path"] == "app/generated_0.py")

    assert report["status"] == "fail"
    assert finding["errors"] == ["UNREADABLE"]
    assert finding["exists"] is True
    assert finding["tracked"] is True
