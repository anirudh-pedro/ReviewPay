"""Focused coverage for the release source-tracking guard."""

from __future__ import annotations

from pathlib import Path
import subprocess

from scripts.source_tracking_guard import build_report


def _write(root: Path, relative_path: str, content: str = "") -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _git(root: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _runtime_repository(tmp_path: Path) -> Path:
    root = tmp_path / "runtime-repository"
    root.mkdir()
    _write(root, ".gitignore", "/models/\n")
    _write(root, "requirements.txt", "pytest==8.4.2\n")
    _write(root, "app/__init__.py")
    _write(root, "app/main.py", "from app.models import Payment\n")
    _write(root, "app/api/__init__.py")
    _write(root, "app/api/router.py", "from app.models import Payment\n")
    _write(root, "app/models/__init__.py", "from app.models.payment import Payment\n")
    _write(root, "app/models/payment.py", "class Payment:\n    pass\n")
    _write(root, "alembic.ini", "[alembic]\nscript_location = alembic\n")
    _write(root, "alembic/env.py", "from app.models import Payment\n")
    _write(root, "alembic/script.py.mako", "revision = None\n")
    _write(root, "alembic/versions/20260101_01_initial.py", "revision = 'initial'\n")
    _write(root, "scripts/check.py", "from app.models import Payment\n")
    _write(root, "tests/test_runtime.py", "from app.models import Payment\n")
    _git(root, "init", "--quiet")
    _git(root, "add", "--all")
    return root


def _finding(report: dict, relative_path: str) -> dict:
    return next(item for item in report["required_files"] if item["path"] == relative_path)


def test_models_are_required_and_not_confused_with_root_model_artifact_ignore(tmp_path: Path):
    root = _runtime_repository(tmp_path)

    first = build_report(root)
    second = build_report(root)
    payment = _finding(first, "app/models/payment.py")

    assert first == second
    assert first["status"] == "pass"
    assert payment["tracked"] is True
    assert payment["ignored"] is False
    assert payment["matching_ignore_rule"] is None
    assert {item["kind"] for item in payment["discovery_evidence"]} >= {"application_models"}
    assert str(root) not in str(first)


def test_missing_local_runtime_import_fails_with_import_evidence(tmp_path: Path):
    root = _runtime_repository(tmp_path)
    _write(root, "app/main.py", "import app.required_but_missing\n")

    report = build_report(root)
    missing = _finding(report, "app/required_but_missing.py")

    assert report["status"] == "fail"
    assert {"MISSING", "UNTRACKED"} <= set(missing["errors"])
    assert {"python_import"} <= {item["kind"] for item in missing["discovery_evidence"]}


def test_untracked_effectively_ignored_runtime_file_reports_rule_provenance(tmp_path: Path):
    root = _runtime_repository(tmp_path)
    _write(root, ".gitignore", "/models/\n/app/ignored_runtime.py\n")
    _write(root, "app/main.py", "import app.ignored_runtime\n")
    _write(root, "app/ignored_runtime.py", "VALUE = 1\n")

    report = build_report(root)
    ignored = _finding(report, "app/ignored_runtime.py")

    assert report["status"] == "fail"
    assert ignored["tracked"] is False
    assert ignored["ignored"] is True
    assert ignored["matching_ignore_rule"] == {
        "line": 2,
        "pattern": "/app/ignored_runtime.py",
        "source": ".gitignore",
    }
    assert {"IGNORED", "UNTRACKED"} <= set(ignored["errors"])


def test_tracked_runtime_file_reports_latent_rule_without_failing(tmp_path: Path):
    root = _runtime_repository(tmp_path)
    _write(root, "app/models/legacy.py", "VALUE = 1\n")
    _write(root, "app/models/__init__.py", "from app.models import legacy\n")
    _git(root, "add", "--all")
    _write(root, ".gitignore", "/models/\napp/models/legacy.py\n")

    report = build_report(root)
    legacy = _finding(report, "app/models/legacy.py")

    # Git keeps a tracked path in every checkout, so the rule is latent evidence
    # rather than an effective exclusion that blocks the release.
    assert legacy["tracked"] is True
    assert legacy["ignored"] is False
    assert legacy["matching_ignore_rule"] == {
        "line": 2,
        "pattern": "app/models/legacy.py",
        "source": ".gitignore",
    }
    assert "IGNORED" not in legacy["errors"]
    assert report["status"] == "pass"


def test_frontend_build_inputs_are_discovered_from_jsonc_typescript_config(tmp_path: Path):
    root = _runtime_repository(tmp_path)
    _write(root, "frontend/package.json", '{"name": "ui", "scripts": {"build": "vite build"}}\n')
    _write(root, "frontend/index.html", '<script type="module" src="/src/main.tsx"></script>\n')
    # TypeScript reads configuration as JSONC: comments and trailing commas are
    # valid input and must not be reported as a malformed build manifest.
    _write(
        root,
        "frontend/tsconfig.json",
        '{\n  /* project layout */\n  "files": [],\n'
        '  "references": [{ "path": "./tsconfig.app.json" }],\n}\n',
    )
    _write(root, "frontend/tsconfig.app.json", '{\n  // strict mode\n  "include": ["src"],\n}\n')
    _write(root, "frontend/src/main.tsx", "import './styles.css';\nimport { Api } from '@/api/client';\n")
    _write(root, "frontend/src/styles.css", "body { color: red; }\n")
    _write(root, "frontend/src/api/client.ts", "export const Api = 1;\n")
    _git(root, "add", "--all")

    report = build_report(root)
    discovered = {item["path"]: item for item in report["required_files"]}

    assert report["status"] == "pass"
    assert discovered["frontend/tsconfig.json"]["errors"] == []
    assert discovered["frontend/tsconfig.app.json"]["errors"] == []
    assert "typescript_project_reference" in {
        item["kind"] for item in discovered["frontend/tsconfig.app.json"]["discovery_evidence"]
    }
    for path in ("frontend/index.html", "frontend/src/main.tsx", "frontend/src/api/client.ts"):
        assert discovered[path]["errors"] == []


def test_malformed_frontend_package_manifest_is_reported(tmp_path: Path):
    root = _runtime_repository(tmp_path)
    _write(root, "frontend/package.json", '{"name": "ui",\n')
    _write(root, "frontend/index.html", "<html></html>\n")
    _git(root, "add", "--all")

    report = build_report(root)
    manifest = _finding(report, "frontend/package.json")

    assert report["status"] == "fail"
    assert "INVALID_FRONTEND_PACKAGE_JSON" in manifest["errors"]
