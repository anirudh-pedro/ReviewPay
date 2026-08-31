"""Deterministic virtual clock.

Simulation time moves only when something explicitly advances it. There is no
scheduler, no background thread, and no ``time.sleep`` anywhere in the system
(Requirement 18.2, 18.10). That is what makes ``RETRY_LATER`` demonstrable on
stage and assertable in tests: fail at 13:00, schedule for 13:16, advance fifteen
minutes, retry executes.

State is persisted as JSON so the API process and the CLI scripts share one
timeline. Reading a small file on each ``now()`` is inexpensive at Phase 0 scale
and avoids a database table, keeping the domain model at exactly seven entities.

Known limitation: the file is not locked, so concurrent writers could interleave.
Phase 0 assumes a single-process development server.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

_ISO_KEY = "simulation_time"


class VirtualClock:
    """The current simulation time, advanced only on request."""

    def __init__(self, state_path: str | Path, start: datetime) -> None:
        self._state_path = Path(state_path)
        self._start = start

    # -- reading -----------------------------------------------------------

    def now(self) -> datetime:
        """Return the current simulation time.

        Initializes the persisted state from the configured start time on first
        use. Never reads the wall clock.
        """
        stored = self._read()
        if stored is None:
            return self._write(self._start)
        return stored

    def is_due(self, moment: datetime | None) -> bool:
        """True when ``moment`` has been reached, or when nothing is scheduled."""
        if moment is None:
            return True
        return self.now() >= moment

    # -- writing -----------------------------------------------------------

    def advance(self, *, minutes: int = 0, hours: int = 0) -> datetime:
        """Advance simulation time and return the new value (Requirement 18.6)."""
        delta = timedelta(minutes=minutes, hours=hours)
        if delta < timedelta(0):
            raise ValueError("Simulation time cannot move backwards; use reset() instead.")
        return self._write(self.now() + delta)

    def reset(self, to: datetime | None = None) -> datetime:
        """Reset simulation time to ``to``, or to the configured start time."""
        return self._write(to if to is not None else self._start)

    # -- persistence -------------------------------------------------------

    def _read(self) -> datetime | None:
        try:
            raw = self._state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        try:
            payload = json.loads(raw)
            return datetime.fromisoformat(payload[_ISO_KEY])
        except (ValueError, KeyError, TypeError):
            # Corrupt or hand-edited state file: fall back to the configured start
            # rather than failing a demo.
            return None

    def _write(self, moment: datetime) -> datetime:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps({_ISO_KEY: moment.isoformat()}, indent=2) + "\n",
            encoding="utf-8",
        )
        return moment


def build_clock() -> VirtualClock:
    """Construct the clock from application settings."""
    from app.core.config import get_settings

    settings = get_settings()
    return VirtualClock(
        state_path=settings.virtual_clock_state_path,
        start=settings.virtual_clock_start,
    )


__all__ = ["VirtualClock", "build_clock"]
