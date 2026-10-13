"""Compact data/extracted.jsonl so it holds one (latest) record per URL.

``main`` appends a record for every processed URL, which means re-running
ingestion for the same URL produces duplicate lines.  This utility keeps only
the newest record for each ``source_url`` (the SQLite database is always the
source of truth).

Usage (from the project root):
    python scripts/compact_jsonl.py [--path data/extracted.jsonl]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import ensure_directories, load_settings, setup_logging  # noqa: E402


def compact(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    records: OrderedDict[str, dict] = OrderedDict()
    total = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        total += 1
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = str(record.get("source_url") or f"__line_{total}")
        records[key] = record  # later lines replace earlier ones

    with path.open("w", encoding="utf-8") as handle:
        for record in records.values():
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return total, len(records)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compact extracted.jsonl")
    parser.add_argument("--path", help="JSONL path (default: data/extracted.jsonl)")
    args = parser.parse_args()

    settings = load_settings()
    ensure_directories(settings)
    setup_logging(settings)

    path = Path(args.path) if args.path else settings.jsonl_path
    total, kept = compact(path)
    print(f"{path}: {total} lines -> {kept} unique records (latest kept per URL)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
