"""Pydantic models shared across extractors, the database and the dashboard."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from utils import json_dumps, utc_now_iso


class ContentType(StrEnum):
    POST = "post"
    REEL = "reel"
    VIDEO = "video"
    HOMEPAGE = "homepage"
    MALFORMED = "malformed"
    UNKNOWN = "unknown"


class ItemStatus(StrEnum):
    PENDING = "pending"
    EXTRACTED = "extracted"
    PARTIAL = "partial"
    NEEDS_LOGIN = "needs_login"
    NEEDS_MANUAL_IMPORT = "needs_manual_import"
    FAILED = "failed"
    SKIPPED = "skipped"


class TranscriptSource(StrEnum):
    SUBTITLES = "subtitles"
    DESCRIPTION = "description"
    WHISPER = "whisper"
    MANUAL = "manual"
    NONE = "none"


class Classification(BaseModel):
    """Result of classifying (and possibly repairing) an input URL."""

    original_url: str
    content_type: ContentType = ContentType.UNKNOWN
    underlying_type: ContentType = ContentType.UNKNOWN
    is_malformed: bool = False
    candidates: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class TranscriptSegment(BaseModel):
    start_seconds: float | None = None
    end_seconds: float | None = None
    text: str = ""


class ExtractedItem(BaseModel):
    """Everything we know about a single Facebook URL."""

    model_config = ConfigDict(use_enum_values=True)

    source_url: str
    resolved_url: str | None = None
    content_type: str = ContentType.UNKNOWN.value
    content_id: str | None = None
    status: str = ItemStatus.PENDING.value
    title: str | None = None
    caption: str | None = None
    transcript_text: str | None = None
    transcript_source: str = TranscriptSource.NONE.value
    transcript_language: str | None = None
    author: str | None = None
    page_name: str | None = None
    upload_date: str | None = None
    duration_seconds: int | None = None
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    share_count: int | None = None
    thumbnail_url: str | None = None
    media_url: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    mentions: list[str] = Field(default_factory=list)
    external_links: list[str] = Field(default_factory=list)
    language: str | None = None
    needs_login: bool = False
    needs_manual_import: bool = False
    malformed: bool = False
    error_message: str | None = None
    extracted_at: str = Field(default_factory=utc_now_iso)


class ExtractionOutcome(BaseModel):
    """Uniform container returned by every extractor implementation."""

    fields: dict[str, Any] = Field(default_factory=dict)
    segments: list[TranscriptSegment] = Field(default_factory=list)
    transcript_text: str | None = None
    transcript_source: str = TranscriptSource.NONE.value
    transcript_language: str | None = None
    needs_login: bool = False
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)

    def has_content(self) -> bool:
        """True when the extractor produced something user-visible."""
        interesting = (
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
        return any(
            self.fields.get(key) not in (None, "", [], {}) for key in interesting
        ) or bool(self.transcript_text)


def _as_str_list(value: Any) -> list[str]:
    """Coerce model output (str / list / None) into a list of strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, (tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"missing", "n/a", "none"}:
            return []
        if "\n" in text:
            return [part.strip(" -*•\t") for part in text.splitlines() if part.strip()]
        if ";" in text:
            return [part.strip() for part in text.split(";") if part.strip()]
        return [text]
    return [str(value)]


class SummaryPayload(BaseModel):
    """Structured AI summary for one item."""

    short_title: str = "missing"
    filipino_summary: str = "missing"
    english_summary: str = "missing"
    key_points: list[str] = Field(default_factory=list)
    detected_topics: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    sentiment: str = "missing"
    content_warnings: list[str] = Field(default_factory=list)
    suggested_tags: list[str] = Field(default_factory=list)
    virality_signals: list[str] = Field(default_factory=list)
    call_to_action: str | None = None

    @classmethod
    def from_model_output(cls, data: dict[str, Any]) -> SummaryPayload:
        """Build a payload tolerantly from whatever JSON the model returned."""
        if not isinstance(data, dict):
            data = {}

        def _first(*keys: str, default: Any = None) -> Any:
            for key in keys:
                if key in data and data[key] is not None:
                    return data[key]
            return default

        def _scalar(value: Any, default: str = "missing") -> str:
            if value is None:
                return default
            if isinstance(value, (list, tuple)):
                joined = "; ".join(str(v) for v in value if str(v).strip())
                return joined or default
            if isinstance(value, dict):
                return json_dumps(value)
            text = str(value).strip()
            return text if text else default

        call_to_action = _first("call_to_action", "cta", default=None)
        if isinstance(call_to_action, (list, tuple)):
            call_to_action = "; ".join(str(v) for v in call_to_action) or None
        elif call_to_action is not None:
            call_to_action = str(call_to_action).strip() or None

        return cls(
            short_title=_scalar(_first("short_title", "title")),
            filipino_summary=_scalar(
                _first("filipino_summary", "summary_filipino", "tl_summary")
            ),
            english_summary=_scalar(
                _first("english_summary", "summary_english", "en_summary")
            ),
            key_points=_as_str_list(_first("key_points", "keypoints")),
            detected_topics=_as_str_list(
                _first("detected_topics", "topics", "detected_topic")
            ),
            hashtags=_as_str_list(_first("hashtags", "hash_tags")),
            entities=_as_str_list(_first("entities", "named_entities")),
            sentiment=_scalar(_first("sentiment")),
            content_warnings=_as_str_list(
                _first("content_warnings", "warnings", "content_warning")
            ),
            suggested_tags=_as_str_list(
                _first("suggested_tags", "tags", "suggested_tag")
            ),
            virality_signals=_as_str_list(
                _first("virality_signals", "virality", "viral_signals")
            ),
            call_to_action=call_to_action,
        )


class ManualImportPayload(BaseModel):
    """Accepted fields for ``main.py manual-import --json-file``."""

    title: str | None = None
    description: str | None = None
    caption: str | None = None
    transcript_text: str | None = None
    author: str | None = None
    page_name: str | None = None
    upload_date: str | None = None
    duration_seconds: int | None = None
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    share_count: int | None = None
    thumbnail_url: str | None = None
    media_url: str | None = None
    hashtags: list[str] | None = None
    language: str | None = None
    content_id: str | None = None
    transcript_segments: list[TranscriptSegment] | None = None
