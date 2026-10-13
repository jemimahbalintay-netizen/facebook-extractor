"""HTTP helpers: sessions, retries with exponential backoff, redirect resolution."""

from __future__ import annotations

import contextlib
import logging
import time
from typing import Any
from urllib.parse import urlparse

import requests

from config import (
    BROWSER_USER_AGENT,
    Settings,
)

logger = logging.getLogger(__name__)

# Markers that indicate Facebook served a login wall instead of public content.
LOGIN_WALL_MARKERS = (
    'id="login_form"',
    "id='login_form'",
    "you must log in",
    "log in to continue",
    "login to continue",
    "log in or sign up",
    "log into facebook",
    "/login/?next=",
    "checkpoint",
)


def default_headers(user_agent: str | None = None) -> dict[str, str]:
    return {
        "User-Agent": user_agent or BROWSER_USER_AGENT,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9,fil;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


def build_session(settings: Settings, user_agent: str | None = None) -> requests.Session:
    session = requests.Session()
    session.headers.update(default_headers(user_agent))
    return session


def _retry_delay(
    settings: Settings, attempt: int, response: requests.Response | None = None
) -> float:
    """Backoff delay, honouring a numeric Retry-After header when present."""
    delay = settings.retry_backoff * (2 ** attempt)
    if response is not None:
        retry_after = None
        try:
            retry_after = response.headers.get("Retry-After")
        except AttributeError:
            retry_after = None
        if retry_after:
            with contextlib.suppress(TypeError, ValueError):
                delay = max(delay, min(float(retry_after), 60.0))
    return delay


# HTTP statuses worth retrying (429 = too many requests).
RETRYABLE_STATUSES = {429}


def request_with_retries(
    session: requests.Session,
    method: str,
    url: str,
    settings: Settings,
    **kwargs: Any,
) -> requests.Response:
    """HTTP request with up to ``settings.max_retries`` attempts and
    exponential backoff for transient failures (timeouts, connection errors,
    429 rate limits and 5xx responses)."""
    attempts = max(1, int(settings.max_retries))
    kwargs.setdefault("timeout", settings.request_timeout)
    last_error: Exception | None = None

    for attempt in range(attempts):
        try:
            response = session.request(method, url, **kwargs)
            transient = (
                response.status_code in RETRYABLE_STATUSES
                or response.status_code >= 500
            )
            if transient:
                if attempt < attempts - 1:
                    delay = _retry_delay(settings, attempt, response)
                    logger.warning(
                        "transient HTTP %s for %s - retrying in %.1fs",
                        response.status_code,
                        url,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                # Retries exhausted: hand the last response to the caller so it
                # can record the exact status code.
                return response
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt < attempts - 1:
                delay = _retry_delay(settings, attempt)
                logger.warning(
                    "request error for %s (%s) - retrying in %.1fs",
                    url,
                    exc,
                    delay,
                )
                time.sleep(delay)

    if last_error is not None:
        raise last_error
    raise requests.RequestException(f"request failed after {attempts} attempts: {url}")


def resolve_redirects(
    url: str,
    settings: Settings,
    session: requests.Session | None = None,
) -> tuple[str, int | None, str | None]:
    """Follow share-link redirects without downloading the body.

    Returns ``(final_url, status_code, error)``.  On failure the original URL
    is returned with an error message so callers can continue.
    """
    own_session = session is None
    session = session or build_session(settings)
    try:
        response = request_with_retries(
            session, "GET", url, settings, stream=True, allow_redirects=True
        )
        final_url = response.url or url
        status_code = response.status_code
        response.close()
        if final_url != url:
            logger.info("resolved %s -> %s", url, final_url)
        return final_url, status_code, None
    except Exception as exc:  # noqa: BLE001 - callers handle any failure
        logger.warning("could not resolve redirects for %s: %s", url, exc)
        return url, None, f"{type(exc).__name__}: {exc}"
    finally:
        if own_session:
            session.close()


def looks_like_login_wall(final_url: str, body: str) -> bool:
    """Detect Facebook login/checkpoint walls from URL or page body."""
    lowered_url = (final_url or "").lower()
    if "/login" in lowered_url or "checkpoint" in lowered_url:
        return True
    lowered_body = (body or "").lower()
    return any(marker in lowered_body for marker in LOGIN_WALL_MARKERS)


def host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
