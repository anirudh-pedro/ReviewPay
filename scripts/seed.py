"""Seed the RevivePay database with synthetic demonstration data.

Usage:
    python scripts/seed.py
    python scripts/seed.py --reset          # wipe and reseed
    python scripts/seed.py --customers 20   # larger background population

All generated data is synthetic. No real payment is involved.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.container import get_clock  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.db.init_db import create_all, drop_all  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.services.scenario_generator import ScenarioGenerator  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed synthetic RevivePay data.")
    parser.add_argument("--reset", action="store_true", help="drop and recreate tables first")
    parser.add_argument(
        "--customers", type=int, default=12, help="background customers to generate"
    )
    args = parser.parse_args()

    configure_logging()
    settings = get_settings()
    clock = get_clock(settings)

    if args.reset:
        print("Dropping existing tables...")
        drop_all()
        clock.reset()

    create_all()

    with session_scope() as session:
        generator = ScenarioGenerator(session=session, clock=clock, settings=settings)
        summary = generator.generate(background_customers=args.customers)

        print()
        print("=" * 74)
        print("  REVIVEPAY  |  SYNTHETIC DEMONSTRATION DATA SEEDED")
        print("=" * 74)
        print(f"  Database          : {settings.database_url}")
        print(f"  Simulation time   : {clock.now().isoformat()}")
        print(f"  Simulation seed   : {settings.simulation_seed}")
        print()
        print(f"  Customers         : {summary.customers}")
        print(f"  Payments          : {summary.payments}")
        print(f"  Recovery cases    : {summary.cases}")
        print()
        print("  Deterministic demo scenarios")
        print("  " + "-" * 70)
        for scenario in summary.scenarios:
            amount = scenario.payment.amount / 100
            print(
                f"  {scenario.key}  {scenario.case.case_id:<26} "
                f"{scenario.payment.failure_reason.value:<22} INR {amount:>12,.2f}"
            )
            print(
                f"     expects {scenario.expected_action} -> "
                f"{scenario.expected_final_state}"
                + ("  (needs clock advance)" if scenario.requires_clock_advance else "")
            )
        print("  " + "-" * 70)
        print()
        print("  Next:  python scripts/demo.py")
        print("=" * 74)
        print()
        print("  All payment data above is synthetic. No real money moved.")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
