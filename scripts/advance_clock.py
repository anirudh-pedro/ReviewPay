"""Advance the simulation clock from the command line.

The CLI equivalent of ``POST /simulate/advance-clock`` (Requirement 18.7). Both
share one persisted timeline, so a demo can mix the two freely.

Usage:
    python scripts/advance_clock.py --minutes 15
    python scripts/advance_clock.py --hours 2
    python scripts/advance_clock.py --show
    python scripts/advance_clock.py --reset
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.container import get_clock  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Advance RevivePay simulation time.")
    parser.add_argument("--minutes", type=int, default=0, help="minutes to advance")
    parser.add_argument("--hours", type=int, default=0, help="hours to advance")
    parser.add_argument("--show", action="store_true", help="print the time and exit")
    parser.add_argument("--reset", action="store_true", help="reset to the configured start")
    args = parser.parse_args()

    configure_logging()
    clock = get_clock()

    if args.show:
        print(f"Simulation time: {clock.now().isoformat()}")
        return 0

    if args.reset:
        print(f"Simulation time reset to: {clock.reset().isoformat()}")
        return 0

    if args.minutes == 0 and args.hours == 0:
        parser.error("specify --minutes, --hours, --show, or --reset")

    previous = clock.now()
    current = clock.advance(minutes=args.minutes, hours=args.hours)

    print(f"Simulation time: {previous.isoformat()} -> {current.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
