"""Manual import support: pasted text, JSON payloads and saved HTML.

Used when automatic extraction fails because Facebook requires a login or
serves only a truncated preview.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from models import (
    ExtractedItem,
    ManualImportPayload,
    TranscriptSegment,
    TranscriptSource,
)

logger = logging.getLogger(__name__)


class ManualImportError(ValueError):
    """Raised when the manual import input cannot be used."""


def read_text_file(path: str | Path) -> str:
    """Read a text file with a few encoding fallbacks."""
    file_path = Path(path)
    if not file_path.exists():
        raise ManualImportError(f"text file not found: {file_path}")
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return file_path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ManualImportError(f"could not decode {file_path} with common encodings")


def read_json_file(path: str | Path) -> dict[str, Any]:
    """Read a JSON metadata file and validate it against the accepted schema."""
    text = read_text_file(path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManualImportError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ManualImportError(
            "JSON import must be an object with fields like title, caption, "
            "transcript_text, author, view_count, ..."
        )
    return data


def apply_text(
    item: ExtractedItem, text: str
) -> tuple[ExtractedItem, list[TranscriptSegment], bool]:
    """Apply pasted text as caption and/or transcript.

    The user explicitly asked for this import, so:
    * the caption is replaced when the pasted text is longer than the current
      (typically truncated) caption;
    * the transcript is replaced unless it came from real subtitles or a
      whisper transcription (those are kept; use ``--json-file`` with
      ``transcript_text`` to force a replacement).

    Returns ``(item, segments, applied)``.
    """
    text = (text or "").strip()
    if not text:
        raise ManualImportError("imported text is empty")

    applied = False
    segments: list[TranscriptSegment] = []

    current_caption = (item.caption or "").strip()
    if (
        not current_caption or len(text) >= len(current_caption)
    ) and text != current_caption:
        item.caption = text
        applied = True

    transcript_source = str(item.transcript_source or "none").lower()
    if transcript_source not in ("subtitles", "whisper"):
        item.transcript_text = text
        item.transcript_source = TranscriptSource.MANUAL.value
        segments = [TranscriptSegment(start_seconds=0.0, end_seconds=None, text=text)]
        applied = True

    return item, segments, applied


def apply_json(
    item: ExtractedItem, data: dict[str, Any]
) -> tuple[ExtractedItem, list[TranscriptSegment], int]:
    """Apply a validated JSON payload to an item.

    Returns ``(item, segments, applied_field_count)``.
    """
    try:
        payload = ManualImportPayload.model_validate(data)
    except Exception as exc:  # pydantic validation error
        raise ManualImportError(f"invalid manual import payload: {exc}") from exc

    applied = 0
    segments: list[TranscriptSegment] = []

    def _set(field: str, value: Any) -> None:
        nonlocal applied
        if value in (None, ""):
            return
        setattr(item, field, value)
        applied += 1

    _set("title", payload.title)
    _set("caption", payload.caption or payload.description)
    _set("author", payload.author)
    _set("page_name", payload.page_name)
    _set("upload_date", payload.upload_date)
    _set("duration_seconds", payload.duration_seconds)
    _set("view_count", payload.view_count)
    _set("like_count", payload.like_count)
    _set("comment_count", payload.comment_count)
    _set("share_count", payload.share_count)
    _set("thumbnail_url", payload.thumbnail_url)
    _set("media_url", payload.media_url)
    _set("content_id", payload.content_id)
    _set("language", payload.language)
    if payload.hashtags:
        item.hashtags = list(payload.hashtags)
        applied += 1

    if payload.transcript_text:
        item.transcript_text = payload.transcript_text
        item.transcript_source = TranscriptSource.MANUAL.value
        applied += 1
        if payload.transcript_segments:
            segments = list(payload.transcript_segments)
        else:
            segments = [
                TranscriptSegment(
                    start_seconds=0.0,
                    end_seconds=None,
                    text=payload.transcript_text,
                )
            ]
    elif payload.transcript_segments:
        joined = " ".join(
            segment.text for segment in payload.transcript_segments if segment.text
        ).strip()
        if joined:
            item.transcript_text = joined
            item.transcript_source = TranscriptSource.MANUAL.value
            segments = list(payload.transcript_segments)
            applied += 1

    if not applied:
        raise ManualImportError(
            "the JSON payload contained no usable fields; expected keys such as "
            "title, caption, transcript_text, author, view_count, ..."
        )

    return item, segments, applied


def load_saved_html(path: str | Path) -> str:
    """Read a manually saved page (HTML) for the caller to parse."""
    return read_text_file(path)
