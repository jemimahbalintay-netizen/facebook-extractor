"""Facebook URL classification and repair.

Labels an input URL as ``post``, ``reel``, ``video``, ``homepage``,
``malformed`` or ``unknown`` and produces candidate URLs to attempt, in order.
"""

from __future__ import annotations

import re
from urllib.parse import ParseResult, urlparse, urlunparse

from models import Classification, ContentType

# /share/p/<id>, /share/r/<id>, /share/v/<id>
SHARE_RE = re.compile(r"/share/([prv])/([A-Za-z0-9_.\-]+)", re.IGNORECASE)

FACEBOOK_HOST_SUFFIXES = ("facebook.com", "fb.com", "fb.watch", "fb.me")

_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")


def normalize_url(raw: str) -> str:
    """Add ``https://`` when the user pasted a scheme-less URL."""
    url = (raw or "").strip()
    if not url:
        return ""
    if not _SCHEME_RE.match(url):
        url = "https://" + url.lstrip("/")
    return url


def _host_is_facebook(host: str) -> bool:
    host = (host or "").lower()
    if not host:
        return False
    return any(
        host == suffix or host.endswith("." + suffix)
        for suffix in FACEBOOK_HOST_SUFFIXES
    )


def _type_from_share_code(code: str) -> ContentType:
    code = code.lower()
    if code == "p":
        return ContentType.POST
    if code == "r":
        return ContentType.REEL
    if code == "v":
        return ContentType.VIDEO
    return ContentType.UNKNOWN


def _repaired_share_url(parsed: ParseResult, code: str, identifier: str) -> str:
    """Build a URL containing only the first share segment."""
    path = f"/share/{code.lower()}/{identifier}/"
    return urlunparse(parsed._replace(path=path, params="", query="", fragment=""))


def classify(raw_url: str) -> Classification:
    """Classify ``raw_url`` and compute extraction candidates."""
    original = (raw_url or "").strip()
    notes: list[str] = []

    if not original:
        return Classification(
            original_url="",
            content_type=ContentType.MALFORMED,
            underlying_type=ContentType.MALFORMED,
            is_malformed=True,
            candidates=[],
            notes=["empty url"],
        )

    url = normalize_url(original)
    if url != original:
        notes.append(f"normalized url: {url}")

    try:
        parsed = urlparse(url)
    except ValueError as exc:
        return Classification(
            original_url=original,
            content_type=ContentType.MALFORMED,
            underlying_type=ContentType.MALFORMED,
            is_malformed=True,
            candidates=[url],
            notes=[f"unparsable url: {exc}"],
        )

    host = parsed.hostname or ""
    path = parsed.path or ""
    path_lower = path.lower()

    if not host:
        return Classification(
            original_url=original,
            content_type=ContentType.MALFORMED,
            underlying_type=ContentType.MALFORMED,
            is_malformed=True,
            candidates=[url],
            notes=["missing host"],
        )

    if not _host_is_facebook(host):
        return Classification(
            original_url=original,
            content_type=ContentType.UNKNOWN,
            underlying_type=ContentType.UNKNOWN,
            notes=[f"non-facebook host: {host}"],
            candidates=[url],
        )

    share_matches = SHARE_RE.findall(path)
    is_malformed = len(share_matches) > 1
    repaired: str | None = None
    effective = ContentType.UNKNOWN

    if share_matches:
        first_code, first_id = share_matches[0]
        effective = _type_from_share_code(first_code)
        if is_malformed:
            repaired = _repaired_share_url(parsed, first_code, first_id)
            notes.append(
                "duplicated share path segments detected; "
                f"repaired candidate: {repaired}"
            )
    elif "/reels/" in path_lower or path_lower.startswith("/reel"):
        effective = ContentType.REEL
    elif (
        "/videos/" in path_lower
        or path_lower.startswith("/watch")
        or "video.php" in path_lower
    ):
        effective = ContentType.VIDEO
    elif (
        "/posts/" in path_lower
        or "permalink.php" in path_lower
        or "story.php" in path_lower
        or "/photo" in path_lower
        or "story_fbid=" in (parsed.query or "").lower()
    ):
        effective = ContentType.POST
    elif path_lower in ("", "/"):
        effective = ContentType.HOMEPAGE
    elif path_lower.startswith("/login") or path_lower.startswith("/checkpoint"):
        notes.append("login page url - nothing public to extract")

    content_type = ContentType.MALFORMED if is_malformed else effective

    if content_type == ContentType.HOMEPAGE:
        candidates = [url]
        notes.append("facebook homepage - nothing to extract")
    elif is_malformed and repaired:
        candidates = [repaired, url]
    else:
        candidates = [url]

    return Classification(
        original_url=original,
        content_type=content_type,
        underlying_type=effective,
        is_malformed=is_malformed,
        candidates=candidates,
        notes=notes,
    )


def is_video_like(content_type: ContentType | str) -> bool:
    """True when the type normally maps to a video resource."""
    value = content_type.value if isinstance(content_type, ContentType) else str(content_type)
    return value in (ContentType.REEL.value, ContentType.VIDEO.value)


def looks_like_video_url(url: str) -> bool:
    """Heuristic check for URLs that yt-dlp can usually handle."""
    lowered = (url or "").lower()
    return any(
        marker in lowered
        for marker in (
            "/reel/",
            "/reels/",
            "/videos/",
            "/watch",
            "video.php",
            "/share/r/",
            "/share/v/",
            "fb.watch/",
        )
    )
