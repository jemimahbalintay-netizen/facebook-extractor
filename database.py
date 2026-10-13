"""SQLite persistence layer.

Three tables are maintained:

* ``items``               - one row per processed Facebook URL
* ``summaries``           - the DeepSeek AI summary for an item
* ``transcript_segments`` - timestamped caption/transcript segments
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from models import ExtractedItem, SummaryPayload, TranscriptSegment
from utils import compute_content_hash, json_dumps, utc_now_iso

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url TEXT NOT NULL UNIQUE,
    resolved_url TEXT,
    content_type TEXT,
    content_id TEXT,
    status TEXT,
    title TEXT,
    caption TEXT,
    transcript_text TEXT,
    transcript_source TEXT,
    transcript_language TEXT,
    author TEXT,
    page_name TEXT,
    upload_date TEXT,
    duration_seconds INTEGER,
    view_count INTEGER,
    like_count INTEGER,
    comment_count INTEGER,
    share_count INTEGER,
    thumbnail_url TEXT,
    media_url TEXT,
    hashtags TEXT,
    mentions TEXT,
    external_links TEXT,
    language TEXT,
    needs_login INTEGER DEFAULT 0,
    needs_manual_import INTEGER DEFAULT 0,
    malformed INTEGER DEFAULT 0,
    error_message TEXT,
    extracted_at TEXT,
    summarized_at TEXT,
    content_hash TEXT,
    summarized_hash TEXT
);

CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    model TEXT,
    short_title TEXT,
    filipino_summary TEXT,
    english_summary TEXT,
    key_points TEXT,
    topics TEXT,
    hashtags TEXT,
    entities TEXT,
    sentiment TEXT,
    content_warnings TEXT,
    suggested_tags TEXT,
    virality_signals TEXT,
    call_to_action TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS transcript_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    start_seconds REAL,
    end_seconds REAL,
    text TEXT,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_items_type ON items(content_type);
CREATE INDEX IF NOT EXISTS idx_items_extracted_at ON items(extracted_at);
CREATE INDEX IF NOT EXISTS idx_segments_item ON transcript_segments(item_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_summaries_item ON summaries(item_id);

-- Full-text search over title/caption/transcript (external content table:
-- the index lives here, the text lives in items).  Kept in sync by triggers;
-- a rebuild runs at init when the index is empty but items exist (upgrades).
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    title,
    caption,
    transcript_text,
    content='items',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS items_fts_ai AFTER INSERT ON items BEGIN
    INSERT INTO items_fts(rowid, title, caption, transcript_text)
    VALUES (new.id, new.title, new.caption, new.transcript_text);
END;

CREATE TRIGGER IF NOT EXISTS items_fts_ad AFTER DELETE ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, title, caption, transcript_text)
    VALUES ('delete', old.id, old.title, old.caption, old.transcript_text);
END;

CREATE TRIGGER IF NOT EXISTS items_fts_au AFTER UPDATE OF title, caption, transcript_text ON items BEGIN
    INSERT INTO items_fts(items_fts, rowid, title, caption, transcript_text)
    VALUES ('delete', old.id, old.title, old.caption, old.transcript_text);
    INSERT INTO items_fts(rowid, title, caption, transcript_text)
    VALUES (new.id, new.title, new.caption, new.transcript_text);
END;
"""

# Columns stored on the items table, in insert order.
ITEM_DB_COLUMNS = [
    "source_url",
    "resolved_url",
    "content_type",
    "content_id",
    "status",
    "title",
    "caption",
    "transcript_text",
    "transcript_source",
    "transcript_language",
    "author",
    "page_name",
    "upload_date",
    "duration_seconds",
    "view_count",
    "like_count",
    "comment_count",
    "share_count",
    "thumbnail_url",
    "media_url",
    "hashtags",
    "mentions",
    "external_links",
    "language",
    "needs_login",
    "needs_manual_import",
    "malformed",
    "error_message",
    "extracted_at",
]

# Fields that are stored as JSON strings.
JSON_ITEM_FIELDS = {"hashtags", "mentions", "external_links"}
BOOL_ITEM_FIELDS = {"needs_login", "needs_manual_import", "malformed"}

SUMMARY_DB_COLUMNS = [
    "item_id",
    "model",
    "short_title",
    "filipino_summary",
    "english_summary",
    "key_points",
    "topics",
    "hashtags",
    "entities",
    "sentiment",
    "content_warnings",
    "suggested_tags",
    "virality_signals",
    "call_to_action",
    "created_at",
]

SUMMARY_JSON_FIELDS = {
    "key_points",
    "topics",
    "hashtags",
    "entities",
    "content_warnings",
    "suggested_tags",
    "virality_signals",
}


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def default_db_path() -> Path:
    """Database path from the environment (falls back to data/)."""
    from config import load_settings

    return load_settings().database_path


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with sane pragmas and row access by name."""
    path = Path(db_path) if db_path else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def db_session(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """Commit-on-success connection context manager."""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path | str | None = None) -> Path:
    """Create the database and schema, apply migrations and index upkeep."""
    path = Path(db_path) if db_path else default_db_path()
    with db_session(path) as conn:
        conn.executescript(SCHEMA)
        _migrate_columns(conn)
        _ensure_fts_index(conn)
    logger.info("database initialised at %s", path)
    return path


def _migrate_columns(conn: sqlite3.Connection) -> None:
    """Additive, idempotent column migrations for databases from older versions."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(items)")}
    for column in ("content_hash", "summarized_hash"):
        if column not in columns:
            conn.execute(f"ALTER TABLE items ADD COLUMN {column} TEXT")
            logger.info("migration: added items.%s", column)


def _ensure_fts_index(conn: sqlite3.Connection) -> None:
    """Rebuild the FTS index when it is empty but items already exist.

    Covers upgrades from pre-search databases (the virtual table is created
    empty by the schema script) and manual index loss.

    Note: ``SELECT COUNT(*) FROM items_fts`` is useless for external-content
    tables — it reports the *content* row count.  The ``items_fts_docsize``
    shadow table tracks indexed documents and is the reliable signal.

    The rebuild must happen in this same init pass: between creating an empty
    index and rebuilding it, the update triggers would issue FTS5 ``delete``
    commands for values that were never indexed, which corrupts the index.
    """
    items_count = conn.execute("SELECT COUNT(*) AS c FROM items").fetchone()["c"]
    if not items_count:
        return
    indexed = conn.execute("SELECT COUNT(*) AS c FROM items_fts_docsize").fetchone()["c"]
    if not indexed:
        conn.execute("INSERT INTO items_fts(items_fts) VALUES('rebuild')")
        logger.info("search index rebuilt for %d items", int(items_count))


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _item_to_row(item: ExtractedItem) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for column in ITEM_DB_COLUMNS:
        value = getattr(item, column, None)
        if column in JSON_ITEM_FIELDS:
            value = json_dumps(value) if value else None
        elif column in BOOL_ITEM_FIELDS:
            value = 1 if value else 0
        row[column] = value
    return row


def decode_item_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    """Convert a raw DB row into a JSON-friendly dict."""
    data: dict[str, Any] = dict(row)
    for field in JSON_ITEM_FIELDS:
        raw = data.get(field)
        if isinstance(raw, str) and raw:
            try:
                data[field] = json.loads(raw)
            except json.JSONDecodeError:
                data[field] = []
        elif raw is None:
            data[field] = []
    for field in BOOL_ITEM_FIELDS:
        data[field] = bool(data.get(field))
    return data


def _summary_to_row(item_id: int, model: str, payload: SummaryPayload) -> dict[str, Any]:
    mapping = {
        "item_id": item_id,
        "model": model,
        "short_title": payload.short_title,
        "filipino_summary": payload.filipino_summary,
        "english_summary": payload.english_summary,
        "key_points": payload.key_points,
        "topics": payload.detected_topics,
        "hashtags": payload.hashtags,
        "entities": payload.entities,
        "sentiment": payload.sentiment,
        "content_warnings": payload.content_warnings,
        "suggested_tags": payload.suggested_tags,
        "virality_signals": payload.virality_signals,
        "call_to_action": payload.call_to_action,
        "created_at": utc_now_iso(),
    }
    for field in SUMMARY_JSON_FIELDS:
        value = mapping.get(field)
        mapping[field] = json_dumps(value) if value is not None else None
    return mapping


def decode_summary_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = dict(row)
    for field in SUMMARY_JSON_FIELDS:
        raw = data.get(field)
        if isinstance(raw, str) and raw:
            try:
                data[field] = json.loads(raw)
            except json.JSONDecodeError:
                data[field] = []
        elif raw is None:
            data[field] = []
    return data


# ---------------------------------------------------------------------------
# Item CRUD
# ---------------------------------------------------------------------------


def upsert_item(item: ExtractedItem, db_path: Path | str | None = None) -> int:
    """Insert or update the item identified by ``source_url``. Returns its id."""
    row = _item_to_row(item)
    placeholders = ", ".join(f":{column}" for column in ITEM_DB_COLUMNS)
    updates = ", ".join(
        f"{column} = excluded.{column}"
        for column in ITEM_DB_COLUMNS
        if column != "source_url"
    )
    sql = (
        f"INSERT INTO items ({', '.join(ITEM_DB_COLUMNS)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT(source_url) DO UPDATE SET {updates}"
    )
    with db_session(db_path) as conn:
        conn.execute(sql, row)
        cursor = conn.execute(
            "SELECT id FROM items WHERE source_url = ?", (item.source_url,)
        )
        result = cursor.fetchone()
        item_id = int(result["id"])
        # Track the summarisable content so stale summaries can be detected.
        conn.execute(
            "UPDATE items SET content_hash = ? WHERE id = ?",
            (
                compute_content_hash(item.title, item.caption, item.transcript_text),
                item_id,
            ),
        )
        return item_id


def get_item(item_id: int, db_path: Path | str | None = None) -> dict[str, Any] | None:
    with db_session(db_path) as conn:
        cursor = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        row = cursor.fetchone()
    return decode_item_row(row) if row else None


def get_item_by_url(
    source_url: str, db_path: Path | str | None = None
) -> dict[str, Any] | None:
    with db_session(db_path) as conn:
        cursor = conn.execute(
            "SELECT * FROM items WHERE source_url = ?", (source_url,)
        )
        row = cursor.fetchone()
    return decode_item_row(row) if row else None


def update_item_fields(
    db_path: Path | str | None = None,
    item_id: int | None = None,
    source_url: str | None = None,
    **fields: Any,
) -> bool:
    """Patch arbitrary columns of an item. Returns True when a row changed."""
    if item_id is None and source_url is None:
        raise ValueError("update_item_fields needs item_id or source_url")
    if not fields:
        return False

    assignments: list[str] = []
    values: dict[str, Any] = {}
    for column, value in fields.items():
        if column not in ITEM_DB_COLUMNS and column != "summarized_at":
            raise ValueError(f"unknown items column: {column}")
        if column in JSON_ITEM_FIELDS:
            value = json_dumps(value) if value else None
        elif column in BOOL_ITEM_FIELDS:
            value = 1 if value else 0
        assignments.append(f"{column} = :{column}")
        values[column] = value

    where = "id = :_item_id" if item_id is not None else "source_url = :_source_url"
    if item_id is not None:
        values["_item_id"] = item_id
    else:
        values["_source_url"] = source_url

    sql = f"UPDATE items SET {', '.join(assignments)} WHERE {where}"
    with db_session(db_path) as conn:
        cursor = conn.execute(sql, values)
        return cursor.rowcount > 0


def list_items(
    db_path: Path | str | None = None,
    content_type: str | None = None,
    status: str | None = None,
    limit: int | None = None,
    ascending: bool = True,
) -> list[dict[str, Any]]:
    """List items with simple filters, newest last by default."""
    clauses: list[str] = []
    values: list[Any] = []
    if content_type:
        clauses.append("content_type = ?")
        values.append(content_type)
    if status:
        clauses.append("status = ?")
        values.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order = "ASC" if ascending else "DESC"
    sql = f"SELECT * FROM items {where} ORDER BY id {order}"
    if limit:
        sql += " LIMIT ?"
        values.append(int(limit))

    with db_session(db_path) as conn:
        cursor = conn.execute(sql, values)
        rows = cursor.fetchall()
    return [decode_item_row(row) for row in rows]


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


def save_summary(
    item_id: int,
    model: str,
    payload: SummaryPayload,
    db_path: Path | str | None = None,
) -> int:
    """Replace the summary of an item. Returns the summary row id."""
    row = _summary_to_row(item_id, model, payload)
    placeholders = ", ".join(f":{column}" for column in SUMMARY_DB_COLUMNS)
    sql = (
        f"INSERT INTO summaries ({', '.join(SUMMARY_DB_COLUMNS)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT(item_id) DO UPDATE SET "
        + ", ".join(
            f"{column} = excluded.{column}"
            for column in SUMMARY_DB_COLUMNS
            if column != "item_id"
        )
    )
    with db_session(db_path) as conn:
        conn.execute(sql, row)
        # Record which content revision this summary describes.
        conn.execute(
            "UPDATE items SET summarized_hash = content_hash WHERE id = ?",
            (item_id,),
        )
        cursor = conn.execute(
            "SELECT id FROM summaries WHERE item_id = ?", (item_id,)
        )
        result = cursor.fetchone()
        return int(result["id"])


def get_summary(
    item_id: int, db_path: Path | str | None = None
) -> dict[str, Any] | None:
    with db_session(db_path) as conn:
        cursor = conn.execute(
            "SELECT * FROM summaries WHERE item_id = ?", (item_id,)
        )
        row = cursor.fetchone()
    return decode_summary_row(row) if row else None


def summaries_by_item(db_path: Path | str | None = None) -> dict[int, dict[str, Any]]:
    """All summaries keyed by item id (used by exporters and the dashboard)."""
    with db_session(db_path) as conn:
        cursor = conn.execute("SELECT * FROM summaries")
        rows = cursor.fetchall()
    return {int(row["item_id"]): decode_summary_row(row) for row in rows}


def items_with_summaries(
    db_path: Path | str | None = None,
    limit: int | None = None,
    content_type: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Items with their summary merged under the ``summary`` key."""
    items = list_items(
        db_path=db_path,
        content_type=content_type,
        status=status,
        limit=limit,
    )
    summaries = summaries_by_item(db_path)
    for item in items:
        item["summary"] = summaries.get(int(item["id"]))
    return items


# ---------------------------------------------------------------------------
# Search, pagination, backlog helpers
# ---------------------------------------------------------------------------

# Whitelist of sortable columns for the dashboard / CLI (SQL-injection safe).
SORTABLE_COLUMNS = {
    "id": "i.id",
    "extracted_at": "i.extracted_at",
    "content_type": "i.content_type",
    "status": "i.status",
    "author": "COALESCE(i.author, i.page_name)",
    "duration_seconds": "i.duration_seconds",
    "view_count": "i.view_count",
    "like_count": "i.like_count",
    "comment_count": "i.comment_count",
}


def list_items_page(
    db_path: Path | str | None = None,
    content_type: str | None = None,
    status: str | None = None,
    sort: str = "id",
    descending: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """One page of items plus the total count for the same filters."""
    column = SORTABLE_COLUMNS.get(sort, "i.id")
    direction = "DESC" if descending else "ASC"

    clauses: list[str] = []
    values: list[Any] = []
    if content_type:
        clauses.append("i.content_type = ?")
        values.append(content_type)
    if status:
        clauses.append("i.status = ?")
        values.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with db_session(db_path) as conn:
        total = int(
            conn.execute(f"SELECT COUNT(*) AS c FROM items i {where}", values).fetchone()["c"]
        )
        rows = conn.execute(
            f"SELECT i.* FROM items i {where} "
            f"ORDER BY {column} {direction}, i.id DESC LIMIT ? OFFSET ?",
            [*values, max(1, int(limit)), max(0, int(offset))],
        ).fetchall()
    return [decode_item_row(row) for row in rows], total


def summaries_for_ids(
    ids: Iterable[int], db_path: Path | str | None = None
) -> dict[int, dict[str, Any]]:
    """Summaries for a specific set of item ids (used by paginated views)."""
    id_list = [int(item_id) for item_id in ids]
    if not id_list:
        return {}
    placeholders = ", ".join("?" for _ in id_list)
    with db_session(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM summaries WHERE item_id IN ({placeholders})", id_list
        ).fetchall()
    return {int(row["item_id"]): decode_summary_row(row) for row in rows}


def failed_urls(
    db_path: Path | str | None = None,
    statuses: Iterable[str] = ("needs_login", "needs_manual_import", "failed"),
) -> list[str]:
    """Source URLs whose last extraction did not succeed (for --retry-failed)."""
    wanted = [str(status) for status in statuses]
    if not wanted:
        return []
    placeholders = ", ".join("?" for _ in wanted)
    with db_session(db_path) as conn:
        rows = conn.execute(
            f"SELECT source_url FROM items WHERE status IN ({placeholders}) "
            "ORDER BY id",
            wanted,
        ).fetchall()
    return [str(row["source_url"]) for row in rows]


def existing_statuses(db_path: Path | str | None = None) -> dict[str, str]:
    """Map of source_url -> status for --skip-existing filtering."""
    with db_session(db_path) as conn:
        rows = conn.execute("SELECT source_url, status FROM items").fetchall()
    return {str(row["source_url"]): str(row["status"] or "") for row in rows}


def stale_summary_item_ids(db_path: Path | str | None = None) -> list[int]:
    """Items whose summary no longer matches their stored content.

    An item is stale when it has a summary, a recorded content hash, and that
    hash differs from the hash recorded when the summary was written (or the
    summary predates hashing and the content changed since).
    """
    with db_session(db_path) as conn:
        rows = conn.execute(
            "SELECT i.id FROM items i "
            "JOIN summaries s ON s.item_id = i.id "
            "WHERE i.content_hash IS NOT NULL "
            "AND (i.summarized_hash IS NULL OR i.summarized_hash != i.content_hash) "
            "ORDER BY i.id"
        ).fetchall()
    return [int(row["id"]) for row in rows]


def _fts_query(raw: str) -> str:
    """Turn user input into a safe FTS5 MATCH expression.

    Every token is quoted (so operators like OR/NOT/NEAR or stray punctuation
    cannot cause syntax errors); a trailing ``*`` enables prefix search.
    """
    parts: list[str] = []
    for token in re.split(r"\s+", (raw or "").strip()):
        if not token:
            continue
        prefix = token.endswith("*")
        core = token[:-1] if prefix else token
        core = core.replace('"', '""').strip()
        if not core:
            continue
        parts.append(f'"{core}"' + ("*" if prefix else ""))
    return " ".join(parts)


def search_items(
    query: str,
    db_path: Path | str | None = None,
    limit: int = 50,
    status: str | None = None,
    content_type: str | None = None,
) -> list[dict[str, Any]]:
    """Full-text search over title, caption and transcript.

    Returns decoded item rows plus ``caption_snippet``, ``transcript_snippet``
    and ``search_rank`` (lower bm25 = better).  Ranking is by relevance.
    """
    match = _fts_query(query)
    if not match:
        return []

    clauses = ["items_fts MATCH ?"]
    values: list[Any] = [match]
    if status:
        clauses.append("i.status = ?")
        values.append(status)
    if content_type:
        clauses.append("i.content_type = ?")
        values.append(content_type)

    sql = (
        "SELECT i.*, "
        "snippet(items_fts, 1, '[', ']', '…', 12) AS caption_snippet, "
        "snippet(items_fts, 2, '[', ']', '…', 12) AS transcript_snippet, "
        "bm25(items_fts) AS search_rank "
        "FROM items_fts JOIN items i ON i.id = items_fts.rowid "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY search_rank LIMIT ?"
    )
    values.append(max(1, int(limit)))

    with db_session(db_path) as conn:
        try:
            rows = conn.execute(sql, values).fetchall()
        except sqlite3.OperationalError as exc:
            logger.warning("search query failed for %r: %s", query, exc)
            return []
    return [decode_item_row(row) for row in rows]


# ---------------------------------------------------------------------------
# Transcript segments
# ---------------------------------------------------------------------------


def replace_transcript_segments(
    item_id: int,
    segments: Iterable[TranscriptSegment],
    db_path: Path | str | None = None,
) -> int:
    """Replace all transcript segments of an item. Returns rows written."""
    created_at = utc_now_iso()
    rows = [
        (
            item_id,
            segment.start_seconds,
            segment.end_seconds,
            segment.text or "",
            created_at,
        )
        for segment in segments
    ]
    with db_session(db_path) as conn:
        conn.execute(
            "DELETE FROM transcript_segments WHERE item_id = ?", (item_id,)
        )
        if rows:
            conn.executemany(
                "INSERT INTO transcript_segments "
                "(item_id, start_seconds, end_seconds, text, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
    return len(rows)


def get_transcript_segments(
    item_id: int, db_path: Path | str | None = None
) -> list[dict[str, Any]]:
    with db_session(db_path) as conn:
        cursor = conn.execute(
            "SELECT * FROM transcript_segments WHERE item_id = ? "
            "ORDER BY COALESCE(start_seconds, 0), id",
            (item_id,),
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def count_rows(db_path: Path | str | None = None) -> dict[str, int]:
    with db_session(db_path) as conn:
        items = conn.execute("SELECT COUNT(*) AS c FROM items").fetchone()["c"]
        summaries = conn.execute("SELECT COUNT(*) AS c FROM summaries").fetchone()["c"]
        segments = conn.execute(
            "SELECT COUNT(*) AS c FROM transcript_segments"
        ).fetchone()["c"]
    return {"items": int(items), "summaries": int(summaries), "segments": int(segments)}


def counts_by(column: str, db_path: Path | str | None = None) -> dict[str, int]:
    """Group item counts by an allowed column (status or content_type)."""
    allowed = {"status", "content_type"}
    if column not in allowed:
        raise ValueError(f"counts_by only supports {sorted(allowed)}")
    with db_session(db_path) as conn:
        cursor = conn.execute(
            f"SELECT COALESCE({column}, 'unknown') AS key, COUNT(*) AS c "
            f"FROM items GROUP BY {column} ORDER BY c DESC"
        )
        rows = cursor.fetchall()
    return {str(row["key"]): int(row["c"]) for row in rows}


def database_stats(db_path: Path | str | None = None) -> dict[str, Any]:
    """Aggregate statistics used by ``main.py status`` and the dashboard."""
    counts = count_rows(db_path)
    with db_session(db_path) as conn:
        flags = conn.execute(
            "SELECT "
            "SUM(CASE WHEN needs_login = 1 THEN 1 ELSE 0 END) AS needs_login, "
            "SUM(CASE WHEN needs_manual_import = 1 THEN 1 ELSE 0 END) AS needs_manual_import, "
            "SUM(CASE WHEN transcript_text IS NOT NULL AND transcript_text != '' THEN 1 ELSE 0 END) AS with_transcript "
            "FROM items"
        ).fetchone()
    return {
        "items": counts["items"],
        "summaries": counts["summaries"],
        "segments": counts["segments"],
        "by_status": counts_by("status", db_path),
        "by_type": counts_by("content_type", db_path),
        "needs_login": int(flags["needs_login"] or 0),
        "needs_manual_import": int(flags["needs_manual_import"] or 0),
        "with_transcript": int(flags["with_transcript"] or 0),
    }
