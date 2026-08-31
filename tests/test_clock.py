"""Virtual clock tests (Requirement 18.1, 18.2, 18.6, 18.10)."""

from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path

import pytest

from app.core.clock import VirtualClock

START = datetime(2026, 1, 1, 13, 0, 0)


@pytest.fixture
def clock(tmp_path) -> VirtualClock:
    return VirtualClock(state_path=tmp_path / "clock.json", start=START)


def test_now_initialises_from_the_configured_start(clock):
    assert clock.now() == START


def test_now_is_stable_across_repeated_calls(clock):
    assert clock.now() == clock.now() == START


def test_advance_by_fifteen_minutes(clock):
    """The canonical demo step: 13:01 + 15m -> 13:16."""
    clock.reset(datetime(2026, 1, 1, 13, 1, 0))
    assert clock.advance(minutes=15) == datetime(2026, 1, 1, 13, 16, 0)


def test_advance_accumulates(clock):
    clock.advance(minutes=10)
    clock.advance(minutes=5)
    assert clock.now() == datetime(2026, 1, 1, 13, 15, 0)


def test_advance_by_hours(clock):
    assert clock.advance(hours=2) == datetime(2026, 1, 1, 15, 0, 0)


def test_advance_rejects_negative_movement(clock):
    with pytest.raises(ValueError, match="backwards"):
        clock.advance(minutes=-5)


def test_reset_returns_to_the_start(clock):
    clock.advance(hours=3)
    assert clock.reset() == START


def test_reset_to_an_explicit_moment(clock):
    target = datetime(2026, 6, 1, 9, 30, 0)
    assert clock.reset(target) == target
    assert clock.now() == target


def test_state_is_shared_between_instances(tmp_path):
    """Requirement 18.1: the API process and CLI scripts share one timeline."""
    path = tmp_path / "clock.json"
    first = VirtualClock(state_path=path, start=START)
    first.advance(minutes=15)

    second = VirtualClock(state_path=path, start=START)
    assert second.now() == datetime(2026, 1, 1, 13, 15, 0)


def test_corrupt_state_falls_back_to_the_start(tmp_path):
    path = tmp_path / "clock.json"
    path.write_text("not json at all", encoding="utf-8")
    assert VirtualClock(state_path=path, start=START).now() == START


def test_is_due_semantics(clock):
    clock.reset(datetime(2026, 1, 1, 13, 1, 0))
    assert clock.is_due(None) is True
    assert clock.is_due(datetime(2026, 1, 1, 13, 16, 0)) is False
    clock.advance(minutes=15)
    assert clock.is_due(datetime(2026, 1, 1, 13, 16, 0)) is True


def test_clock_module_uses_no_scheduler_or_sleep():
    """Requirement 18.2: no real scheduling anywhere in the clock."""
    source_path = Path(__file__).resolve().parents[1] / "app" / "core" / "clock.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert "apscheduler" not in imported
    assert "threading" not in imported
    assert "asyncio" not in imported
    assert "time" not in imported

    # Inspect calls rather than raw text, so prose in docstrings cannot trip this.
    called: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            called.add(func.attr)
        elif isinstance(func, ast.Name):
            called.add(func.id)

    # Wall-clock reads would reintroduce nondeterminism.
    assert "sleep" not in called
    assert "utcnow" not in called

    # datetime.now() specifically: the clock derives time from persisted state.
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "now"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "datetime"
        ):
            raise AssertionError("clock must not read the wall clock via datetime.now()")
