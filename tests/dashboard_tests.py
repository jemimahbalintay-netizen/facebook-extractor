"""Dashboard render tests (frontend + headers) — offline, deterministic.

Runs the FastAPI app in-process through Starlette's TestClient against a
scratch database with synthetic fixtures, so it never touches production data
and never opens a network port.

Guards real regressions found during the pre-ship audit:
  * Jinja attribute/key collisions (``stats.items`` rendering a bound method);
  * unescaped or unrendered template output;
  * missing accessibility scaffolding (scopes, landmarks, aria labels);
  * missing security headers / CSP violations from inline styles or scripts.

Usage (from the project root):
    python tests/dashboard_tests.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

# Scratch environment must be set before importing config-dependent modules.
scratch_dir = Path(tempfile.mkdtemp(prefix="fbx_dash_"))
os.environ["DATABASE_PATH"] = str(scratch_dir / "dash.db")
os.environ["DEEPSEEK_API_KEY"] = ""

from config import load_settings  # noqa: E402

settings = load_settings()

from database import (  # noqa: E402
    init_db,
    replace_transcript_segments,
    save_summary,
    upsert_item,
)
from models import (  # noqa: E402
    ExtractedItem,
    SummaryPayload,
    TranscriptSegment,
)

# --- deterministic fixtures -------------------------------------------------
init_db(settings.database_path)

reel = ExtractedItem(
    source_url="https://www.facebook.com/share/r/DASHTEST0001/",
    content_type="reel",
    status="extracted",
    title="Dashboard fixture reel",
    caption="Fixture caption for the reel.",
    transcript_text="Fixture whisper transcript text.",
    transcript_source="whisper",
    transcript_language="en",
    duration_seconds=49,
    view_count=6200,
    like_count=126,
    author="Fixture Author",
)
reel_id = upsert_item(reel, settings.database_path)
replace_transcript_segments(
    reel_id,
    [
        TranscriptSegment(start_seconds=0.0, end_seconds=2.0, text="first segment"),
        TranscriptSegment(start_seconds=2.0, end_seconds=4.0, text="second segment"),
    ],
    settings.database_path,
)
save_summary(
    reel_id,
    "deepseek-ai/deepseek-v4.1-flash",
    SummaryPayload(
        short_title="Fixture summary title",
        filipino_summary="Buod sa Filipino.",
        english_summary="English summary.",
        key_points=["point one", "point two"],
        sentiment="neutral",
    ),
    settings.database_path,
)

post = ExtractedItem(
    source_url="https://www.facebook.com/share/p/DASHTEST0002/",
    content_type="post",
    status="partial",
    caption="Truncated preview text...",
    transcript_text="Truncated preview text...",
    transcript_source="description",
    needs_manual_import=True,
)
upsert_item(post, settings.database_path)

skipped = ExtractedItem(
    source_url="https://www.facebook.com/",
    content_type="homepage",
    status="skipped",
)
upsert_item(skipped, settings.database_path)

# The app must be imported after the scratch env is in place; rebuild its
# module-level settings by importing lazily.
from fastapi.testclient import TestClient  # noqa: E402

from dashboard.app import app  # noqa: E402

client = TestClient(app)

results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    ok = bool(condition)
    results.append((name, ok, detail))
    suffix = f"  [{detail}]" if detail and not ok else ""
    print(f"{'PASS' if ok else 'FAIL'}  {name}{suffix}")


print("=== endpoints ===")
check("health", client.get("/health").json() == {"status": "ok"})
check("items.json", client.get("/items.json").status_code == 200)
check("item 404", client.get("/item/999999").status_code == 404)
check("/docs disabled", client.get("/docs").status_code == 404)
check("/redoc disabled", client.get("/redoc").status_code == 404)
check("/openapi.json kept", client.get("/openapi.json").status_code == 200)

print("\n=== static assets ===")
css = client.get("/static/style.css")
check("style.css served", css.status_code == 200 and "text/css" in css.headers.get("content-type", ""))
check(
    "style.css uses Radix Colors scales (attributed)",
    "--green-11: #3dd68c" in css.text
    and "--red-11: #ff9592" in css.text
    and "radix-ui.com/colors" in css.text,
)
favicon = client.get("/static/favicon.svg")
check("favicon.svg served", favicon.status_code == 200 and "svg" in favicon.headers.get("content-type", ""))

print("\n=== palette contrast (computed from the served stylesheet) ===")
import re as _re  # noqa: E402


def _tokens(css_text: str) -> dict[str, str]:
    return {
        match.group(1): match.group(2).strip()
        for match in _re.finditer(r"--([a-z0-9-]+)\s*:\s*([^;]+);", css_text)
    }


def _resolve(tokens: dict[str, str], value: str) -> str:
    var = _re.fullmatch(r"var\(--([a-z0-9-]+)\)", value.strip())
    return tokens.get(var.group(1), value) if var else value


def _lum(hex_color: str) -> float:
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast(fg: str, bg: str) -> float:
    l1, l2 = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


tokens = _tokens(css.text)

def _ratio(fg_name: str, bg_name: str) -> float:
    return _contrast(_resolve(tokens, tokens[fg_name]), _resolve(tokens, tokens[bg_name]))


TEXT_PAIRS = [
    ("text", "bg"),
    ("text", "panel"),
    ("muted", "panel"),
    ("muted", "bg"),
    ("muted", "panel2"),
    ("accent", "bg"),
    ("accent", "panel"),
    ("ok-text", "ok-bg"),
    ("warn-text", "warn-bg"),
    ("bad-text", "bad-bg"),
    ("neutral-text", "neutral-bg"),
    ("warn-text", "panel"),
    ("bad-text", "panel"),
]
for _fg, _bg in TEXT_PAIRS:
    _r = _ratio(_fg, _bg)
    check(f"contrast { _fg } on { _bg } >= 4.5 (measured {_r:.2f})", _r >= 4.5)
_ring = _ratio("teal-9", "panel")
check(f"focus ring contrast >= 3.0 (measured {_ring:.2f})", _ring >= 3.0)

print("\n=== index page ===")
index = client.get("/")
html = index.text
check("index 200", index.status_code == 200)
check("no unrendered Jinja", "{{" not in html and "{%" not in html)
check("no leaked bound method (stats.items regression)", "<built-in method" not in html)
check("main landmark", "<main>" in html)
check("metric strip values", '<span class="value">3</span> <span class="label">items' in html)
check(
    "strip counts (transcripts/summaries/manual)",
    '<span class="value">2</span> <span class="label">with transcript' in html
    and '<span class="value">1</span> <span class="label">AI summaries' in html
    and '<span class="value">1</span> <span class="label">need manual import' in html,
)
check("attention styling on manual metric", 'class="metric attention"' in html)
check("status badge classes", "s-extracted" in html and "s-partial" in html and "s-skipped" in html)
check("scoped column headers", html.count('scope="col"') >= 10)
check("stylesheet + favicon linked", "/static/style.css" in html and "favicon.svg" in html)
check("no inline <style>", "<style" not in html)
check("no inline style attributes", 'style="' not in html)
check("no unicode glyph icons", "\u26a0" not in html)
check("no clear-filters link when unfiltered", "clear-filters" not in html)

filtered = client.get("/?status=partial")
check("filtered view", filtered.status_code == 200 and "clear-filters" in filtered.text)

print("\n=== item page ===")
item = client.get(f"/item/{reel_id}")
item_html = item.text
check("item 200", item.status_code == 200)
check("no unrendered Jinja", "{{" not in item_html and "{%" not in item_html)
check("no leaked bound method", "<built-in method" not in item_html)
check("main landmark + strip", "<main>" in item_html and "status-strip" in item_html)
check("strip duration value", '<span class="value">49s</span> <span class="label">duration' in item_html)
check(
    "missing values flagged",
    'class="value missing">missing</span> <span class="label">comments' in item_html,
)
check("row-scoped headers", item_html.count('scope="row"') >= 3)
check("summary block rendered", "Fixture summary title" in item_html and "Buod sa Filipino." in item_html)
check("transcript segments block", 'aria-label="Transcript segments"' in item_html and "second segment" in item_html)
check("raw JSON in details element", "<details class=\"panel\">" in item_html)
check("time elements used", "<time datetime=" in item_html)
check("no inline style attributes", 'style="' not in item_html)

print("\n=== search, sorting, pagination, xlsx ===")
search_page = client.get("/?q=whisper")
check("search box present on index", 'type="search"' in html and 'name="q"' in html)
check(
    "search filters rows to matches",
    "of 1" in search_page.text and "s-skipped" not in search_page.text,
)
check("search renders a snippet", "snippet" in search_page.text)
check("search miss shows empty state", "No matches for" in client.get("/?q=zzzz").text)
sorted_page = client.get("/?sort=view_count&order=desc")
check("sorting marks aria-sort", 'aria-sort="descending"' in sorted_page.text)
check("active sort link styled", "sort-link active desc" in sorted_page.text)
check("sortable header links present", "?sort=extracted_at" in sorted_page.text)
paged = client.get("/?per_page=2")
check(
    "pagination shows range and next link",
    "1–2 of 3" in paged.text and ">Next<" in paged.text,
)
check("pagination shows previous link", ">Previous<" in client.get("/?per_page=2&page=2").text)
xlsx_response = client.get("/export/xlsx")
check(
    "xlsx route serves a workbook",
    xlsx_response.status_code == 200 and xlsx_response.content[:2] == b"PK",
    str(xlsx_response.status_code),
)
check("xlsx download link in nav", "/export/xlsx" in html)

print("\n=== security headers ===")
headers = index.headers
check("CSP strict", headers.get("content-security-policy", "").startswith("default-src 'none'"), headers.get("content-security-policy"))
check("nosniff", headers.get("x-content-type-options") == "nosniff")
check("referrer policy", headers.get("referrer-policy") == "no-referrer")
check("html not cached", headers.get("cache-control") == "no-store")
check("static css cacheable", "no-store" not in str(css.headers.get("cache-control", "")))

failed = [name for name, ok, _ in results if not ok]
print(f"\n{'=' * 60}")
print(f"DASHBOARD TESTS: {len(results) - len(failed)}/{len(results)} passed")
if failed:
    print("FAILED:")
    for name in failed:
        print("  -", name)
print(f"scratch dir: {scratch_dir}")
sys.exit(1 if failed else 0)
