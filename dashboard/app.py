"""Local FastAPI dashboard for reviewing extracted items.

Run with ``python main.py serve`` (or ``uvicorn dashboard.app:app``).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from config import Settings, load_settings
from database import (
    SORTABLE_COLUMNS,
    database_stats,
    get_item,
    get_summary,
    get_transcript_segments,
    items_with_summaries,
    list_items_page,
    search_items,
    summaries_for_ids,
)
from export.csv_exporter import export_csv
from export.json_exporter import export_json
from export.markdown_exporter import export_markdown
from export.xlsx_exporter import export_xlsx
from utils import humanize_duration, humanize_number, truncate

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"

# /docs and /redoc are disabled: they load Swagger/ReDoc assets from a CDN,
# which the strict Content-Security-Policy below blocks, and the dashboard is
# the intended interface.  /openapi.json stays available for tooling.
app = FastAPI(
    title="Facebook Extractor Dashboard",
    version="1.1.0",
    docs_url=None,
    redoc_url=None,
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Every page is same-origin, script-free, and styled from /static only; the
# CSP below locks that in.  HTML responses are never cached so the tables
# always reflect the current database.
_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "form-action 'self'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'"
)


@app.middleware("http")
async def security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Content-Security-Policy", _CONTENT_SECURITY_POLICY)
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals.update(
    humanize_duration=humanize_duration,
    humanize_number=humanize_number,
    truncate=truncate,
)


def get_settings() -> Settings:
    return load_settings()


@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    status: str | None = None,
    content_type: str | None = None,
    q: str | None = None,
    sort: str | None = None,
    order: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> HTMLResponse:
    settings = get_settings()
    sort_key = sort if sort in SORTABLE_COLUMNS else "id"
    descending = (order or "desc").lower() != "asc"
    per_page = min(max(1, per_page), 200)
    page = max(1, page)
    offset = (page - 1) * per_page

    query_text = (q or "").strip()
    if query_text:
        # Relevance-ranked search; sort links do not apply to ranked results.
        found = search_items(
            query_text,
            settings.database_path,
            limit=500,
            status=status or None,
            content_type=content_type or None,
        )
        total = len(found)
        items = found[offset : offset + per_page]
    else:
        items, total = list_items_page(
            settings.database_path,
            content_type=content_type or None,
            status=status or None,
            sort=sort_key,
            descending=descending,
            limit=per_page,
            offset=offset,
        )

    summaries = summaries_for_ids(
        [item["id"] for item in items], settings.database_path
    )
    for item in items:
        item["summary"] = summaries.get(int(item["id"]))

    base: dict[str, str] = {}
    if query_text:
        base["q"] = query_text
    if status:
        base["status"] = status
    if content_type:
        base["content_type"] = content_type
    base_params = urlencode(base)

    pages = max(1, (total + per_page - 1) // per_page)
    context: dict[str, Any] = {
        "request": request,
        "items": items,
        "stats": database_stats(settings.database_path),
        "filter_status": status or "",
        "filter_type": content_type or "",
        "q": query_text,
        "sort": sort_key,
        "order": "desc" if descending else "asc",
        "page": page,
        "pages": pages,
        "total": total,
        "base_params": base_params,
        "show_from": (offset + 1) if total else 0,
        "show_to": min(offset + per_page, total),
    }
    return templates.TemplateResponse(
        request=request, name="index.html", context=context
    )


@app.get("/item/{item_id}", response_class=HTMLResponse)
def item_detail(request: Request, item_id: int) -> HTMLResponse:
    settings = get_settings()
    item = get_item(item_id, settings.database_path)
    if item is None:
        raise HTTPException(status_code=404, detail=f"item {item_id} not found")
    summary = get_summary(item_id, settings.database_path)
    segments = get_transcript_segments(item_id, settings.database_path)
    context: dict[str, Any] = {
        "request": request,
        "item": item,
        "summary": summary,
        "segments": segments,
    }
    return templates.TemplateResponse(
        request=request, name="item.html", context=context
    )


@app.get("/items.json")
def items_json(
    status: str | None = None,
    content_type: str | None = None,
    q: str | None = None,
) -> JSONResponse:
    settings = get_settings()
    query_text = (q or "").strip()
    if query_text:
        items = search_items(
            query_text,
            settings.database_path,
            limit=500,
            status=status or None,
            content_type=content_type or None,
        )
    else:
        items = items_with_summaries(
            settings.database_path,
            content_type=content_type or None,
            status=status or None,
        )
        items = list(reversed(items))
    stats = database_stats(settings.database_path)
    return JSONResponse({"stats": stats, "count": len(items), "items": items})


@app.get("/export/csv")
def export_csv_route() -> FileResponse:
    settings = get_settings()
    path = export_csv(settings)
    return FileResponse(
        path,
        media_type="text/csv",
        filename="export_items.csv",
    )


@app.get("/export/markdown")
def export_markdown_route() -> FileResponse:
    settings = get_settings()
    path = export_markdown(settings)
    return FileResponse(
        path,
        media_type="text/markdown",
        filename="report.md",
    )


@app.get("/export/json")
def export_json_route() -> FileResponse:
    settings = get_settings()
    path = export_json(settings)
    return FileResponse(
        path,
        media_type="application/json",
        filename="export_items.json",
    )


@app.get("/export/xlsx")
def export_xlsx_route() -> FileResponse:
    settings = get_settings()
    path = export_xlsx(settings)
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="export_items.xlsx",
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Start the dashboard with uvicorn (blocking)."""
    import uvicorn

    logger.info("starting dashboard at http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info", server_header=False)
