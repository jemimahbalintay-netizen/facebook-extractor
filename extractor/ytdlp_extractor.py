"""Video/reel metadata + subtitle extraction built on yt-dlp."""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config import Settings
from extractor.net import build_session
from extractor.subtitles import (
    parse_subtitle_payload,
    pick_subtitle_format,
    pick_subtitle_track,
)
from extractor.transcript_extractor import (
    TranscriptionUnavailable,
    transcribe_audio,
)
from models import ExtractionOutcome, TranscriptSource

logger = logging.getLogger(__name__)

# Auto-generated caption tracks occasionally contain a single stray character;
# treat anything shorter than this as unusable and fall back to the caption.
MIN_SUBTITLE_TEXT_CHARS = 20

# Whisper hallucinates short junk phrases (often in other languages) when a
# video has no speech at all; results below this length are discarded in
# favour of the caption text.
MIN_WHISPER_TEXT_CHARS = 20

# Error message fragments that indicate authentication/private content rather
# than a transient failure.  The Facebook-specific strings come from observed
# behaviour and yt-dlp's canonical login hint ("This video is only available
# for registered users. Use --cookies-from-browser or --cookies ..."):
# gated /share/p/ posts redirect to /posts/pfbid... and then fail with
# "Cannot parse data" or "Unable to download webpage: HTTP Error 404".
# (Facebook returns 404-style errors for both deleted and login-gated posts,
# so the caller's manual-import fallback is what preserves the item.)
LOGIN_ERROR_MARKERS = (
    "login",
    "log in",
    "sign in",
    "sign-in",
    "registered users",
    "cookies-from-browser",
    "for the authentication",
    "requires authentication",
    "not authorized",
    "you must be logged in",
    "private video",
    "private content",
    "cannot parse data",
    "unable to download webpage",
    "http error 404",
    "rate-limit reached",
    "unable to extract",
    "no video formats found",
)


def looks_like_login_error(message: str) -> bool:
    lowered = (message or "").lower()
    return any(marker in lowered for marker in LOGIN_ERROR_MARKERS)


def _base_ydl_opts(settings: Settings) -> dict[str, Any]:
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": settings.request_timeout,
        "retries": max(1, min(settings.max_retries, 3)),
        "extractor_retries": 2,
        "http_headers": {
            "User-Agent": settings.user_agent,
            "Accept-Language": "en-US,en;q=0.9,fil;q=0.8",
        },
        "ignoreerrors": False,
    }
    if settings.cookie_file and settings.cookie_file.exists():
        options["cookiefile"] = str(settings.cookie_file)
        logger.info("using cookie file %s", settings.cookie_file)
    return options


def _normalize_upload_date(info: dict[str, Any]) -> str | None:
    raw_date = info.get("upload_date")
    if raw_date and isinstance(raw_date, str) and len(raw_date) == 8 and raw_date.isdigit():
        return f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
    timestamp = info.get("timestamp") or info.get("release_timestamp")
    if timestamp:
        try:
            return datetime.fromtimestamp(float(timestamp), tz=UTC).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _pick_thumbnail(info: dict[str, Any]) -> str | None:
    thumbnail = info.get("thumbnail")
    if thumbnail:
        return str(thumbnail)
    thumbnails = info.get("thumbnails") or []
    if thumbnails:
        last = thumbnails[-1] or {}
        if last.get("url"):
            return str(last["url"])
    return None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


_COUNT_TOKEN_RE = re.compile(r"([\d][\d.,]*\s*[KMB]?)\s*(?P<unit>views|reactions|likes|comments|shares)", re.IGNORECASE)
_COUNT_UNIT_MAP = {
    "views": "view_count",
    "reactions": "like_count",
    "likes": "like_count",
    "comments": "comment_count",
    "shares": "share_count",
}


def parse_compact_number(token: str) -> int | None:
    """Parse compact count text like ``49K``, ``1.2M`` or ``12,345``."""
    cleaned = (token or "").strip().replace(",", "").replace(" ", "")
    if not cleaned:
        return None
    multiplier = 1
    suffix = cleaned[-1].upper()
    if suffix in ("K", "M", "B"):
        multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[suffix]
        cleaned = cleaned[:-1]
    try:
        return int(float(cleaned) * multiplier)
    except ValueError:
        return None


def fill_missing_counts_from_text(fields: dict[str, Any]) -> None:
    """Fill missing view/like/comment/share counts from title/description text.

    Facebook page titles often look like
    ``"49K views · 387 reactions | Some caption..."``.
    """
    text = " ".join(
        str(fields.get(key) or "") for key in ("title", "caption")
    )
    if not text.strip():
        return
    for match in _COUNT_TOKEN_RE.finditer(text):
        field = _COUNT_UNIT_MAP.get(match.group("unit").lower())
        if not field or fields.get(field) is not None:
            continue
        value = parse_compact_number(match.group(1))
        if value is not None:
            fields[field] = value
    if fields.get("view_count") is None:
        views_match = re.search(r"([\d][\d.,]*\s*[KMB]?)\s*views", text, re.IGNORECASE)
        if views_match:
            fields["view_count"] = parse_compact_number(views_match.group(1))


def map_info_to_fields(info: dict[str, Any], fallback_url: str) -> dict[str, Any]:
    """Map a yt-dlp info dict onto our item field names."""
    title = (info.get("title") or "").strip() or None
    description = info.get("description")
    if isinstance(description, str):
        description = description.strip() or None

    author = (
        info.get("uploader")
        or info.get("channel")
        or info.get("creator")
        or (info.get("uploader_id") if not str(info.get("uploader_id", "")).startswith("http") else None)
    )
    page_name = info.get("channel") or info.get("uploader")

    fields: dict[str, Any] = {
        "resolved_url": info.get("webpage_url") or fallback_url,
        "content_id": str(info.get("id")) if info.get("id") is not None else None,
        "title": title,
        "caption": description,
        "author": str(author).strip() if author else None,
        "page_name": str(page_name).strip() if page_name else None,
        "upload_date": _normalize_upload_date(info),
        "duration_seconds": _int_or_none(info.get("duration")),
        "view_count": _int_or_none(info.get("view_count")),
        "like_count": _int_or_none(info.get("like_count")),
        "comment_count": _int_or_none(info.get("comment_count")),
        "share_count": _int_or_none(info.get("repost_count")),
        "thumbnail_url": _pick_thumbnail(info),
        "media_url": info.get("url") or None,
    }
    fill_missing_counts_from_text(fields)
    return fields


def _fetch_subtitles(
    info: dict[str, Any], settings: Settings
) -> tuple[list, str | None, str | None, str | None]:
    """Fetch and parse the best available subtitle/caption track.

    Returns ``(segments, text, language, source)``.
    """
    tracks_sets = [
        ("subtitles", info.get("subtitles") or {}),
        ("automatic_captions", info.get("automatic_captions") or {}),
    ]
    for source_name, tracks in tracks_sets:
        language, entries = pick_subtitle_track(tracks)
        if not language or not entries:
            continue
        format_entry = pick_subtitle_format(entries)
        if not format_entry:
            continue
        url = format_entry.get("url")
        if not url:
            continue
        ext = format_entry.get("ext") or "vtt"
        try:
            session = build_session(settings)
            response = session.get(
                url,
                timeout=settings.request_timeout,
                headers={
                    "Referer": info.get("webpage_url") or "https://www.facebook.com/",
                    "User-Agent": settings.user_agent,
                },
            )
            response.raise_for_status()
            segments = parse_subtitle_payload(response.text, ext)
            if segments:
                text = " ".join(segment.text for segment in segments).strip()
                if len(text) < MIN_SUBTITLE_TEXT_CHARS:
                    logger.warning(
                        "ignoring unusable subtitle track (%s, %s): only %d chars",
                        source_name,
                        language,
                        len(text),
                    )
                    continue
                logger.info(
                    "captured %d subtitle segments (lang=%s, source=%s)",
                    len(segments),
                    language,
                    source_name,
                )
                return segments, text, language, TranscriptSource.SUBTITLES.value
        except Exception as exc:  # noqa: BLE001 - subtitle fetch is best effort
            logger.warning("subtitle download failed (%s, %s): %s", source_name, language, exc)
    return [], None, None, None


def _download_audio_and_transcribe(
    url: str, settings: Settings, outcome: ExtractionOutcome
) -> None:
    """Download audio to a temp dir, transcribe it, then delete the audio."""
    temp_dir = Path(tempfile.mkdtemp(prefix="fbx_audio_"))
    try:
        try:
            from yt_dlp import YoutubeDL
        except ImportError as exc:
            outcome.warnings.append(f"yt-dlp not installed: {exc}")
            return

        options = _base_ydl_opts(settings)
        options.update(
            {
                "skip_download": False,
                "format": "bestaudio/best",
                "outtmpl": str(temp_dir / "%(id)s.%(ext)s"),
                "noprogress": True,
            }
        )
        with YoutubeDL(options) as ydl:
            ydl.download([url])

        audio_files = [path for path in temp_dir.iterdir() if path.is_file()]
        if not audio_files:
            outcome.warnings.append("audio download produced no files")
            return
        audio_path = max(audio_files, key=lambda path: path.stat().st_size)
        logger.info("downloaded audio for transcription: %s", audio_path.name)

        try:
            segments, text, language = transcribe_audio(audio_path, settings)
        except TranscriptionUnavailable as exc:
            outcome.warnings.append(str(exc))
            return

        if segments and text:
            if len(text) < MIN_WHISPER_TEXT_CHARS:
                logger.warning(
                    "discarding whisper result for %s: only %d chars (%r)",
                    audio_path.name,
                    len(text),
                    text[:50],
                )
                outcome.warnings.append(
                    f"whisper produced only {len(text)} chars (likely a "
                    "hallucination on music/no-speech audio); using the caption "
                    "as the transcript instead"
                )
                return
            outcome.segments = segments
            outcome.transcript_text = text
            outcome.transcript_language = language
            outcome.transcript_source = TranscriptSource.WHISPER.value
            logger.info("whisper produced %d segments", len(segments))
        else:
            outcome.warnings.append("whisper returned no segments")
    except Exception as exc:  # noqa: BLE001 - transcription is best effort
        message = f"{type(exc).__name__}: {exc}"
        logger.warning("audio transcription failed: %s", message)
        outcome.warnings.append(f"transcription failed: {message[:500]}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def extract_video(
    url: str, settings: Settings, transcribe: bool = False
) -> ExtractionOutcome:
    """Extract metadata (and optionally a transcript) for a video/reel URL."""
    outcome = ExtractionOutcome()

    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        outcome.error = "yt-dlp is not installed; run `pip install yt-dlp`"
        return outcome

    info: dict[str, Any] | None = None
    try:
        with YoutubeDL(_base_ydl_opts(settings)) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001 - yt-dlp raises many error types
        message = f"{type(exc).__name__}: {exc}"
        outcome.error = message[:1500]
        outcome.needs_login = looks_like_login_error(message)
        return outcome

    if not isinstance(info, dict):
        outcome.error = "yt-dlp returned no metadata for this URL"
        return outcome

    outcome.fields = map_info_to_fields(info, url)

    segments, text, language, source = _fetch_subtitles(info, settings)
    if segments and text:
        outcome.segments = segments
        outcome.transcript_text = text
        outcome.transcript_language = language
        outcome.transcript_source = source or TranscriptSource.SUBTITLES.value
    elif transcribe:
        webpage_url = info.get("webpage_url") or url
        _download_audio_and_transcribe(webpage_url, settings, outcome)

    return outcome
