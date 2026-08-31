"""Initialize the RevivePay database.

Usage:
    python scripts/init_db.py
    python scripts/init_db.py --reset      # drop and recreate every table
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as a plain script from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.db.init_db import create_all, drop_all, table_names  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the RevivePay database schema.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="drop all tables before creating them (destroys local demo data)",
    )
    args = parser.parse_args()

    configure_logging()
    settings = get_settings()

    print(f"Database: {settings.database_url}")

    if args.reset:
        print("Dropping existing tables...")
        drop_all()

    create_all()

    tables = table_names()
    print(f"Schema ready. {len(tables)} tables:")
    for name in tables:
        print(f"  - {name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
