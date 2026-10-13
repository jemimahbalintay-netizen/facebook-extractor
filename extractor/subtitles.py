"""Subtitle/caption parsing for the formats yt-dlp exposes.

Supported payload formats: WebVTT (``vtt``), SubRip (``srt``), YouTube-style
JSON3 (``json3``) and TTML/XML (``ttml``/``xml``).
"""

from __future__ import annotations

import html
import json
import logging
import re
from typing import Any

from models import TranscriptSegment

logger = logging.getLogger(__name__)

SUBTITLE_LANG_PREFERENCE = [
    "en",
    "en-us",
    "en-gb",
    "en-ph",
    "fil",
    "tl",
    "fil-ph",
    "ceb",
    "es",
]

SUBTITLE_FORMAT_PREFERENCE = ["json3", "vtt", "srt", "ttml", "xml"]

_TAG_RE = re.compile(r"<[^>]+>")
_TIMESTAMP_RE = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[.,](?P<ms>\d{1,3})"
)


def _clean_text(text: str) -> str:
    text = _TAG_RE.sub(" ", text or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    # Replacing inline tags with a space can leave a stray space before
    # punctuation ("tama ?" -> "tama?").
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text


def parse_timestamp(value: str) -> float | None:
    """Parse ``00:00:01.500`` / ``00:00:01,500`` / ``1.5s`` / ``150ms``."""
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    match = _TIMESTAMP_RE.search(value)
    if match:
        hours = int(match.group("h"))
        minutes = int(match.group("m"))
        seconds = int(match.group("s"))
        millis = int(match.group("ms").ljust(3, "0"))
        return hours * 3600 + minutes * 60 + seconds + millis / 1000.0
    lowered = value.lower()
    try:
        if lowered.endswith("ms"):
            return float(lowered[:-2]) / 1000.0
        if lowered.endswith("s"):
            return float(lowered[:-1])
        if lowered.endswith("m"):
            return float(lowered[:-1]) * 60
        return float(lowered)
    except ValueError:
        return None


def parse_vtt(payload: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    lines = (payload or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if "-->" in line:
            parts = line.split("-->")
            start = parse_timestamp(parts[0].strip())
            end = parse_timestamp(parts[1].split()[0].strip()) if len(parts) > 1 else None
            index += 1
            buffer: list[str] = []
            while index < len(lines) and lines[index].strip():
                buffer.append(lines[index].strip())
                index += 1
            text = _clean_text(" ".join(buffer))
            if text:
                segments.append(
                    TranscriptSegment(start_seconds=start, end_seconds=end, text=text)
                )
        else:
            index += 1
    return segments


def parse_srt(payload: str) -> list[TranscriptSegment]:
    # SRT is structurally identical to VTT for our purposes.
    return parse_vtt(payload)


def parse_json3(payload: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.warning("could not parse json3 subtitle payload")
        return segments

    for event in data.get("events", []) or []:
        pieces = event.get("segs") or []
        text = _clean_text("".join(piece.get("utf8", "") for piece in pieces))
        if not text:
            continue
        start_ms = event.get("tStartMs")
        duration_ms = event.get("dDurationMs")
        start = start_ms / 1000.0 if isinstance(start_ms, (int, float)) else None
        end = (
            (start_ms + duration_ms) / 1000.0
            if isinstance(start_ms, (int, float)) and isinstance(duration_ms, (int, float))
            else None
        )
        segments.append(
            TranscriptSegment(start_seconds=start, end_seconds=end, text=text)
        )
    return segments


_TTML_RE = re.compile(r"<p\b([^>]*)>(.*?)</p>", re.IGNORECASE | re.DOTALL)
_ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def parse_ttml(payload: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    for attrs_raw, body in _TTML_RE.findall(payload or ""):
        attrs = dict(_ATTR_RE.findall(attrs_raw))
        start = parse_timestamp(attrs.get("begin", ""))
        end = parse_timestamp(attrs.get("end", ""))
        if end is None and attrs.get("dur"):
            duration = parse_timestamp(attrs["dur"])
            if start is not None and duration is not None:
                end = start + duration
        text = _clean_text(body)
        if text:
            segments.append(
                TranscriptSegment(start_seconds=start, end_seconds=end, text=text)
            )
    return segments


def parse_subtitle_payload(payload: str, ext: str) -> list[TranscriptSegment]:
    """Dispatch to the right parser based on the subtitle extension."""
    ext = (ext or "").lower().lstrip(".")
    try:
        if ext == "json3":
            return parse_json3(payload)
        if ext in ("vtt", "webvtt"):
            return parse_vtt(payload)
        if ext == "srt":
            return parse_srt(payload)
        if ext in ("ttml", "xml", "dfxp"):
            return parse_ttml(payload)
        # Unknown extension: try VTT, then SRT, then TTML.
        for parser in (parse_vtt, parse_srt, parse_ttml):
            segments = parser(payload)
            if segments:
                return segments
    except Exception as exc:  # noqa: BLE001 - parsing must never crash ingestion
        logger.warning("subtitle parsing failed for ext=%s: %s", ext, exc)
    return []


def pick_subtitle_track(
    tracks: dict[str, Any],
) -> tuple[str | None, list[dict[str, Any]] | None]:
    """Pick the preferred language track from a yt-dlp subtitles dict."""
    if not tracks:
        return None, None
    normalized = {str(key).lower(): key for key in tracks}

    for preference in SUBTITLE_LANG_PREFERENCE:
        if preference in normalized:
            key = normalized[preference]
            return str(key), tracks.get(key)

    # Fall back to any language that is not an obviously unusable entry.
    for key, entries in tracks.items():
        if entries:
            return str(key), entries
    return None, None


def pick_subtitle_format(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the most easily parsed format entry that has a download URL."""
    if not entries:
        return None
    by_ext = {
        str(entry.get("ext", "")).lower(): entry
        for entry in entries
        if entry.get("url")
    }
    for preferred in SUBTITLE_FORMAT_PREFERENCE:
        if preferred in by_ext:
            return by_ext[preferred]
    for entry in entries:
        if entry.get("url"):
            return entry
    return None
