"""Export the database to CSV, Markdown and JSON.

Usage (from the project root):
    python scripts/export_all.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import ensure_directories, load_settings, setup_logging  # noqa: E402
from export.csv_exporter import export_csv  # noqa: E402
from export.json_exporter import export_json  # noqa: E402
from export.markdown_exporter import export_markdown  # noqa: E402


def main() -> int:
    settings = load_settings()
    ensure_directories(settings)
    setup_logging(settings)

    csv_path = export_csv(settings)
    markdown_path = export_markdown(settings)
    json_path = export_json(settings)

    print(f"CSV      -> {csv_path}")
    print(f"Markdown -> {markdown_path}")
    print(f"JSON     -> {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
