"""CSV export: one row per item, summary fields merged in."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from config import Settings
from database import items_with_summaries

logger = logging.getLogger(__name__)

CSV_COLUMNS = [
    "id",
    "source_url",
    "resolved_url",
    "content_type",
    "content_id",
    "status",
    "title",
    "author",
    "page_name",
    "upload_date",
    "duration_seconds",
    "view_count",
    "like_count",
    "comment_count",
    "share_count",
    "language",
    "transcript_source",
    "transcript_language",
    "caption",
    "transcript_text",
    "hashtags",
    "mentions",
    "external_links",
    "thumbnail_url",
    "media_url",
    "needs_login",
    "needs_manual_import",
    "malformed",
    "error_message",
    "extracted_at",
    "summarized_at",
    # Summary fields
    "summary_model",
    "short_title",
    "english_summary",
    "filipino_summary",
    "key_points",
    "detected_topics",
    "summary_hashtags",
    "entities",
    "sentiment",
    "content_warnings",
    "suggested_tags",
    "virality_signals",
    "call_to_action",
]


def _join_list(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    return str(value)


# Spreadsheet formula injection protection (OWASP CSV injection): a cell that
# starts with these characters is interpreted as a formula by Excel/Sheets.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: Any) -> Any:
    """Neutralise spreadsheet formulas by prefixing them with an apostrophe."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def export_csv(settings: Settings, output_path: Path | None = None) -> Path:
    """Write data/export_items.csv and return the path."""
    path = output_path or settings.csv_path
    path.parent.mkdir(parents=True, exist_ok=True)
    items = items_with_summaries(settings.database_path)

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for item in items:
            summary = item.get("summary") or {}
            row = {
                **item,
                "hashtags": _join_list(item.get("hashtags")),
                "mentions": _join_list(item.get("mentions")),
                "external_links": _join_list(item.get("external_links")),
                "summary_model": summary.get("model", ""),
                "short_title": summary.get("short_title", ""),
                "english_summary": summary.get("english_summary", ""),
                "filipino_summary": summary.get("filipino_summary", ""),
                "key_points": _join_list(summary.get("key_points")),
                "detected_topics": _join_list(summary.get("topics")),
                "summary_hashtags": _join_list(summary.get("hashtags")),
                "entities": _join_list(summary.get("entities")),
                "sentiment": summary.get("sentiment", ""),
                "content_warnings": _join_list(summary.get("content_warnings")),
                "suggested_tags": _join_list(summary.get("suggested_tags")),
                "virality_signals": _join_list(summary.get("virality_signals")),
                "call_to_action": summary.get("call_to_action") or "",
            }
            writer.writerow({key: _csv_safe(value) for key, value in row.items()})

    logger.info("CSV export written: %s (%d rows)", path, len(items))
    return path
