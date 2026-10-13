"""Prompt templates for DeepSeek summarisation."""

from __future__ import annotations

from typing import Any

from utils import truncate

SYSTEM_PROMPT = (
    "You are a meticulous Filipino-English media analyst. You extract, "
    "summarize, and structure information from social media posts, videos, "
    "and reels. You are factual. If data is missing, say missing. Do not "
    "invent details. Provide outputs in Filipino and English."
)

JSON_FIELDS_SPEC = """{
  "short_title": "one-line descriptive title",
  "filipino_summary": "buod sa Filipino (2-4 sentences)",
  "english_summary": "summary in English (2-4 sentences)",
  "key_points": ["bullet list of the most important facts"],
  "detected_topics": ["short topic labels"],
  "hashtags": ["hashtags without the # symbol"],
  "entities": ["people, organizations, places, products mentioned"],
  "sentiment": "positive | negative | neutral | mixed",
  "content_warnings": ["warnings such as violence, misinformation, sensitive topics; empty list if none"],
  "suggested_tags": ["lowercase tags for filing this item"],
  "virality_signals": ["why this may spread: emotion, controversy, humor, timeliness, ..."],
  "call_to_action": "any explicit CTA in the content, or null"
}"""

RESPONSE_RULES = (
    "Respond with ONLY a single valid JSON object matching this schema:\n"
    f"{JSON_FIELDS_SPEC}\n"
    'Use the string "missing" for unknown scalar values and [] for unknown '
    "lists. Never wrap the JSON in markdown fences. Never add commentary "
    "outside the JSON object."
)


def _field(label: str, value: Any) -> str:
    if value in (None, "", [], {}):
        return f"{label}: missing"
    if isinstance(value, list):
        joined = ", ".join(str(item) for item in value)
        return f"{label}: {joined if joined else 'missing'}"
    return f"{label}: {value}"


def build_user_prompt(item: dict[str, Any], transcript: str | None) -> str:
    """Full analysis prompt for one item (used when the text fits one call)."""
    transcript_text = transcript or item.get("transcript_text") or ""
    lines = [
        "Analyze this Facebook content item.",
        "",
        _field("URL", item.get("source_url")),
        _field("Content type", item.get("content_type")),
        _field("Title", item.get("title")),
        _field("Author/Page", item.get("author") or item.get("page_name")),
        _field("Upload date", item.get("upload_date")),
        _field("Duration", item.get("duration_seconds")),
        _field("Views", item.get("view_count")),
        _field("Likes", item.get("like_count")),
        _field("Comments", item.get("comment_count")),
        _field("Shares", item.get("share_count")),
        _field("Caption", item.get("caption")),
        _field("Transcript", transcript_text),
        _field("Hashtags", item.get("hashtags")),
        _field("External links", item.get("external_links")),
        "",
        RESPONSE_RULES,
    ]
    return "\n".join(lines)


def build_map_prompt(
    item: dict[str, Any],
    chunk: str,
    chunk_index: int,
    chunk_total: int,
) -> str:
    """Prompt for one transcript chunk in map-reduce mode."""
    lines = [
        f"Analyze part {chunk_index} of {chunk_total} of a longer Facebook video transcript.",
        "",
        _field("Title", item.get("title")),
        _field("Author/Page", item.get("author") or item.get("page_name")),
        _field("Content type", item.get("content_type")),
        "",
        "Transcript chunk:",
        chunk,
        "",
        "Summarize this chunk and extract its key facts.",
        "Respond with ONLY a JSON object with keys:",
        '{"chunk_summary": "...", "key_points": ["..."], "entities": ["..."], '
        '"detected_topics": ["..."], "hashtags": ["..."], "call_to_action": "..." or null}',
    ]
    return "\n".join(lines)


def build_reduce_prompt(item: dict[str, Any], partials: list[dict[str, Any]]) -> str:
    """Final prompt combining per-chunk analyses into the full summary."""
    partial_lines: list[str] = []
    for index, partial in enumerate(partials, start=1):
        partial_lines.append(f"--- Analysis of part {index} ---")
        partial_lines.append(
            _field("Chunk summary", partial.get("chunk_summary") or partial.get("summary"))
        )
        partial_lines.append(_field("Key points", partial.get("key_points")))
        partial_lines.append(_field("Entities", partial.get("entities")))
        partial_lines.append(_field("Topics", partial.get("detected_topics") or partial.get("topics")))
        partial_lines.append(_field("Hashtags", partial.get("hashtags")))
        partial_lines.append(_field("Call to action", partial.get("call_to_action")))
        partial_lines.append("")

    lines = [
        "You are given per-segment analyses of one Facebook item. Produce the final"
        " consolidated analysis in Filipino and English.",
        "",
        _field("URL", item.get("source_url")),
        _field("Content type", item.get("content_type")),
        _field("Title", item.get("title")),
        _field("Author/Page", item.get("author") or item.get("page_name")),
        _field("Upload date", item.get("upload_date")),
        _field("Views", item.get("view_count")),
        _field("Likes", item.get("like_count")),
        _field("Comments", item.get("comment_count")),
        _field("Shares", item.get("share_count")),
        _field("Caption (may be truncated)", truncate(item.get("caption") or "", 1500)),
        "",
        *partial_lines,
        RESPONSE_RULES,
    ]
    return "\n".join(lines)
