"""Optional Playwright-based extraction for rendered public pages.

Disabled unless ``ENABLE_PLAYWRIGHT=true`` and the ``playwright`` package
(plus its Chromium browser) is installed.  All failures degrade to warnings so
the pipeline can continue with HTTP/yt-dlp results or manual import.
"""

from __future__ import annotations

import importlib.util
import logging

from config import Settings
from extractor.facebook_post_extractor import fields_from_html
from extractor.net import looks_like_login_wall
from models import ExtractionOutcome

logger = logging.getLogger(__name__)


def playwright_installed() -> bool:
    return importlib.util.find_spec("playwright") is not None


def extract_with_browser(url: str, settings: Settings) -> ExtractionOutcome:
    """Render ``url`` with headless Chromium and parse the resulting HTML."""
    outcome = ExtractionOutcome()

    if not settings.enable_playwright:
        outcome.warnings.append("playwright disabled (ENABLE_PLAYWRIGHT=false)")
        return outcome

    if not playwright_installed():
        outcome.warnings.append(
            "playwright is not installed; run `pip install playwright` and "
            "`playwright install chromium` to enable browser extraction"
        )
        return outcome

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depends on environment
        outcome.warnings.append(f"playwright import failed: {exc}")
        return outcome

    page_html = ""
    final_url = url
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=settings.playwright_headless)
            try:
                context = browser.new_context(
                    user_agent=settings.user_agent, locale="en-US"
                )
                page = context.new_page()
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=settings.request_timeout * 1000,
                )
                page.wait_for_timeout(3000)
                page_html = page.content()
                final_url = page.url
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 - browser failures are non-fatal
        outcome.error = f"playwright extraction failed: {type(exc).__name__}: {exc}"
        logger.warning("playwright failed for %s: %s", url, exc)
        return outcome

    html_outcome = fields_from_html(page_html or "", final_url or url)
    outcome.fields = html_outcome.fields
    outcome.warnings.extend(html_outcome.warnings)
    outcome.segments = html_outcome.segments
    outcome.transcript_text = html_outcome.transcript_text
    outcome.transcript_source = html_outcome.transcript_source

    if looks_like_login_wall(final_url, page_html) and not outcome.fields.get("caption"):
        outcome.needs_login = True
        outcome.error = (
            "playwright reached a login wall; this content is not publicly "
            "accessible without authentication"
        )
    return outcome
