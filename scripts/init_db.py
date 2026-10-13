"""Initialise the SQLite database.

Usage (from the project root):
    python scripts/init_db.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import ensure_directories, load_settings, setup_logging  # noqa: E402
from database import count_rows, init_db  # noqa: E402


def main() -> int:
    settings = load_settings()
    ensure_directories(settings)
    setup_logging(settings)

    path = init_db(settings.database_path)
    counts = count_rows(settings.database_path)

    print(f"Database initialised: {path}")
    print(
        "Tables: items, summaries, transcript_segments | "
        f"items={counts['items']} "
        f"summaries={counts['summaries']} "
        f"transcript_segments={counts['segments']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
