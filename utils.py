"""Shared helpers: timestamps, text heuristics, hashtag/link extraction."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string (seconds precision)."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Text pattern extraction
# ---------------------------------------------------------------------------

HASHTAG_RE = re.compile(r"#([\w\u00C0-\u024F\u0370-\u03FF\u0400-\u04FF]{1,100})", re.UNICODE)
MENTION_RE = re.compile(r"@([A-Za-z0-9_.\-]{2,75})")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")

_FACEBOOK_LINK_HOSTS = (
    "facebook.com",
    "fb.com",
    "fb.watch",
    "fb.me",
    "m.facebook.com",
    "l.facebook.com",
)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            output.append(value)
    return output


def extract_hashtags(text: str | None) -> list[str]:
    """Return hashtags (without the leading ``#``), de-duplicated."""
    if not text:
        return []
    return _dedupe_preserve_order(HASHTAG_RE.findall(text))


def extract_mentions(text: str | None) -> list[str]:
    """Return @mentions (without the leading ``@``), de-duplicated."""
    if not text:
        return []
    # Avoid treating e-mail addresses as mentions.
    cleaned = re.sub(r"[\w.\-]+@[\w.\-]+\.\w+", " ", text)
    return _dedupe_preserve_order(MENTION_RE.findall(cleaned))


def extract_external_links(text: str | None) -> list[str]:
    """Return http(s) links that do not point at Facebook itself."""
    if not text:
        return []
    links: list[str] = []
    for match in URL_RE.findall(text):
        lowered = match.lower()
        host_part = lowered.split("://", 1)[-1].split("/", 1)[0]
        if any(
            host_part == host or host_part.endswith("." + host)
            for host in _FACEBOOK_LINK_HOSTS
        ):
            continue
        links.append(match.rstrip(".,;:"))
    return _dedupe_preserve_order(links)


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

_FILIPINO_MARKERS = {
    "ang", "ng", "mga", "sa", "ay", "ito", "siya", "kami", "tayo", "kayo",
    "sila", "ako", "ikaw", "naman", "lang", "po", "opo", "hindi", "oo",
    "salamat", "mahal", "pag", "para", "kung", "dahil", "pero", "kapag",
    "maging", "natin", "nila", "niya", "ating", "inyong", "kanilang",
    "napaka", "sobra", "grabe", "talaga", "bakit", "paano", "sino", "ano",
    "saan", "kailan", "gusto", "ayaw", "pwede", "puwede", "meron", "mayroon",
    "wala", "yung", "iyon", "dito", "doon", "ngayon", "bukas", "kahapon",
    "mabuhay", "kuya", "ate", "bes", "lodi", "petmalu", "chismis",
}

_ENGLISH_MARKERS = {
    "the", "and", "you", "that", "this", "with", "have", "for", "not",
    "are", "was", "were", "his", "her", "they", "them", "from", "what",
    "when", "where", "which", "will", "would", "there", "their", "about",
    "just", "like", "people", "watch", "video", "please", "share", "comment",
    "subscribe", "follow", "today", "good", "great", "best", "very",
}

_WORD_RE = re.compile(r"[A-Za-z\u00C0-\u024F]+")


def _heuristic_language(text: str) -> str | None:
    words = [w.lower() for w in _WORD_RE.findall(text)]
    if len(words) < 4:
        return None
    filipino_hits = sum(1 for w in words if w in _FILIPINO_MARKERS)
    english_hits = sum(1 for w in words if w in _ENGLISH_MARKERS)
    if filipino_hits == 0 and english_hits == 0:
        return None
    if filipino_hits > english_hits:
        return "fil"
    if english_hits > filipino_hits:
        return "en"
    return "fil" if filipino_hits >= 3 else "en"


def detect_language(text: str | None) -> str | None:
    """Best-effort language detection.

    Uses ``langdetect`` when installed (optional dependency), otherwise falls
    back to a small Filipino/English marker-word heuristic.  Returns an ISO
    language code such as ``"en"`` or ``"fil"`` or ``None`` when unknown.
    """
    if not text or not text.strip():
        return None
    sample = text.strip()[:2000]

    try:
        from langdetect import DetectorFactory, LangDetectException, detect

        DetectorFactory.seed = 0
        try:
            return detect(sample)
        except LangDetectException:
            logger.debug("langdetect could not classify the sample")
        except Exception as exc:  # noqa: BLE001 - langdetect internals
            logger.debug("langdetect failed: %s", exc)
    except ImportError:
        pass

    return _heuristic_language(sample)


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------


def json_dumps(value: Any) -> str:
    """JSON encode a value for storage in SQLite TEXT columns."""
    return json.dumps(value, ensure_ascii=False)


def safe_int(value: Any) -> int | None:
    """Convert a value to int when possible, otherwise ``None``."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def truncate(text: str | None, limit: int = 500, suffix: str = "...") -> str:
    """Truncate ``text`` to ``limit`` characters for display purposes."""
    if not text:
        return ""
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(suffix))] + suffix


def humanize_duration(seconds: int | None) -> str:
    """Format a duration in seconds as ``1h 02m 03s``-style text."""
    if seconds is None:
        return "missing"
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return "missing"
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def humanize_number(value: int | None) -> str:
    """Format an integer count compactly (12345 -> 12.3K)."""
    if value is None:
        return "missing"
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "missing"
    if abs(number) < 1000:
        return str(number)
    for suffix, scale in (("M", 1_000_000), ("K", 1_000)):
        if abs(number) >= scale:
            compact = number / scale
            return f"{compact:.1f}{suffix}".replace(".0", "")
    return str(number)
