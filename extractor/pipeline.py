"""Ingestion pipeline: classify -> extract -> persist -> optionally summarize."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from config import Settings
from database import (
    get_item_by_url,
    get_transcript_segments,
    init_db,
    replace_transcript_segments,
    save_summary,
    update_item_fields,
    upsert_item,
)
from extractor import browser_extractor, facebook_post_extractor, ytdlp_extractor
from extractor.classifier import classify, is_video_like, looks_like_video_url
from extractor.manual_extractor import ManualImportError, apply_json, apply_text
from extractor.net import resolve_redirects
from models import (
    ContentType,
    ExtractedItem,
    ExtractionOutcome,
    ItemStatus,
    TranscriptSegment,
    TranscriptSource,
)
from utils import (
    detect_language,
    extract_external_links,
    extract_hashtags,
    extract_mentions,
    utc_now_iso,
)

logger = logging.getLogger(__name__)

_CORE_CONTENT_FIELDS = (
    "title",
    "caption",
    "transcript_text",
    "author",
    "page_name",
    "thumbnail_url",
    "media_url",
    "duration_seconds",
    "view_count",
)

# Transcript quality ranking. A re-run never downgrades a stored transcript to
# a lower-ranked fresh one (e.g. re-ingesting without --transcribe must not
# replace a whisper transcript with the caption fallback).
_TRANSCRIPT_RANKS = {
    "subtitles": 4,
    "whisper": 3,
    "manual": 2,
    "description": 1,
    "none": 0,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_blank(value: Any) -> bool:
    return value in (None, "", [], {})


def _row_has_content(existing: dict[str, Any]) -> bool:
    """True when a database row already holds useful extracted content."""
    return any(not is_blank(existing.get(field)) for field in _CORE_CONTENT_FIELDS)


def _restorable(field: str, value: Any) -> bool:
    """True when a fresh item's value is empty or a meaningless placeholder."""
    if is_blank(value):
        return True
    text = str(value).strip().lower()
    if field == "transcript_source" and text == "none":
        return True
    return bool(field == "content_type" and text == "unknown")


def _restore_from_existing(item: ExtractedItem, existing: dict[str, Any]) -> None:
    """Copy non-empty previously stored values into a fresh, empty item."""
    skip = {
        "source_url",
        "extracted_at",
        "status",
        "needs_login",
        "needs_manual_import",
        "malformed",
        "error_message",
    }
    for field in ExtractedItem.model_fields:
        if field in skip:
            continue
        if _restorable(field, getattr(item, field, None)) and not is_blank(
            existing.get(field)
        ):
            setattr(item, field, existing[field])


def _segments_from_rows(rows: list[dict[str, Any]]) -> list[TranscriptSegment]:
    return [
        TranscriptSegment(
            start_seconds=row.get("start_seconds"),
            end_seconds=row.get("end_seconds"),
            text=row.get("text") or "",
        )
        for row in rows
    ]


def _merge_outcome(item: ExtractedItem, outcome: ExtractionOutcome) -> None:
    """Fill empty item fields from an extractor outcome (first wins)."""
    for key, value in outcome.fields.items():
        if is_blank(value) or not hasattr(item, key):
            continue
        if is_blank(getattr(item, key)):
            setattr(item, key, value)


def _collect_text(item: ExtractedItem) -> str:
    parts = [item.title, item.caption, item.transcript_text]
    return " ".join(part for part in parts if part)


def _refresh_derived_fields(item: ExtractedItem) -> None:
    combined = _collect_text(item)
    item.hashtags = extract_hashtags(combined) or list(item.hashtags or [])
    item.mentions = extract_mentions(combined) or list(item.mentions or [])
    item.external_links = extract_external_links(combined) or list(item.external_links or [])
    detected = detect_language(combined)
    if detected:
        item.language = detected
    if item.transcript_text and not item.transcript_language:
        heuristic = detect_language(item.transcript_text)
        if heuristic:
            item.transcript_language = heuristic


def _extract_transcript(
    outcomes: list[ExtractionOutcome],
) -> tuple[list[TranscriptSegment], str | None, str, str | None]:
    for outcome in outcomes:
        if outcome.transcript_text:
            return (
                outcome.segments,
                outcome.transcript_text,
                outcome.transcript_source or TranscriptSource.NONE.value,
                outcome.transcript_language,
            )
    return [], None, TranscriptSource.NONE.value, None


def append_jsonl(item: ExtractedItem, settings: Settings) -> None:
    """Append the item as one JSON object to data/extracted.jsonl."""
    settings.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    payload = item.model_dump()
    with settings.jsonl_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _persist(
    item: ExtractedItem, segments: Iterable[TranscriptSegment], settings: Settings
) -> int:
    item_id = upsert_item(item, settings.database_path)
    replace_transcript_segments(item_id, segments, settings.database_path)
    append_jsonl(item, settings)
    return item_id


def _summarize_item(item: ExtractedItem, item_id: int, settings: Settings) -> str | None:
    """Run DeepSeek summarisation. Returns None on success or a reason string."""
    from ai.deepseek_client import DeepSeekError, is_configured
    from ai.summarizer import summarize_item

    if not is_configured(settings):
        return "DEEPSEEK_API_KEY is not set (see .env.example)"

    try:
        payload = summarize_item(item, settings)
        save_summary(item_id, settings.deepseek_model, payload, settings.database_path)
        update_item_fields(
            db_path=settings.database_path,
            item_id=item_id,
            summarized_at=utc_now_iso(),
        )
        logger.info("summarized item %s with %s", item_id, settings.deepseek_model)
        return None
    except DeepSeekError as exc:
        logger.warning("summarisation failed for item %s: %s", item_id, exc)
        return str(exc)[:300]
    except Exception as exc:  # noqa: BLE001 - never break ingestion over the AI step
        logger.exception("unexpected summarisation failure for item %s", item_id)
        return f"{type(exc).__name__}: {exc}"[:300]


# ---------------------------------------------------------------------------
# Single URL processing
# ---------------------------------------------------------------------------


def process_url(
    url: str,
    settings: Settings,
    transcribe: bool = False,
    summarize: bool = False,
) -> dict[str, Any]:
    """Run the full pipeline for one URL and return a short result record."""
    classification = classify(url)
    item = ExtractedItem(
        source_url=classification.original_url or (url or "").strip(),
        content_type=classification.content_type.value,
        malformed=classification.is_malformed,
    )
    record: dict[str, Any] = {
        "url": item.source_url,
        "content_type": item.content_type,
        "malformed": classification.is_malformed,
        "notes": list(classification.notes),
    }
    for note in classification.notes:
        logger.info("classifier: %s -> %s", item.source_url, note)

    if not classification.candidates:
        item.status = ItemStatus.FAILED.value
        item.needs_manual_import = True
        item.error_message = (
            "; ".join(classification.notes) or "no candidate URL to attempt"
        )
        item_id = _persist(item, [], settings)
        record.update(
            {"id": item_id, "status": item.status, "error": item.error_message}
        )
        return record

    if classification.content_type == ContentType.HOMEPAGE:
        item.status = ItemStatus.SKIPPED.value
        item.error_message = "facebook homepage - nothing to extract"
        item_id = _persist(item, [], settings)
        record.update(
            {"id": item_id, "status": item.status, "error": item.error_message}
        )
        return record

    outcomes: list[ExtractionOutcome] = []
    effective = classification.underlying_type
    video_first = is_video_like(effective) or (
        effective in (ContentType.UNKNOWN, ContentType.MALFORMED)
        and looks_like_video_url(classification.candidates[0])
    )

    if video_first:
        for candidate in classification.candidates:
            resolved, _status_code, resolve_error = resolve_redirects(candidate, settings)
            if resolve_error:
                logger.warning("redirect resolution failed for %s: %s", candidate, resolve_error)
            target = resolved or candidate
            if target != candidate and is_blank(item.resolved_url):
                item.resolved_url = target

            outcome = ytdlp_extractor.extract_video(target, settings, transcribe=transcribe)
            outcomes.append(outcome)
            if outcome.has_content() or outcome.needs_login:
                break

            # yt-dlp could not read it: the page may still expose public OG
            # metadata (e.g. a post that merely looks like a video URL).
            post_outcome = facebook_post_extractor.extract_post(target, settings)
            outcomes.append(post_outcome)
            if post_outcome.has_content():
                break
    else:
        for candidate in classification.candidates:
            outcome = facebook_post_extractor.extract_post(candidate, settings)
            outcomes.append(outcome)
            if outcome.has_content() or outcome.needs_login:
                break

    if not any(outcome.has_content() for outcome in outcomes) and settings.enable_playwright:
        browser_outcome = browser_extractor.extract_with_browser(
            classification.candidates[0], settings
        )
        outcomes.append(browser_outcome)

    for outcome in outcomes:
        _merge_outcome(item, outcome)

    segments, transcript_text, transcript_source, transcript_language = _extract_transcript(
        outcomes
    )
    if transcript_text:
        item.transcript_text = transcript_text
        item.transcript_source = transcript_source
        if transcript_language:
            item.transcript_language = transcript_language
    elif item.caption:
        # Priority order: subtitles -> whisper -> description -> manual -> none.
        item.transcript_text = item.caption
        item.transcript_source = TranscriptSource.DESCRIPTION.value

    errors = [outcome.error for outcome in outcomes if outcome.error]
    warnings = [w for outcome in outcomes for w in outcome.warnings]
    needs_login = any(outcome.needs_login for outcome in outcomes)
    truncated_preview = any("truncated" in w.lower() for w in warnings)

    has_content = any(
        not is_blank(getattr(item, field, None)) for field in _CORE_CONTENT_FIELDS
    )

    # Data safety and manual-import precedence when a row already exists:
    #  * a refresh that produces nothing never overwrites good data;
    #  * a refresh that succeeds only enriches blanks (never erases counts,
    #    urls, media links, ...);
    #  * manually imported captions/transcripts stay sticky unless the fresh
    #    run found real subtitles or a whisper transcription.
    preserved = False
    kept_previous = False
    existing = get_item_by_url(item.source_url, settings.database_path)
    existing_has_content = existing is not None and _row_has_content(existing)

    if existing is not None and existing_has_content and not has_content:
        _restore_from_existing(item, existing)
        segments = _segments_from_rows(
            get_transcript_segments(int(existing["id"]), settings.database_path)
        )
        preserved = True
        has_content = True
        logger.warning(
            "refresh of %s produced no content; keeping previous data (status=%s)",
            item.source_url,
            existing.get("status"),
        )
    elif existing is not None and existing_has_content:
        _restore_from_existing(item, existing)
        existing_source = str(existing.get("transcript_source") or "none").lower()
        fresh_source = str(item.transcript_source or "none").lower()
        if _TRANSCRIPT_RANKS.get(existing_source, 0) > _TRANSCRIPT_RANKS.get(
            fresh_source, 0
        ):
            if existing.get("caption") and len(existing.get("caption") or "") > len(
                item.caption or ""
            ):
                item.caption = existing["caption"]
            if existing.get("transcript_text"):
                item.transcript_text = existing["transcript_text"]
                item.transcript_source = existing_source
                item.transcript_language = (
                    existing.get("transcript_language") or item.transcript_language
                )
                existing_segments = _segments_from_rows(
                    get_transcript_segments(int(existing["id"]), settings.database_path)
                )
                if existing_segments:
                    segments = existing_segments
            kept_previous = True
            logger.info(
                "kept stored '%s' transcript for %s (fresh run produced '%s')",
                existing_source,
                item.source_url,
                fresh_source,
            )

    item.needs_login = needs_login
    if has_content:
        item.status = (
            ItemStatus.PARTIAL.value
            if (needs_login or truncated_preview)
            else ItemStatus.EXTRACTED.value
        )
        item.needs_manual_import = truncated_preview or (
            needs_login and is_blank(item.caption)
        )
    else:
        item.status = (
            ItemStatus.NEEDS_LOGIN.value if needs_login else ItemStatus.NEEDS_MANUAL_IMPORT.value
        )
        item.needs_manual_import = True

    unique_errors = list(dict.fromkeys(error for error in errors if error))
    error_message = "; ".join(unique_errors)
    if not error_message and warnings:
        error_message = "notes: " + "; ".join(dict.fromkeys(warnings))
    item.error_message = error_message[:2000] if error_message else None

    if preserved and existing is not None:
        item.status = str(existing.get("status") or ItemStatus.EXTRACTED.value)
        item.needs_login = bool(existing.get("needs_login"))
        item.needs_manual_import = bool(existing.get("needs_manual_import"))
        note = (
            "refresh produced no content; kept previous data. "
            f"fresh run note: {error_message or 'none'}"
        )
        item.error_message = note[:2000]
        item.extracted_at = utc_now_iso()
    elif kept_previous and existing is not None:
        item.status = str(existing.get("status") or ItemStatus.EXTRACTED.value)
        item.needs_login = bool(existing.get("needs_login"))
        item.needs_manual_import = bool(existing.get("needs_manual_import"))
        item.error_message = None

    _refresh_derived_fields(item)
    item_id = _persist(item, segments, settings)

    record.update(
        {
            "id": item_id,
            "status": item.status,
            "resolved_url": item.resolved_url,
            "title": item.title,
            "author": item.author,
            "transcript_source": item.transcript_source,
            "transcript_chars": len(item.transcript_text or ""),
            "needs_login": item.needs_login,
            "needs_manual_import": item.needs_manual_import,
            "error": item.error_message,
            "warnings": warnings[:5],
            "preserved_previous": preserved,
            "kept_previous": kept_previous,
        }
    )

    if summarize or settings.auto_summarize:
        summary_error = _summarize_item(item, item_id, settings)
        record["summary"] = "ok" if summary_error is None else f"skipped: {summary_error}"

    return record


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------


def load_urls_from_file(path: str | Path) -> list[str]:
    """Read newline-separated URLs, ignoring blanks and ``#`` comments."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"URL file not found: {file_path}")
    urls: list[str] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


# Statuses that it is worth re-attempting (everything else counts as "done").
RETRYABLE_STATUSES = ("failed", "needs_login", "needs_manual_import")


def filter_existing_urls(
    urls: Iterable[str],
    settings: Settings,
    retryable: Iterable[str] = RETRYABLE_STATUSES,
) -> tuple[list[str], int]:
    """Drop URLs that already have content (``ingest --skip-existing``).

    URLs not present in the database are kept, as are URLs whose last run
    failed (they are worth retrying).  Returns ``(kept_urls, skipped_count)``.
    """
    from database import existing_statuses

    statuses = existing_statuses(settings.database_path)
    allowed = {str(status) for status in retryable}
    kept: list[str] = []
    skipped = 0
    for url in urls:
        status = statuses.get(url)
        if status is None or status in allowed:
            kept.append(url)
        else:
            skipped += 1
    return kept, skipped


def _record_failure(url: str, exc: Exception, settings: Settings) -> dict[str, Any]:
    """Persist a failed URL so nothing is lost when a crash occurs."""
    classification = classify(url)
    item = ExtractedItem(
        source_url=classification.original_url or (url or "").strip() or "unknown-url",
        content_type=classification.content_type.value,
        status=ItemStatus.FAILED.value,
        malformed=classification.is_malformed,
        needs_manual_import=True,
        error_message=f"{type(exc).__name__}: {exc}"[:2000],
    )
    _refresh_derived_fields(item)
    item_id = _persist(item, [], settings)
    return {
        "id": item_id,
        "url": item.source_url,
        "content_type": item.content_type,
        "status": item.status,
        "needs_login": False,
        "needs_manual_import": True,
        "transcript_source": item.transcript_source,
        "transcript_chars": 0,
        "error": item.error_message,
    }


def ingest_urls(
    urls: Iterable[str],
    settings: Settings,
    transcribe: bool = False,
    summarize: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Process a batch of URLs politely (delay between requests)."""
    init_db(settings.database_path)
    cleaned = [url.strip() for url in urls if url and url.strip()]
    if limit:
        cleaned = cleaned[: int(limit)]
    total = len(cleaned)
    results: list[dict[str, Any]] = []

    for index, url in enumerate(cleaned):
        if index > 0:
            time.sleep(max(0.0, settings.facebook_delay_seconds))
        logger.info("processing %d/%d: %s", index + 1, total, url)
        try:
            record = process_url(url, settings, transcribe=transcribe, summarize=summarize)
        except Exception as exc:  # noqa: BLE001 - keep the batch alive
            logger.exception("unhandled error while processing %s", url)
            record = _record_failure(url, exc, settings)
        record["index"] = index + 1
        record["total"] = total
        results.append(record)

    return results


# ---------------------------------------------------------------------------
# Manual import
# ---------------------------------------------------------------------------


def _item_from_existing(existing: dict[str, Any]) -> ExtractedItem:
    allowed = set(ExtractedItem.model_fields.keys())
    data = {key: value for key, value in existing.items() if key in allowed}
    return ExtractedItem.model_validate(data)


def manual_import(
    url: str,
    settings: Settings,
    text: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply a manual text/JSON import to the item identified by ``url``."""
    init_db(settings.database_path)
    if text is None and payload is None:
        raise ManualImportError("provide either text or a JSON payload")

    existing = get_item_by_url(url, settings.database_path)
    item = _item_from_existing(existing) if existing else ExtractedItem(source_url=url)
    item.source_url = url  # ensure the unique key is exactly what the user typed

    all_segments: list[TranscriptSegment] = []
    applied = 0

    if text is not None:
        item, segments, text_applied = apply_text(item, text)
        all_segments.extend(segments)
        applied += 1 if text_applied else 0

    if payload is not None:
        item, segments, json_applied = apply_json(item, payload)
        all_segments.extend(segments)
        applied += json_applied

    if applied == 0:
        raise ManualImportError(
            "nothing was imported: the pasted text was not longer than the "
            "existing caption and the transcript came from subtitles/whisper "
            "(use --json-file with transcript_text to force a replacement)"
        )

    item.status = ItemStatus.EXTRACTED.value
    item.needs_manual_import = False
    item.needs_login = False
    item.error_message = None
    item.extracted_at = utc_now_iso()
    _refresh_derived_fields(item)

    item_id = _persist(item, all_segments, settings)
    return {
        "id": item_id,
        "url": url,
        "status": item.status,
        "caption_chars": len(item.caption or ""),
        "transcript_chars": len(item.transcript_text or ""),
        "transcript_source": item.transcript_source,
        "applied_fields": applied,
    }
