"""Release guard for tracked, readable runtime source inputs.

The guard performs static, non-mutating discovery from the supported Python,
Alembic, test, script, and frontend build entrypoints.  It deliberately emits
only repository-relative paths and classification metadata so its JSON report
can be retained as release evidence without exposing source contents, secrets,
or local environment values.

Ignore reporting distinguishes two states.  ``matching_ignore_rule`` records the
provenance of any working-tree ignore rule that matches a required input, and
``ignored`` is true only when such a rule matches an input Git does not track --
the case that actually withholds the input from a checkout and therefore fails
release validation.
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Sequence
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


SCHEMA_VERSION = 1
LOCAL_PYTHON_PACKAGES = frozenset({"app", "scripts", "tests"})
PYTHON_SUFFIXES = (".py",)
FRONTEND_SOURCE_SUFFIXES = frozenset({".css", ".js", ".jsx", ".ts", ".tsx"})
FRONTEND_RESOLUTION_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".css", ".json")
IMPORT_PATTERN = re.compile(
    r"(?:^|[;\n])\s*(?:import\s+(?:type\s+)?|export\s+[^;\n]*?\s+from\s+)['\"]([^'\"]+)['\"]",
    re.MULTILINE,
)
DYNAMIC_IMPORT_PATTERN = re.compile(r"\bimport\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")
CSS_IMPORT_PATTERN = re.compile(r"@import\s+(?:url\()?['\"]([^'\"]+)['\"]")
CSS_URL_PATTERN = re.compile(r"url\(\s*['\"]?([^'\")\s]+)")
HTML_REFERENCE_PATTERN = re.compile(r"\b(?:src|href)\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)

# An ignore rule can live outside the repository (for example a user-level
# excludes file).  Release evidence records that fact without embedding a local
# filesystem path.
EXTERNAL_IGNORE_SOURCE = "external_excludes_file"


def _strip_jsonc(text: str) -> str:
    """Return ``text`` with JSONC comments and trailing commas removed.

    The scan is character-by-character rather than regular-expression based so a
    comment marker or comma inside a string literal is preserved verbatim.
    """

    output: list[str] = []
    index = 0
    length = len(text)
    in_string = False

    while index < length:
        char = text[index]
        if in_string:
            output.append(char)
            if char == "\\" and index + 1 < length:
                output.append(text[index + 1])
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "/":
            while index < length and text[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "*":
            index += 2
            while index + 1 < length and not (text[index] == "*" and text[index + 1] == "/"):
                index += 1
            index += 2
            continue
        if char in "}]":
            trailing = len(output) - 1
            while trailing >= 0 and output[trailing].isspace():
                trailing -= 1
            if trailing >= 0 and output[trailing] == ",":
                del output[trailing]
        output.append(char)
        index += 1

    return "".join(output)


@dataclass
class RequiredFile:
    """A discovered source input and its evidence, stored without file content."""

    path: str
    evidence: list[dict[str, str]] = field(default_factory=list)
    discovery_errors: set[str] = field(default_factory=set)

    def add_evidence(self, *, kind: str, origin: str) -> None:
        item = {"kind": kind, "origin": origin}
        if item not in self.evidence:
            self.evidence.append(item)


class SourceDiscovery:
    """Collect local runtime inputs while retaining the origin of every edge."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.files: dict[str, RequiredFile] = {}
        self._visited_python: set[str] = set()
        self._visited_frontend: set[str] = set()
        self._visited_tsconfigs: set[str] = set()

    def discover(self) -> dict[str, RequiredFile]:
        self._seed_python_runtime()
        self._seed_alembic()
        self._seed_scripts_and_tests()
        self._seed_frontend()
        return self.files

    def _seed_python_runtime(self) -> None:
        self._add_python_file(self.root / "app" / "main.py", "python_startup", "app/main.py")
        self._add_python_file(self.root / "app" / "api" / "router.py", "api_router", "app/api/router.py")

        # Models are loaded by Alembic and application startup.  This explicit
        # classification is intentionally independent from a root-level /models/
        # ignore rule, which only concerns generated model artifacts.
        models_root = self.root / "app" / "models"
        model_files = sorted(models_root.rglob("*.py")) if models_root.is_dir() else []
        if not model_files:
            self._add_file(models_root / "__init__.py", "application_models", "app/models")
        for path in model_files:
            self._add_python_file(path, "application_models", "app/models")

        self._add_file(self.root / "requirements.txt", "python_dependency_manifest", "requirements.txt")

    def _seed_alembic(self) -> None:
        self._add_file(self.root / "alembic.ini", "alembic_configuration", "alembic.ini")
        self._add_python_file(self.root / "alembic" / "env.py", "alembic_environment", "alembic.ini")
        self._add_file(self.root / "alembic" / "script.py.mako", "alembic_template", "alembic")
        versions_root = self.root / "alembic" / "versions"
        for path in sorted(versions_root.rglob("*.py")) if versions_root.is_dir() else []:
            self._add_python_file(path, "alembic_revision", "alembic/versions")

    def _seed_scripts_and_tests(self) -> None:
        for directory, kind in (("scripts", "supported_script"), ("tests", "supported_test")):
            source_root = self.root / directory
            for path in sorted(source_root.rglob("*.py")) if source_root.is_dir() else []:
                self._add_python_file(path, kind, directory)

    def _seed_frontend(self) -> None:
        frontend_root = self.root / "frontend"
        if not frontend_root.is_dir():
            return

        package_path = frontend_root / "package.json"
        self._add_file(package_path, "frontend_build_manifest", "frontend/package.json")
        if package_path.is_file():
            self._parse_json_file(package_path, "INVALID_FRONTEND_PACKAGE_JSON")

        lock_path = frontend_root / "package-lock.json"
        if lock_path.exists():
            self._add_file(lock_path, "frontend_lockfile", "frontend/package.json")

        index_path = frontend_root / "index.html"
        self._add_file(index_path, "frontend_build_entrypoint", "frontend/package.json")
        self._walk_frontend_file(index_path, "frontend_html_reference")

        for config_name in ("vite.config.ts", "postcss.config.js", "tailwind.config.js"):
            config_path = frontend_root / config_name
            if config_path.exists():
                self._walk_frontend_file(config_path, "frontend_build_config")

        for config_path in sorted(frontend_root.glob("tsconfig*.json")):
            self._add_file(config_path, "frontend_typescript_config", "frontend/package.json")
            self._walk_tsconfig(config_path)

        source_root = frontend_root / "src"
        for path in sorted(source_root.rglob("*")) if source_root.is_dir() else []:
            if path.is_file() and path.suffix in FRONTEND_SOURCE_SUFFIXES:
                self._walk_frontend_file(path, "frontend_source_tree")

        public_root = frontend_root / "public"
        for path in sorted(public_root.rglob("*")) if public_root.is_dir() else []:
            if path.is_file():
                self._add_file(path, "frontend_static_asset", "frontend/public")

    def _walk_tsconfig(self, path: Path) -> None:
        relative = self._relative(path)
        if relative in self._visited_tsconfigs:
            return
        self._visited_tsconfigs.add(relative)
        value = self._parse_json_file(path, "INVALID_TYPESCRIPT_CONFIG", tolerate_comments=True)
        if not isinstance(value, dict):
            return

        references = value.get("references", [])
        if isinstance(references, list):
            for reference in references:
                if not isinstance(reference, dict) or not isinstance(reference.get("path"), str):
                    continue
                target = self._resolve_config_reference(path.parent, reference["path"])
                self._add_file(target, "typescript_project_reference", relative)
                self._walk_tsconfig(target)

        extends = value.get("extends")
        if isinstance(extends, str) and extends.startswith((".", "/")):
            target = self._resolve_config_reference(path.parent, extends)
            self._add_file(target, "typescript_config_extends", relative)
            self._walk_tsconfig(target)

    @staticmethod
    def _resolve_config_reference(base: Path, reference: str) -> Path:
        target = base / reference
        if target.suffix:
            return target
        return target / "tsconfig.json" if target.is_dir() else target.with_suffix(".json")

    def _walk_frontend_file(self, path: Path, kind: str) -> None:
        self._add_file(path, kind, self._relative_or(path, "frontend"))
        relative = self._relative(path)
        if relative in self._visited_frontend:
            return
        self._visited_frontend.add(relative)

        text = self._read_text(path)
        if text is None:
            return

        suffix = path.suffix.lower()
        if suffix in {".ts", ".tsx", ".js", ".jsx"}:
            specifiers = [match.group(1) for match in IMPORT_PATTERN.finditer(text)]
            specifiers.extend(match.group(1) for match in DYNAMIC_IMPORT_PATTERN.finditer(text))
            for specifier in specifiers:
                self._add_frontend_specifier(path, specifier, "frontend_import")
        elif suffix == ".css":
            specifiers = [match.group(1) for match in CSS_IMPORT_PATTERN.finditer(text)]
            specifiers.extend(match.group(1) for match in CSS_URL_PATTERN.finditer(text))
            for specifier in specifiers:
                self._add_frontend_specifier(path, specifier, "frontend_asset_reference")
        elif suffix == ".html":
            for match in HTML_REFERENCE_PATTERN.finditer(text):
                self._add_frontend_specifier(path, match.group(1), "frontend_html_reference")

    def _add_frontend_specifier(self, importer: Path, specifier: str, kind: str) -> None:
        if not specifier or specifier.startswith(("#", "data:", "http:", "https:", "//")):
            return
        target = self._resolve_frontend_specifier(importer, specifier)
        if target is None:
            return
        self._walk_frontend_file(target, kind)

    def _resolve_frontend_specifier(self, importer: Path, specifier: str) -> Path | None:
        frontend_root = self.root / "frontend"
        clean = specifier.split("?", 1)[0].split("#", 1)[0]
        if not clean:
            return None
        if clean.startswith("@/"):
            candidate = frontend_root / "src" / clean[2:]
        elif clean.startswith("/"):
            if clean.startswith("/src/"):
                candidate = frontend_root / clean.lstrip("/")
            else:
                candidate = frontend_root / "public" / clean.lstrip("/")
        elif clean.startswith("."):
            candidate = importer.parent / clean
        else:
            return None
        return self._resolve_frontend_path(candidate)

    @staticmethod
    def _resolve_frontend_path(candidate: Path) -> Path:
        if candidate.is_file() or candidate.suffix:
            return candidate
        for suffix in FRONTEND_RESOLUTION_SUFFIXES:
            with_suffix = candidate.with_suffix(suffix)
            if with_suffix.is_file():
                return with_suffix
        for suffix in FRONTEND_RESOLUTION_SUFFIXES:
            index_path = candidate / f"index{suffix}"
            if index_path.is_file():
                return index_path
        # Preserve an unresolved relative/alias import as a failed required input.
        return candidate.with_suffix(".ts")

    def _add_python_file(self, path: Path, kind: str, origin: str) -> None:
        self._add_file(path, kind, origin)
        self._walk_python_file(path)

    def _walk_python_file(self, path: Path) -> None:
        relative = self._relative(path)
        if relative in self._visited_python:
            return
        self._visited_python.add(relative)
        text = self._read_text(path)
        if text is None:
            return
        try:
            tree = ast.parse(text, filename=relative)
        except SyntaxError:
            self._record_error(path, "INVALID_PYTHON")
            return

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self._add_local_module(alias.name, path)
            elif isinstance(node, ast.ImportFrom):
                module = self._import_from_module(node, path)
                if module is None:
                    continue
                self._add_local_module(module, path)
                for alias in node.names:
                    self._add_existing_child_module(module, alias.name, path)

    def _import_from_module(self, node: ast.ImportFrom, importer: Path) -> str | None:
        if node.level == 0:
            return node.module
        relative = self._relative(importer)
        parts = list(Path(relative).with_suffix("").parts)
        package_parts = parts[:-1]
        if Path(relative).name == "__init__.py":
            package_parts = parts[:-1]
        keep = len(package_parts) - (node.level - 1)
        if keep <= 0:
            return None
        base = package_parts[:keep]
        if node.module:
            base.extend(node.module.split("."))
        return ".".join(base)

    def _add_existing_child_module(self, module: str, child: str, importer: Path) -> None:
        if child == "*":
            return
        candidate = self._module_path(f"{module}.{child}", allow_missing=False)
        if candidate is not None:
            self._add_python_file(candidate, "python_import", self._relative(importer))

    def _add_local_module(self, module: str | None, importer: Path) -> None:
        if not module or module.split(".", 1)[0] not in LOCAL_PYTHON_PACKAGES:
            return
        target = self._module_path(module, allow_missing=True)
        if target is not None:
            self._add_python_file(target, "python_import", self._relative(importer))

    def _module_path(self, module: str, *, allow_missing: bool) -> Path | None:
        parts = module.split(".")
        if not parts or parts[0] not in LOCAL_PYTHON_PACKAGES:
            return None
        base = self.root.joinpath(*parts)
        file_candidate = base.with_suffix(".py")
        package_candidate = base / "__init__.py"
        if file_candidate.is_file():
            return file_candidate
        if package_candidate.is_file():
            return package_candidate
        return file_candidate if allow_missing else None

    def _add_file(self, path: Path, kind: str, origin: str) -> None:
        relative = self._relative(path)
        record = self.files.setdefault(relative, RequiredFile(path=relative))
        record.add_evidence(kind=kind, origin=origin)

    def _record_error(self, path: Path, error: str) -> None:
        relative = self._relative(path)
        record = self.files.setdefault(relative, RequiredFile(path=relative))
        record.discovery_errors.add(error)

    def _read_text(self, path: Path) -> str | None:
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            self._record_error(path, "UNREADABLE")
            return None

    def _parse_json_file(self, path: Path, error: str, *, tolerate_comments: bool = False) -> Any:
        """Parse a build-configuration file, recording genuinely malformed input.

        A manifest the build cannot parse is a discovery failure rather than a
        silent no-op, because the inputs it declares stay undiscovered.
        ``tolerate_comments`` applies to TypeScript configuration, which the
        compiler reads as JSONC: comments and trailing commas are valid there and
        must not be reported as malformed.
        """

        text = self._read_text(path)
        if text is None:
            return None
        try:
            return json.loads(_strip_jsonc(text) if tolerate_comments else text)
        except json.JSONDecodeError:
            self._record_error(path, error)
            return None

    def _relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            # An out-of-repository path can never be a reproducible release input.
            return path.absolute().as_posix()

    def _relative_or(self, path: Path, default: str) -> str:
        try:
            return self._relative(path)
        except ValueError:
            return default


def _run_git(root: Path, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _run_git_bytes(root: Path, args: Sequence[str], *, stdin_data: bytes) -> subprocess.CompletedProcess[bytes]:
    # Byte-mode stdin is required for NUL-delimited path input: text mode
    # rewrites "\n" to the platform line separator, which appends a carriage
    # return to each path on Windows and silently defeats path matching.
    return subprocess.run(
        ["git", "-C", str(root), *args],
        input=stdin_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _git_inventory(root: Path) -> tuple[set[str], bool]:
    probe = _run_git(root, ["rev-parse", "--is-inside-work-tree"])
    if probe.returncode != 0 or probe.stdout.strip().lower() != "true":
        return set(), False
    tracked = _run_git(root, ["ls-files", "-z"])
    if tracked.returncode != 0:
        return set(), False
    return {entry.replace("\\", "/") for entry in tracked.stdout.split("\0") if entry}, True


def _is_repository_relative(relative_path: str) -> bool:
    """Return whether ``relative_path`` can be handed to Git as a repository path.

    Discovery falls back to an absolute path when a reference escapes the
    repository.  Git rejects such a path and aborts the whole batch, so those
    paths are excluded here; they are already reported as untracked.
    """

    if not relative_path or relative_path.startswith("/"):
        return False
    if Path(relative_path).is_absolute() or ":" in relative_path.split("/", 1)[0]:
        return False
    return ".." not in relative_path.split("/")


def _normalize_ignore_source(root: Path, source: str) -> str:
    candidate = Path(source)
    if not candidate.is_absolute():
        return source.replace("\\", "/")
    try:
        return candidate.resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        return EXTERNAL_IGNORE_SOURCE


def _ignore_provenance_map(
    root: Path,
    relative_paths: Sequence[str],
    *,
    git_available: bool,
) -> dict[str, dict[str, Any]]:
    """Return the effective ignore rule matching each path, keyed by path.

    ``--no-index`` makes Git evaluate the working-tree rule set alone, so the
    reported provenance does not depend on whether a path happens to be staged.
    ``-z`` keeps the four output fields unambiguous for patterns or paths that
    contain a colon or a tab.  One batched call keeps the report cheap for the
    several hundred inputs a supported release discovers.
    """

    if not git_available:
        return {}
    candidates = [path for path in relative_paths if _is_repository_relative(path)]
    if not candidates:
        return {}

    stdin_data = b"".join(f"{path}\0".encode() for path in candidates)
    result = _run_git_bytes(root, ["check-ignore", "--no-index", "-z", "-v", "--stdin"], stdin_data=stdin_data)
    # Exit status 1 means no candidate matched a rule; any other nonzero status
    # is a Git error, and whatever was emitted before it is still valid.
    fields = result.stdout.decode("utf-8", errors="replace").split("\0")

    provenance: dict[str, dict[str, Any]] = {}
    for index in range(0, len(fields) - 3, 4):
        source, line_number, pattern, matched_path = fields[index : index + 4]
        if not matched_path:
            continue
        try:
            parsed_line: int | None = int(line_number)
        except ValueError:
            parsed_line = None
        provenance[matched_path.replace("\\", "/")] = {
            "line": parsed_line,
            "pattern": pattern,
            "source": _normalize_ignore_source(root, source),
        }
    return provenance


def _is_readable(path: Path) -> bool:
    try:
        with path.open("rb") as source:
            source.read(1)
        return True
    except OSError:
        return False


def build_report(root: Path | str) -> dict[str, Any]:
    """Build a stable, non-secret tracking report for ``root``.

    The function is deliberately side-effect free: it only reads repository files
    and Git metadata.  Callers can serialize the returned data directly as
    release evidence.
    """

    repository_root = Path(root).resolve()
    if not repository_root.is_dir():
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "fail",
            "git": {"available": False},
            "required_files": [],
            "summary": {"failed": 1, "required": 0},
            "tool_errors": ["INVALID_REPOSITORY_ROOT"],
        }

    discovery = SourceDiscovery(repository_root)
    required = discovery.discover()
    tracked_files, git_available = _git_inventory(repository_root)
    ignore_rules = _ignore_provenance_map(repository_root, sorted(required), git_available=git_available)
    findings: list[dict[str, Any]] = []

    for relative_path in sorted(required):
        record = required[relative_path]
        path = repository_root / Path(relative_path)
        errors = set(record.discovery_errors)
        exists = path.is_file()
        readable = exists and _is_readable(path)
        if not exists:
            errors.add("MISSING")
        elif not readable:
            errors.add("UNREADABLE")

        if not git_available:
            tracked = False
            errors.add("GIT_UNAVAILABLE")
        else:
            tracked = relative_path in tracked_files
            if not tracked:
                errors.add("UNTRACKED")

        # A rule is reported whenever it matches, but it only *effectively*
        # ignores a required input that Git is not already tracking: a tracked
        # path is present in every checkout, so a broad legacy pattern is latent
        # rather than release-blocking.
        matching_rule = ignore_rules.get(relative_path)
        ignored = matching_rule is not None and not tracked
        if ignored:
            errors.add("IGNORED")

        findings.append(
            {
                "discovery_evidence": sorted(record.evidence, key=lambda item: (item["kind"], item["origin"])),
                "errors": sorted(errors),
                "exists": exists,
                "ignored": ignored,
                "matching_ignore_rule": matching_rule,
                "path": relative_path,
                "readable": readable,
                "required": True,
                "tracked": tracked,
            }
        )

    failed = sum(bool(item["errors"]) for item in findings)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "pass" if failed == 0 else "fail",
        "git": {"available": git_available},
        "required_files": findings,
        "summary": {"failed": failed, "required": len(findings)},
        "tool_errors": [] if git_available else ["GIT_UNAVAILABLE"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report whether required runtime sources are tracked and readable.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root to inspect (defaults to the repository containing this script)",
    )
    args = parser.parse_args(argv)
    report = build_report(args.root)
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
