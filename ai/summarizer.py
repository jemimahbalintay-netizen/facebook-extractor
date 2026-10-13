"""Turn an extracted item into a structured DeepSeek summary.

Long transcripts are handled map-reduce style: each chunk is summarized
individually, then a final call consolidates everything.  ``summarize_pending``
runs batch summarisation straight from the database (no re-fetching needed).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ai.deepseek_client import DeepSeekError, chat_json
from ai.prompts import (
    SYSTEM_PROMPT,
    build_map_prompt,
    build_reduce_prompt,
    build_user_prompt,
)
from config import Settings
from models import ExtractedItem, SummaryPayload

logger = logging.getLogger(__name__)


def chunk_text(text: str, max_chars: int, overlap: int = 500) -> list[str]:
    """Split text into chunks of at most ``max_chars`` characters.

    Splits prefer paragraph/sentence boundaries near the limit so chunks stay
    readable for the model.
    """
    text = text or ""
    if len(text) <= max_chars:
        return [text] if text else []

    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + max_chars, length)
        if end < length:
            window_start = max(start, end - 1000)
            window = text[window_start:end]
            best_cut = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("! "), window.rfind("? "))
            if best_cut > 0:
                end = window_start + best_cut + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = max(end - overlap, start + 1)
    return chunks


def summarize_item(
    item: ExtractedItem,
    settings: Settings,
    transcript: str | None = None,
) -> SummaryPayload:
    """Summarize one item. Raises DeepSeekError subclasses on failure."""
    item_dict: dict[str, Any] = item.model_dump()
    full_text = (transcript or item.transcript_text or "").strip()

    chunks = chunk_text(full_text, max(2000, settings.max_transcript_chars))

    if len(chunks) <= 1:
        data = chat_json(
            settings,
            SYSTEM_PROMPT,
            build_user_prompt(item_dict, chunks[0] if chunks else ""),
        )
        return SummaryPayload.from_model_output(data)

    logger.info(
        "transcript of %d chars split into %d chunks for map-reduce summarisation",
        len(full_text),
        len(chunks),
    )
    partials: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        try:
            partial = chat_json(
                settings,
                SYSTEM_PROMPT,
                build_map_prompt(item_dict, chunk, index, len(chunks)),
                max_tokens=4000,
            )
            partials.append(partial)
        except Exception as exc:  # noqa: BLE001 - keep remaining chunks going
            logger.warning("chunk %d/%d summarisation failed: %s", index, len(chunks), exc)

    if not partials:
        raise DeepSeekError("no transcript chunk could be summarized")

    data = chat_json(settings, SYSTEM_PROMPT, build_reduce_prompt(item_dict, partials))
    return SummaryPayload.from_model_output(data)


# ---------------------------------------------------------------------------
# Batch summarisation from the database
# ---------------------------------------------------------------------------


def _has_summariable_content(record: dict[str, Any]) -> bool:
    if str(record.get("status") or "") in ("skipped", "failed", "pending"):
        return False
    return bool(
        (record.get("caption") or "").strip()
        or (record.get("transcript_text") or "").strip()
        or (record.get("title") or "").strip()
    )


def _record_to_item(record: dict[str, Any]) -> ExtractedItem:
    allowed = set(ExtractedItem.model_fields.keys())
    return ExtractedItem.model_validate(
        {key: value for key, value in record.items() if key in allowed}
    )


def summarize_pending(
    settings: Settings,
    urls: list[str] | None = None,
    limit: int | None = None,
    missing_only: bool = True,
    delay_seconds: float = 1.0,
    stale_only: bool = False,
) -> list[dict[str, Any]]:
    """Summarize stored items straight from the database.

    Selection modes:
    * ``stale_only`` — only items whose stored content changed after their
      summary was generated (see ``summarize --stale``);
    * ``missing_only`` — skip items that already have a summary;
    * neither — summarize everything considered.

    Returns one result record per considered item.
    """
    from database import (
        items_with_summaries,
        save_summary,
        stale_summary_item_ids,
        update_item_fields,
    )
    from utils import utc_now_iso

    records = items_with_summaries(settings.database_path)

    def _normalize(url: str) -> str:
        return (url or "").strip().rstrip("/").lower()

    wanted = {_normalize(url) for url in (urls or [])}
    stale_ids: set[int] = set()
    if stale_only:
        stale_ids = set(stale_summary_item_ids(settings.database_path))
    results: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []

    for record in records:
        source_url = record.get("source_url") or ""
        if wanted and _normalize(source_url) not in wanted:
            continue
        if stale_only:
            if int(record["id"]) not in stale_ids:
                continue
        elif missing_only and record.get("summary"):
            continue
        if not _has_summariable_content(record):
            results.append(
                {
                    "id": record.get("id"),
                    "url": source_url,
                    "status": "skipped",
                    "error": "no caption/transcript to summarize",
                }
            )
            continue
        candidates.append(record)

    if limit:
        candidates = candidates[: int(limit)]

    for index, record in enumerate(candidates):
        if index > 0 and delay_seconds > 0:
            time.sleep(delay_seconds)
        source_url = record.get("source_url") or ""
        logger.info(
            "summarizing %d/%d: %s", index + 1, len(candidates), source_url
        )
        try:
            payload = summarize_item(_record_to_item(record), settings)
        except DeepSeekError as exc:
            logger.warning("summarizing %s failed: %s", source_url, exc)
            results.append(
                {
                    "id": record.get("id"),
                    "url": source_url,
                    "status": "failed",
                    "error": str(exc)[:300],
                }
            )
            continue
        except Exception as exc:  # noqa: BLE001 - keep the batch alive
            logger.exception("unexpected summarisation failure for %s", source_url)
            results.append(
                {
                    "id": record.get("id"),
                    "url": source_url,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}"[:300],
                }
            )
            continue

        item_id = int(record["id"])
        save_summary(item_id, settings.deepseek_model, payload, settings.database_path)
        update_item_fields(
            db_path=settings.database_path,
            item_id=item_id,
            summarized_at=utc_now_iso(),
        )
        logger.info("summary saved for item %s", item_id)
        results.append(
            {
                "id": item_id,
                "url": source_url,
                "status": "ok",
                "short_title": payload.short_title,
                "sentiment": payload.sentiment,
                "key_points": len(payload.key_points),
            }
        )

    return results
