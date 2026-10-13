"""JSON export: a full dump of items, summaries and transcript segments."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from config import Settings
from database import get_transcript_segments, items_with_summaries
from utils import utc_now_iso

logger = logging.getLogger(__name__)


def build_export_payload(settings: Settings) -> dict[str, Any]:
    items = items_with_summaries(settings.database_path)
    exported_items: list[dict[str, Any]] = []
    for item in items:
        exported_items.append(
            {
                **item,
                "transcript_segments": get_transcript_segments(
                    int(item["id"]), settings.database_path
                ),
            }
        )
    return {
        "generated_at": utc_now_iso(),
        "database_path": str(settings.database_path),
        "item_count": len(exported_items),
        "items": exported_items,
    }


def export_json(settings: Settings, output_path: Path | None = None) -> Path:
    """Write data/export_items.json and return the path."""
    path = output_path or settings.json_export_path
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_export_payload(settings)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info("JSON export written: %s (%d items)", path, payload["item_count"])
    return path
