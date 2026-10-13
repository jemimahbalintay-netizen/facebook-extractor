"""CLI entry point for facebook-extractor.

Commands:
    python main.py ingest --all [--transcribe] [--summarize]
    python main.py ingest --url URL
    python main.py ingest --file seed_urls.txt
    python main.py ingest --retry-failed [--include needs_login,...]
    python main.py ingest --all --skip-existing
    python main.py summarize [--all] [--stale] [--url URL] [--limit N]
    python main.py search "query" [--status S] [--type T] [--json]
    python main.py manual-import --url URL --text-file caption.txt
    python main.py manual-import --url URL --json-file metadata.json
    python main.py export --format csv|markdown|json|xlsx|all
    python main.py serve [--host 127.0.0.1] [--port 8765]
    python main.py status
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ai.summarizer import summarize_pending
from config import (
    Settings,
    ensure_directories,
    ffmpeg_available,
    load_settings,
    setup_logging,
)
from database import database_stats, failed_urls, list_items, search_items
from export.csv_exporter import export_csv
from export.json_exporter import export_json
from export.markdown_exporter import export_markdown
from export.xlsx_exporter import export_xlsx
from extractor.manual_extractor import (
    ManualImportError,
    read_json_file,
    read_text_file,
)
from extractor.pipeline import (
    filter_existing_urls,
    ingest_urls,
    load_urls_from_file,
    manual_import,
)
from extractor.transcript_extractor import faster_whisper_installed
from utils import truncate


def _configure_console_encoding() -> None:
    """Force UTF-8 on stdout/stderr so rich never crashes on emoji in titles.

    Legacy Windows terminals default to cp1252, which raises
    ``UnicodeEncodeError`` for characters like emoji that appear in Facebook
    captions.  ``errors="replace"`` guarantees output never fails.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - best effort; printing still works
            pass


_configure_console_encoding()

console = Console()
logger = logging.getLogger("facebook_extractor")

_STATUS_STYLES = {
    "extracted": "green",
    "partial": "yellow",
    "needs_login": "red",
    "needs_manual_import": "magenta",
    "failed": "red",
    "skipped": "dim",
    "pending": "dim",
}


def _status_text(status: str) -> str:
    style = _STATUS_STYLES.get(status, "white")
    return f"[{style}]{status}[/{style}]"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_ingest(args: argparse.Namespace, settings: Settings) -> int:
    urls: list[str] = []

    if args.url:
        urls.extend(args.url)
    if args.file:
        urls.extend(load_urls_from_file(args.file))
    if args.all:
        urls.extend(load_urls_from_file(settings.seed_file))
    if getattr(args, "retry_failed", False):
        statuses = [
            status.strip()
            for status in (
                args.include or "needs_login,needs_manual_import,failed"
            ).split(",")
            if status.strip()
        ]
        retry_urls = failed_urls(settings.database_path, statuses)
        console.print(
            f"Retrying [bold]{len(retry_urls)}[/bold] URL(s) with status in "
            f"{', '.join(statuses)}"
        )
        urls.extend(retry_urls)
    if (
        not args.url
        and not args.file
        and not args.all
        and not getattr(args, "retry_failed", False)
    ):
        console.print(
            "[yellow]No source given; defaulting to seed_urls.txt "
            "(use --url, --file, --all or --retry-failed).[/yellow]"
        )
        urls.extend(load_urls_from_file(settings.seed_file))

    # De-duplicate while preserving order.
    urls = list(dict.fromkeys(urls))

    if getattr(args, "skip_existing", False) and urls:
        urls, skipped = filter_existing_urls(urls, settings)
        if skipped:
            console.print(f"Skipping {skipped} URL(s) that already have content.")

    if not urls:
        console.print("[red]No URLs to process.[/red]")
        return 2

    if args.transcribe:
        if not faster_whisper_installed():
            console.print(
                "[yellow]Warning: faster-whisper is not installed; audio "
                "transcription will be skipped. Install the optional "
                "dependencies with `pip install -r requirements-optional.txt`.[/yellow]"
            )
        if not ffmpeg_available():
            console.print(
                "[yellow]Warning: ffmpeg was not found on PATH. Audio decoding "
                "may fail; install ffmpeg to enable transcription.[/yellow]"
            )

    want_summary = bool(args.summarize or settings.auto_summarize)
    if want_summary and not settings.summary_enabled():
        console.print(
            "[yellow]Warning: DEEPSEEK_API_KEY is not set; AI summarisation "
            "will be skipped. Copy .env.example to .env and add your key.[/yellow]"
        )

    console.print(
        f"Processing [bold]{len(urls)}[/bold] URL(s) "
        f"(delay {settings.facebook_delay_seconds:g}s between requests, "
        f"transcribe={bool(args.transcribe)}, summarize={want_summary})"
    )
    results = ingest_urls(
        urls,
        settings,
        transcribe=bool(args.transcribe),
        summarize=bool(args.summarize),
        limit=args.limit,
    )
    _print_ingest_table(results)

    stats = database_stats(settings.database_path)
    console.print(
        f"\nDatabase now holds [bold]{stats['items']}[/bold] items "
        f"([green]{stats['by_status'].get('extracted', 0)} extracted[/green], "
        f"[yellow]{stats['by_status'].get('partial', 0)} partial[/yellow], "
        f"[red]{stats['needs_login']} need login[/red], "
        f"[magenta]{stats['needs_manual_import']} need manual import[/magenta])."
    )
    return 0


def _print_ingest_table(results: list[dict[str, Any]]) -> None:
    table = Table(title="Ingestion results", show_lines=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("URL", max_width=44)
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Transcript")
    table.add_column("Summary")
    table.add_column("Flags")
    table.add_column("Notes / error", max_width=50)

    for record in results:
        flags = []
        if record.get("needs_login"):
            flags.append("login")
        if record.get("needs_manual_import"):
            flags.append("manual")
        if record.get("malformed"):
            flags.append("malformed")
        if record.get("preserved_previous"):
            flags.append("kept")
        if record.get("kept_previous"):
            flags.append("prev-kept")
        transcript = record.get("transcript_source") or "none"
        chars = record.get("transcript_chars") or 0
        transcript_text = f"{transcript} ({chars})" if chars else transcript

        summary_state = record.get("summary")
        if summary_state is None:
            summary_text = "[dim]-[/dim]"
        elif summary_state == "ok":
            summary_text = "[green]ok[/green]"
        else:
            summary_text = "[yellow]skipped[/yellow]"

        note = record.get("error") or ""
        if not note:
            warnings = record.get("warnings") or []
            note = warnings[0] if warnings else ""
        table.add_row(
            str(record.get("index", "")),
            truncate(record.get("url", ""), 42),
            str(record.get("content_type", "")),
            _status_text(str(record.get("status", ""))),
            transcript_text,
            summary_text,
            ", ".join(flags) or "-",
            truncate(note, 48) if note else "-",
        )
    console.print(table)


def cmd_summarize(args: argparse.Namespace, settings: Settings) -> int:
    from ai.deepseek_client import is_configured

    if not is_configured(settings):
        console.print(
            "[red]DEEPSEEK_API_KEY is not configured.[/red] Copy .env.example "
            "to .env and add your key (e.g. an NVIDIA NIM key with "
            "DEEPSEEK_BASE_URL=https://integrate.api.nvidia.com/v1 and "
            "DEEPSEEK_MODEL=deepseek-ai/deepseek-v4.1-flash)."
        )
        return 2

    if getattr(args, "stale", False):
        mode_text = "re-summarizing only items whose content changed"
    elif args.all:
        mode_text = "re-summarizing everything"
    else:
        mode_text = "only items without a summary"
    console.print(
        f"Summarizing stored items with [bold]{settings.deepseek_model}[/bold] "
        f"via {settings.deepseek_base_url} (delay {args.delay:g}s between calls, "
        f"{mode_text})"
    )
    results = summarize_pending(
        settings,
        urls=args.url,
        limit=args.limit,
        missing_only=not (args.all or getattr(args, "stale", False)),
        delay_seconds=args.delay,
        stale_only=bool(getattr(args, "stale", False)),
    )

    table = Table(title="Summarisation results")
    table.add_column("Item", justify="right")
    table.add_column("Status")
    table.add_column("URL", max_width=42)
    table.add_column("Short title / error", max_width=56)
    for record in results:
        status = str(record.get("status"))
        styled = {
            "ok": "[green]ok[/green]",
            "failed": "[red]failed[/red]",
            "skipped": "[dim]skipped[/dim]",
        }.get(status, status)
        detail = record.get("short_title") or record.get("error") or ""
        table.add_row(
            str(record.get("id", "")),
            styled,
            truncate(str(record.get("url", "")), 40),
            truncate(str(detail), 54),
        )
    console.print(table)

    ok = sum(1 for record in results if record.get("status") == "ok")
    failed = sum(1 for record in results if record.get("status") == "failed")
    skipped = sum(1 for record in results if record.get("status") == "skipped")
    console.print(
        f"Done: [green]{ok} summarized[/green], [red]{failed} failed[/red], "
        f"[dim]{skipped} skipped[/dim]."
    )
    return 0 if failed == 0 else 1


def cmd_manual_import(args: argparse.Namespace, settings: Settings) -> int:
    text: str | None = None
    payload: dict[str, Any] | None = None

    if args.text_file:
        text = read_text_file(args.text_file)
    if args.json_file:
        payload = read_json_file(args.json_file)
    if text is None and payload is None and args.caption:
        text = args.caption
    if text is None and payload is None:
        console.print(
            "[red]Nothing to import.[/red] Provide --text-file, --json-file "
            "or --caption."
        )
        return 2

    result = manual_import(args.url, settings, text=text, payload=payload)
    console.print(
        Panel(
            f"[green]Manual import saved[/green]\n"
            f"Item #{result['id']} - {result['url']}\n"
            f"caption: {result['caption_chars']} chars, "
            f"transcript: {result['transcript_chars']} chars "
            f"({result['transcript_source']}), "
            f"fields applied: {result['applied_fields']}",
            title="manual-import",
        )
    )
    return 0


def cmd_search(args: argparse.Namespace, settings: Settings) -> int:
    results = search_items(
        args.query,
        settings.database_path,
        limit=args.limit,
        status=getattr(args, "status", None),
        content_type=getattr(args, "content_type", None),
    )

    if getattr(args, "json_output", False):
        import json as _json

        print(_json.dumps(results, ensure_ascii=False, indent=2, default=str))
        return 0

    if not results:
        console.print(f"[yellow]No matches for {args.query!r}.[/yellow]")
        return 0

    table = Table(title=f"Search: {args.query!r} — {len(results)} result(s)")
    table.add_column("ID", justify="right")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Title", max_width=34)
    table.add_column("Author", max_width=18)
    table.add_column("Match snippet", max_width=56)
    for record in results:
        snippet = (
            record.get("transcript_snippet")
            or record.get("caption_snippet")
            or ""
        )
        table.add_row(
            str(record.get("id", "")),
            str(record.get("content_type", "")),
            _status_text(str(record.get("status", ""))),
            truncate(record.get("title") or "(no title)", 32),
            truncate(record.get("author") or record.get("page_name") or "-", 16),
            truncate(str(snippet), 54),
        )
    console.print(table)
    return 0


def cmd_export(args: argparse.Namespace, settings: Settings) -> int:
    fmt = args.format
    formats = ["csv", "markdown", "json", "xlsx"] if fmt == "all" else [fmt]

    exporters = {
        "csv": ("CSV", export_csv),
        "markdown": ("Markdown", export_markdown),
        "json": ("JSON", export_json),
        "xlsx": ("XLSX", export_xlsx),
    }
    for name in formats:
        label, exporter = exporters[name]
        path = exporter(settings)
        console.print(f"[green]Exported {label}:[/green] {path}")
    return 0


def cmd_serve(args: argparse.Namespace, settings: Settings) -> int:
    from dashboard.app import run

    loopback_hosts = {"127.0.0.1", "::1", "localhost"}
    if args.host not in loopback_hosts:
        console.print(
            "[yellow]Warning: the dashboard has no authentication. Binding to "
            f"{args.host} exposes all extracted content and the export endpoints "
            "to your local network. Use 127.0.0.1 unless you understand the "
            "risk.[/yellow]"
        )
    console.print(f"Starting dashboard at [bold]http://{args.host}:{args.port}[/bold]")
    console.print("Press Ctrl+C to stop.")
    run(args.host, args.port)
    return 0


def cmd_status(args: argparse.Namespace, settings: Settings) -> int:
    stats = database_stats(settings.database_path)

    overview = Table(title="facebook-extractor status", show_header=False)
    overview.add_column("Metric", style="bold")
    overview.add_column("Value")
    overview.add_row("Database", str(settings.database_path))
    overview.add_row("Items", str(stats["items"]))
    overview.add_row("With transcript", str(stats["with_transcript"]))
    overview.add_row("AI summaries", str(stats["summaries"]))
    overview.add_row("Transcript segments", str(stats["segments"]))
    overview.add_row("Needs login", str(stats["needs_login"]))
    overview.add_row("Needs manual import", str(stats["needs_manual_import"]))
    overview.add_row(
        "DeepSeek key", "configured" if settings.summary_enabled() else "not configured"
    )
    overview.add_row(
        "faster-whisper",
        "installed" if faster_whisper_installed() else "not installed (optional)",
    )
    overview.add_row(
        "ffmpeg", "available" if ffmpeg_available() else "missing (optional)"
    )
    console.print(overview)

    by_status = Table(title="Items by status")
    by_status.add_column("Status")
    by_status.add_column("Count", justify="right")
    for status, count in sorted(stats["by_status"].items(), key=lambda kv: -kv[1]):
        by_status.add_row(_status_text(status), str(count))
    console.print(by_status)

    by_type = Table(title="Items by content type")
    by_type.add_column("Type")
    by_type.add_column("Count", justify="right")
    for content_type, count in stats["by_type"].items():
        by_type.add_row(content_type, str(count))
    console.print(by_type)

    items = list_items(settings.database_path, limit=args.limit, ascending=False)
    if items:
        latest = Table(title=f"Latest {len(items)} items")
        latest.add_column("ID", justify="right")
        latest.add_column("Type")
        latest.add_column("Status")
        latest.add_column("Title", max_width=44)
        latest.add_column("Author", max_width=22)
        latest.add_column("Transcript")
        latest.add_column("Extracted at")
        for item in items:
            latest.add_row(
                str(item["id"]),
                str(item["content_type"]),
                _status_text(str(item["status"])),
                truncate(item.get("title") or item.get("caption") or "-", 42),
                truncate(item.get("author") or item.get("page_name") or "-", 20),
                str(item.get("transcript_source") or "none"),
                truncate(str(item.get("extracted_at") or "-"), 19),
            )
        console.print(latest)
    return 0


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description=(
            "facebook-extractor: extract public metadata, captions and "
            "transcripts from Facebook links, store them locally, and "
            "summarize them with DeepSeek."
        ),
    )
    parser.add_argument(
        "--verbose", action="store_true", help="show debug logging on the console"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser(
        "ingest", help="extract metadata/captions/transcripts from Facebook URLs"
    )
    ingest.add_argument(
        "--all", action="store_true", help="process every URL in seed_urls.txt"
    )
    ingest.add_argument(
        "--url",
        action="append",
        default=[],
        metavar="URL",
        help="process a single URL (can be repeated)",
    )
    ingest.add_argument("--file", metavar="PATH", help="process URLs from a text file")
    ingest.add_argument(
        "--transcribe",
        action="store_true",
        help="download audio and transcribe with faster-whisper when no subtitles exist",
    )
    ingest.add_argument(
        "--summarize", action="store_true", help="generate DeepSeek AI summaries"
    )
    ingest.add_argument(
        "--retry-failed",
        action="store_true",
        help="re-process URLs whose last extraction failed "
        "(needs_login / needs_manual_import / failed)",
    )
    ingest.add_argument(
        "--include",
        metavar="STATUSES",
        help="statuses considered by --retry-failed "
        "(default: needs_login,needs_manual_import,failed)",
    )
    ingest.add_argument(
        "--skip-existing",
        action="store_true",
        help="skip URLs that already have content; only new and failed URLs "
        "are processed (ideal for scheduled runs)",
    )
    ingest.add_argument(
        "--limit", type=int, metavar="N", help="only process the first N URLs"
    )

    summarize = subparsers.add_parser(
        "summarize",
        help="generate DeepSeek summaries for stored items (no re-fetching)",
    )
    summarize.add_argument(
        "--url",
        action="append",
        default=[],
        metavar="URL",
        help="summarize only this URL (can be repeated)",
    )
    summarize.add_argument(
        "--all",
        action="store_true",
        help="re-summarize items that already have a summary "
        "(default: only items missing one)",
    )
    summarize.add_argument(
        "--stale",
        action="store_true",
        help="re-summarize only items whose stored content changed after "
        "their summary was generated",
    )
    summarize.add_argument("--limit", type=int, metavar="N")
    summarize.add_argument(
        "--delay",
        type=float,
        default=1.0,
        metavar="SECONDS",
        help="pause between API calls (default: 1s)",
    )

    search = subparsers.add_parser(
        "search", help="full-text search over titles, captions and transcripts"
    )
    search.add_argument("query", help="search terms (whitespace = AND, suffix * = prefix)")
    search.add_argument("--status", metavar="STATUS", help="restrict to one status")
    search.add_argument(
        "--type", dest="content_type", metavar="TYPE", help="restrict to one content type"
    )
    search.add_argument(
        "--limit", type=int, default=25, metavar="N", help="maximum results (default 25)"
    )
    search.add_argument(
        "--json", dest="json_output", action="store_true", help="print JSON"
    )

    manual = subparsers.add_parser(
        "manual-import",
        help="attach pasted text or JSON metadata to a URL that could not be extracted",
    )
    manual.add_argument("--url", required=True, help="the original Facebook URL")
    manual.add_argument(
        "--text-file", metavar="PATH", help="file containing the caption/post text"
    )
    manual.add_argument(
        "--json-file", metavar="PATH", help="file with a JSON metadata payload"
    )
    manual.add_argument(
        "--caption", metavar="TEXT", help="inline caption/transcript text (alternative to --text-file)"
    )

    export = subparsers.add_parser("export", help="export the database")
    export.add_argument(
        "--format",
        choices=["csv", "markdown", "json", "xlsx", "all"],
        default="all",
        help="output format (default: all)",
    )

    serve = subparsers.add_parser("serve", help="run the local dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    status = subparsers.add_parser("status", help="show database and tool status")
    status.add_argument(
        "--limit", type=int, default=20, help="how many recent items to show"
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = load_settings()
    ensure_directories(settings)
    setup_logging(settings)
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        if args.command == "ingest":
            return cmd_ingest(args, settings)
        if args.command == "summarize":
            return cmd_summarize(args, settings)
        if args.command == "search":
            return cmd_search(args, settings)
        if args.command == "manual-import":
            return cmd_manual_import(args, settings)
        if args.command == "export":
            return cmd_export(args, settings)
        if args.command == "serve":
            return cmd_serve(args, settings)
        if args.command == "status":
            return cmd_status(args, settings)
        parser.print_help()
        return 2
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    except ManualImportError as exc:
        console.print(f"[red]Manual import failed:[/red] {exc}")
        return 2
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/yellow]")
        return 130
    except Exception as exc:  # noqa: BLE001 - top-level safety net
        logger.exception("command failed")
        console.print(
            f"[red]Unexpected error:[/red] {type(exc).__name__}: {exc}\n"
            f"See logs/extractor.log for details."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
