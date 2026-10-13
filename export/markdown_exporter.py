"""Markdown export: a human-readable report grouped by content type."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config import Settings
from database import database_stats, get_transcript_segments, items_with_summaries
from models import ContentType, ItemStatus
from utils import humanize_duration, humanize_number, truncate

logger = logging.getLogger(__name__)

_GROUP_ORDER = [
    ContentType.VIDEO.value,
    ContentType.REEL.value,
    ContentType.POST.value,
    ContentType.MALFORMED.value,
    ContentType.UNKNOWN.value,
    ContentType.HOMEPAGE.value,
]

_GROUP_TITLES = {
    ContentType.VIDEO.value: "Videos",
    ContentType.REEL.value: "Reels",
    ContentType.POST.value: "Posts",
    ContentType.MALFORMED.value: "Malformed URLs",
    ContentType.UNKNOWN.value: "Unknown",
    ContentType.HOMEPAGE.value: "Homepage",
}

_STATUS_ICONS = {
    ItemStatus.EXTRACTED.value: "OK",
    ItemStatus.PARTIAL.value: "PARTIAL",
    ItemStatus.NEEDS_LOGIN.value: "LOGIN",
    ItemStatus.NEEDS_MANUAL_IMPORT.value: "MANUAL",
    ItemStatus.FAILED.value: "FAILED",
    ItemStatus.SKIPPED.value: "SKIPPED",
    ItemStatus.PENDING.value: "PENDING",
}


def _fmt(value: Any, fallback: str = "missing") -> str:
    if value in (None, "", [], {}):
        return fallback
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _summary_section(summary: dict[str, Any] | None) -> list[str]:
    if not summary:
        return ["_No AI summary yet (run `python main.py ingest --all --summarize`)._", ""]
    lines = [
        f"**Short title:** {_fmt(summary.get('short_title'))}",
        "",
        f"**English summary:** {_fmt(summary.get('english_summary'))}",
        "",
        f"**Filipino summary:** {_fmt(summary.get('filipino_summary'))}",
        "",
    ]
    key_points = summary.get("key_points") or []
    if key_points:
        lines.append("**Key points:**")
        lines.append("")
        for point in key_points:
            lines.append(f"- {point}")
        lines.append("")
    lines.extend(
        [
            f"**Topics:** {_fmt(summary.get('topics'))}  ",
            f"**Sentiment:** {_fmt(summary.get('sentiment'))}  ",
            f"**Entities:** {_fmt(summary.get('entities'))}  ",
            f"**Virality signals:** {_fmt(summary.get('virality_signals'))}  ",
            f"**Content warnings:** {_fmt(summary.get('content_warnings'), 'none')}  ",
            f"**Suggested tags:** {_fmt(summary.get('suggested_tags'))}",
            "",
        ]
    )
    if summary.get("call_to_action"):
        lines.extend([f"**Call to action:** {summary['call_to_action']}", ""])
    return lines


def _render_item(item: dict[str, Any]) -> list[str]:
    lines = [
        f"### {item['id']}. {_fmt(item.get('title'), '(no title)')}",
        "",
        f"- **Status:** {_STATUS_ICONS.get(str(item.get('status') or ''), item.get('status'))}"
        + (" (needs login)" if item.get("needs_login") else "")
        + (" (needs manual import)" if item.get("needs_manual_import") else ""),
        f"- **URL:** {item.get('source_url')}",
        f"- **Resolved URL:** {_fmt(item.get('resolved_url'))}",
        f"- **Author / Page:** {_fmt(item.get('author') or item.get('page_name'))}",
        f"- **Upload date:** {_fmt(item.get('upload_date'))}",
        f"- **Duration:** {humanize_duration(item.get('duration_seconds'))}",
        f"- **Views:** {humanize_number(item.get('view_count'))}  "
        f"**Likes:** {humanize_number(item.get('like_count'))}  "
        f"**Comments:** {humanize_number(item.get('comment_count'))}  "
        f"**Shares:** {humanize_number(item.get('share_count'))}",
        f"- **Language:** {_fmt(item.get('language'))}",
        f"- **Transcript source:** {_fmt(item.get('transcript_source'), 'none')}"
        + (f" ({item['transcript_language']})" if item.get("transcript_language") else ""),
        f"- **Extracted at:** {_fmt(item.get('extracted_at'))}",
        "",
    ]

    if item.get("thumbnail_url"):
        lines.append(f"![thumbnail]({item['thumbnail_url']})")
        lines.append("")

    if item.get("hashtags"):
        lines.extend([f"**Hashtags:** {' '.join('#' + tag for tag in item['hashtags'])}", ""])
    if item.get("external_links"):
        lines.extend([f"**External links:** {_fmt(item.get('external_links'))}", ""])

    caption = (item.get("caption") or "").strip()
    if caption:
        lines.extend(["**Caption:**", "", "> " + caption.replace("\n", "\n> "), ""])

    transcript = (item.get("transcript_text") or "").strip()
    if transcript:
        excerpt = truncate(transcript, 1200)
        lines.extend(["**Transcript excerpt:**", "", "> " + excerpt.replace("\n", "\n> "), ""])

    if item.get("error_message"):
        lines.extend([f"**Error:** {item['error_message']}", ""])

    lines.extend(["**AI Summary**", "", *_summary_section(item.get("summary"))])
    lines.append("---")
    lines.append("")
    return lines


def export_markdown(
    settings: Settings,
    output_path: Path | None = None,
    include_transcript_segments: bool = False,
) -> Path:
    """Write data/report.md and return the path."""
    path = output_path or settings.markdown_path
    path.parent.mkdir(parents=True, exist_ok=True)

    items = items_with_summaries(settings.database_path)
    stats = database_stats(settings.database_path)
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(str(item.get("content_type") or "unknown"), []).append(item)

    ordered_groups = [group for group in _GROUP_ORDER if group in grouped]
    ordered_groups += [group for group in sorted(grouped) if group not in _GROUP_ORDER]

    lines: list[str] = [
        "# Facebook Content Extraction Report",
        "",
        f"_Generated at {generated_at} by facebook-extractor._",
        "",
        "## Summary",
        "",
        f"- Total items: **{stats['items']}**",
        f"- Items with transcript: **{stats['with_transcript']}**",
        f"- Items needing login: **{stats['needs_login']}**",
        f"- Items needing manual import: **{stats['needs_manual_import']}**",
        f"- AI summaries generated: **{stats['summaries']}**",
        "",
        "| Content type | Items |",
        "| --- | --- |",
    ]
    for group in ordered_groups:
        lines.append(f"| {_GROUP_TITLES.get(group, group)} | {len(grouped[group])} |")
    lines.extend(
        [
            "",
            "| Status | Items |",
            "| --- | --- |",
        ]
    )
    for status, count in sorted(stats["by_status"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {_STATUS_ICONS.get(status, status)} | {count} |")
    lines.append("")

    for group in ordered_groups:
        lines.extend([f"## {_GROUP_TITLES.get(group, group)} ({len(grouped[group])})", ""])
        for item in grouped[group]:
            lines.extend(_render_item(item))
            if include_transcript_segments:
                segments = get_transcript_segments(int(item["id"]), settings.database_path)
                if segments:
                    lines.extend(["**Transcript segments:**", ""])
                    for segment in segments:
                        start = segment.get("start_seconds")
                        stamp = f"[{start:8.2f}s]" if isinstance(start, (int, float)) else "[   ?   ]"
                        lines.append(f"- `{stamp}` {segment.get('text', '')}")
                    lines.extend(["", "---", ""])

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Markdown export written: %s (%d items)", path, len(items))
    return path
