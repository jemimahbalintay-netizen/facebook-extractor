"""Create a verified backup of the SQLite database using the SQLite backup API.

Unlike a file copy, ``sqlite3.Connection.backup`` is safe for WAL-mode
databases (it takes a consistent snapshot even while other connections are
active).  The copy is verified with ``PRAGMA integrity_check`` before old
backups are pruned.

Usage (from the project root):
    python scripts/backup_db.py [--keep 10]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import ensure_directories, load_settings, setup_logging  # noqa: E402


def make_backup(db_path: Path, keep: int) -> Path:
    backups_dir = db_path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = backups_dir / f"facebook_content-{stamp}.db"

    source = sqlite3.connect(str(db_path))
    target = sqlite3.connect(str(destination))
    try:
        with target:
            source.backup(target)
        integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"backup integrity check failed: {integrity}")
        counts = {
            "items": target.execute("SELECT COUNT(*) FROM items").fetchone()[0],
            "summaries": target.execute("SELECT COUNT(*) FROM summaries").fetchone()[0],
            "segments": target.execute(
                "SELECT COUNT(*) FROM transcript_segments"
            ).fetchone()[0],
        }
    finally:
        source.close()
        target.close()

    print(f"backup written : {destination} ({destination.stat().st_size} bytes)")
    print("integrity      : ok")
    print(
        "rows           : items={items} summaries={summaries} segments={segments}".format(
            **counts
        )
    )

    # Retention: keep the newest ``keep`` backups.
    existing = sorted(backups_dir.glob("facebook_content-*.db"))
    for stale in existing[:-keep] if keep > 0 else []:
        stale.unlink()
        print(f"pruned old backup: {stale.name}")

    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Verified SQLite backup")
    parser.add_argument(
        "--keep", type=int, default=10, help="how many backups to retain (default 10)"
    )
    args = parser.parse_args()

    settings = load_settings()
    ensure_directories(settings)
    setup_logging(settings)

    if not settings.database_path.exists():
        print(f"database not found: {settings.database_path}")
        return 2

    make_backup(settings.database_path, max(1, args.keep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
