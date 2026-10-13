"""Ingest every URL from seed_urls.txt (thin wrapper around the pipeline).

Usage (from the project root):
    python scripts/ingest_seed.py [--file seed_urls.txt] [--transcribe] [--summarize] [--limit N]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import ensure_directories, load_settings, setup_logging  # noqa: E402
from extractor.pipeline import ingest_urls, load_urls_from_file  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest seed URLs")
    parser.add_argument("--file", help="URL file (default: seed_urls.txt)")
    parser.add_argument("--transcribe", action="store_true")
    parser.add_argument("--summarize", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    settings = load_settings()
    ensure_directories(settings)
    setup_logging(settings)

    url_file = Path(args.file) if args.file else settings.seed_file
    urls = load_urls_from_file(url_file)
    print(f"Ingesting {len(urls)} URL(s) from {url_file}")

    results = ingest_urls(
        urls,
        settings,
        transcribe=args.transcribe,
        summarize=args.summarize,
        limit=args.limit,
    )
    for record in results:
        status = record.get("status", "?")
        error = (record.get("error") or "").split(";")[0][:90]
        print(
            f"[{record.get('index', '?')}/{record.get('total', '?')}] "
            f"{status:<20} {record.get('url', '')} {('- ' + error) if error else ''}"
        )

    ok = sum(1 for record in results if record.get("status") == "extracted")
    print(f"\nDone: {ok}/{len(results)} extracted cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
