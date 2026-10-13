"""Public metadata extraction for Facebook post URLs via plain HTTP.

Only publicly served HTML is read (the same HTML any browser or link-preview
crawler would receive).  Nothing attempts to bypass a login wall: when
Facebook demands authentication the outcome is flagged ``needs_login``.
"""

from __future__ import annotations

import json
import logging
import re
from html import unescape
from typing import Any

import requests

from config import LINK_PREVIEW_USER_AGENT, Settings
from extractor.net import (
    build_session,
    looks_like_login_wall,
    request_with_retries,
    resolve_redirects,
)
from models import ExtractionOutcome

logger = logging.getLogger(__name__)

_META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_META_PROPERTY_FIRST_RE = re.compile(
    r'(?:property|name)\s*=\s*["\']([^"\']+)["\'][^>]*?content\s*=\s*["\']([^"\']*)["\']',
    re.IGNORECASE | re.DOTALL,
)
_META_CONTENT_FIRST_RE = re.compile(
    r'content\s*=\s*["\']([^"\']*)["\'][^>]*?(?:property|name)\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE | re.DOTALL,
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_JSONLD_RE = re.compile(
    r'<script[^>]+type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)

_ID_PATTERNS = (
    re.compile(r"/posts/(\d+)"),
    re.compile(r"/videos/(\d+)"),
    re.compile(r"/reel/(\d+)"),
    re.compile(r"[?&]story_fbid=(\d+)"),
    re.compile(r"[?&]fbid=(\d+)"),
)

_GENERIC_DESCRIPTION_MARKERS = (
    "see posts, photos and more on facebook",
    "log in or sign up to view",
    "log into facebook",
)

_PREVIEW_TITLE_RE = re.compile(
    r"^See more of .+? on Facebook\.?$", re.IGNORECASE
)

# Titles that Facebook error/login pages expose and that carry no content.
_JUNK_TITLES = {
    "error",
    "facebook",
    "log in",
    "log into facebook",
    "login",
    "content not found",
    "page not found",
    "this content isn't available right now",
    "this content is not available",
    "not found",
}


def _clean_title(title: str | None) -> str | None:
    """Drop placeholder titles served by error/login pages."""
    if not title:
        return None
    cleaned = title.strip()
    if not cleaned:
        return None
    lowered = cleaned.lower().rstrip("!.")
    if lowered in _JUNK_TITLES:
        return None
    if lowered.startswith("error") and len(lowered) <= 30:
        return None
    if re.fullmatch(r"(log ?in|sign ?up)(\s*\|\s*facebook)?", lowered):
        return None
    return cleaned


def parse_html_metadata(page_html: str) -> dict[str, str]:
    """Collect ``<meta>`` values (og:, article:, name=...) from raw HTML."""
    metadata: dict[str, str] = {}
    for tag in _META_TAG_RE.findall(page_html or ""):
        match = _META_PROPERTY_FIRST_RE.search(tag)
        if match:
            key, value = match.group(1), match.group(2)
        else:
            match = _META_CONTENT_FIRST_RE.search(tag)
            if not match:
                continue
            value, key = match.group(1), match.group(2)
        key = key.strip().lower()
        value = unescape(value or "").strip()
        if key and value and key not in metadata:
            metadata[key] = value

    title_match = _TITLE_RE.search(page_html or "")
    if title_match:
        metadata.setdefault("title", unescape(title_match.group(1)).strip())
    return metadata


def parse_json_ld(page_html: str) -> dict[str, Any]:
    """Best-effort extraction of article-ish fields from JSON-LD blocks."""
    result: dict[str, Any] = {}
    for block in _JSONLD_RE.findall(page_html or ""):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        candidates = data if isinstance(data, list) else [data]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if candidate.get("articleBody") and "articleBody" not in result:
                result["articleBody"] = str(candidate["articleBody"])
            if candidate.get("headline") and "headline" not in result:
                result["headline"] = str(candidate["headline"])
            if candidate.get("datePublished") and "datePublished" not in result:
                result["datePublished"] = str(candidate["datePublished"])
            author = candidate.get("author")
            if isinstance(author, dict) and author.get("name") and "author" not in result:
                result["author"] = str(author["name"])
            elif isinstance(author, str) and author and "author" not in result:
                result["author"] = author
    return result


def extract_content_id(url: str) -> str | None:
    for pattern in _ID_PATTERNS:
        match = pattern.search(url or "")
        if match:
            return match.group(1)
    return None


def _is_generic_description(text: str | None) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _GENERIC_DESCRIPTION_MARKERS)


def _looks_truncated_preview(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.lower().strip()
    if "see more of" in lowered and "log in" in lowered:
        return True
    if "…" in lowered:
        return True
    # Facebook often strips the ellipsis to plain dots in previews.
    return lowered.endswith("...")


def fields_from_html(page_html: str, final_url: str) -> ExtractionOutcome:
    """Turn raw HTML (from HTTP or Playwright) into an extraction outcome."""
    outcome = ExtractionOutcome()
    metadata = parse_html_metadata(page_html)
    json_ld = parse_json_ld(page_html)

    title = metadata.get("og:title") or metadata.get("title")
    description = (
        metadata.get("og:description")
        or metadata.get("description")
        or json_ld.get("articleBody")
    )
    if _is_generic_description(description):
        description = None

    author = metadata.get("og:article:author") or metadata.get("article:author")
    if not author and json_ld.get("author"):
        author = json_ld["author"]
    # Facebook post pages often use og:title as the author (page name) when
    # og:description carries the post body.
    if not author and title and description and len(title) <= 80 and len(description) > len(title):
        author = title

    upload_date = (
        metadata.get("article:published_time")
        or metadata.get("og:updated_time")
        or json_ld.get("datePublished")
    )
    if upload_date:
        upload_date = str(upload_date).strip()[:10] or None

    if title and _PREVIEW_TITLE_RE.match(title):
        title = None
    title = _clean_title(title)
    author = _clean_title(author) if author else author

    fields: dict[str, Any] = {
        "resolved_url": metadata.get("og:url") or final_url,
        "content_id": extract_content_id(final_url),
        "title": title or None,
        "caption": description or None,
        "author": author or None,
        "page_name": author or None,
        "upload_date": upload_date,
        "thumbnail_url": metadata.get("og:image") or None,
        "media_url": (
            metadata.get("og:video:secure_url")
            or metadata.get("og:video:url")
            or metadata.get("og:video")
            or None
        ),
    }
    outcome.fields = {key: value for key, value in fields.items() if value not in (None, "")}

    if _looks_truncated_preview(description) or _looks_truncated_preview(title):
        outcome.warnings.append(
            "Facebook only served a truncated public preview for this post; "
            "the full text may require manual import"
        )
    return outcome


def _score_outcome(outcome: ExtractionOutcome) -> int:
    """Rank candidate outcomes so the richest public page wins."""
    score = 0
    if outcome.fields.get("caption"):
        score += 3
    if outcome.fields.get("title"):
        score += 1
    if outcome.fields.get("author"):
        score += 1
    if outcome.fields.get("thumbnail_url"):
        score += 1
    if outcome.fields.get("media_url"):
        score += 1
    return score


def extract_post(url: str, settings: Settings) -> ExtractionOutcome:
    """Fetch a public post page and pull out whatever metadata is visible.

    Facebook serves share/ post links with full public Open Graph metadata to
    the standard link-preview crawler user-agent (the mechanism every chat app
    uses to render link previews), while a plain browser user-agent often gets
    HTTP 400.  Both are attempted; nothing here authenticates or bypasses a
    login wall - if Facebook demands a session the item is flagged instead.
    """
    outcome = ExtractionOutcome()
    browser_session = build_session(settings)
    preview_session = build_session(settings, user_agent=LINK_PREVIEW_USER_AGENT)

    final_url, _status_code, resolve_error = resolve_redirects(
        url, settings, browser_session
    )
    if resolve_error:
        outcome.warnings.append(f"redirect resolution failed: {resolve_error}")

    strategies: list[tuple[str, requests.Session, str]] = [
        ("link-preview", preview_session, url),
        ("browser", browser_session, final_url or url),
    ]
    if final_url and final_url != url:
        strategies.append(("link-preview-resolved", preview_session, final_url))

    errors: list[str] = []
    login_wall_seen = False
    best: ExtractionOutcome | None = None
    best_score = -1

    for label, session, target in strategies:
        try:
            response = request_with_retries(session, "GET", target, settings)
        except Exception as exc:  # noqa: BLE001 - network failures must not crash
            errors.append(f"{label}: {type(exc).__name__}: {exc}")
            continue

        page_html = response.text or ""
        if response.status_code >= 400:
            errors.append(
                f"HTTP {response.status_code} while fetching {target} ({label})"
            )
            continue

        if looks_like_login_wall(response.url, page_html):
            login_wall_seen = True
            errors.append(f"{label}: facebook served a login wall")

        parsed = fields_from_html(page_html, response.url or target)
        score = _score_outcome(parsed)
        if score > best_score:
            best = parsed
            best_score = score
        if parsed.fields.get("caption"):
            break  # good enough, no need to try more strategies

    if best is not None:
        for key, value in best.fields.items():
            if value not in (None, ""):
                outcome.fields[key] = value
        outcome.warnings.extend(best.warnings)

    if not outcome.fields.get("resolved_url"):
        outcome.fields["resolved_url"] = final_url or url

    has_caption = bool(outcome.fields.get("caption"))
    if has_caption:
        if login_wall_seen:
            outcome.warnings.append(
                "facebook showed a login wall but public metadata was still available"
            )
    elif login_wall_seen:
        outcome.needs_login = True
        outcome.error = (
            "Facebook served a login wall for this public URL; "
            "manual import is required to capture the content"
        )
    elif errors:
        outcome.error = "; ".join(dict.fromkeys(errors))[:1500]
    else:
        outcome.error = "no public caption or description found on the page"

    return outcome
