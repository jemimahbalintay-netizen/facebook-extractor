# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [1.1.0] — 2026-10-13

### Added

- **Full-text search** — SQLite FTS5 index over titles, captions and transcripts
  (external-content table kept in sync by triggers, `unicode61` tokenizer with
  diacritic folding):
  - `python main.py search "term" [--status S] [--type T] [--json]` with
    relevance (bm25) ranking and highlighted snippets;
  - dashboard search box and `?q=` support on `/` and `/items.json`;
  - safe query handling — user input is always quoted (FTS operators and stray
    punctuation cannot break the query).
- **Dashboard: sorting and pagination** — sortable column headers with
  `aria-sort` and a drawn (non-glyph) direction indicator, page-size support,
  range counter ("1–50 of N") and previous/next links; still zero-JS.
- **XLSX export** (`export --format xlsx`, `/export/xlsx`) — two sheets
  (Items + Summaries), frozen headers, sized columns, formula-injection guard.
- **Stale-summary detection** — `content_hash` per item plus `summarized_hash`
  written with each summary; `python main.py summarize --stale` re-summarizes
  only items whose content changed.
- **Ingestion backlog flags** — `ingest --retry-failed [--include …]`
  re-processes `needs_login` / `needs_manual_import` / `failed` URLs, and
  `ingest --skip-existing` makes scheduled runs process only new and failed URLs.
- **CI**: Python 3.14 added to the Linux matrix and a dedicated Windows job.

### Fixed

- **Search index upgrades** — pre-search databases now rebuild the FTS index
  automatically on first use. The rebuild is detected via the
  `items_fts_docsize` shadow table (a plain `COUNT(*)` on an external-content
  FTS table reports content rows, not indexed rows) and runs inside the same
  init pass — closing the window where update triggers could issue FTS5
  `delete` commands for never-indexed values and corrupt the index.

### Changed

- Test suite: 199 → **242** offline checks (unit 93, audit 83, dashboard 66).
- `openpyxl` added as a core dependency.

[1.1.0]: https://github.com/jemimahbalintay-netizen/facebook-extractor/releases/tag/v1.1.0

## [1.0.0] — 2026-10-13

First public release.

### Added

- **Extraction pipeline** — URL classifier (`post` / `reel` / `video` /
  `homepage` / `malformed` / `unknown`), malformed share-path repair with
  dual-candidate attempts, polite rate limiting (2 s default) and retries with
  exponential backoff (429/5xx/timeouts, `Retry-After` aware).
- **Video & reel metadata** via yt-dlp — titles, authors, durations,
  view/like/comment/share counts, upload dates, thumbnails, embedded
  subtitles (VTT/SRT/JSON3/TTML parsers).
- **Post metadata** via the public link-preview path (crawler user-agent, no
  login-wall bypass) with truncation detection.
- **Local transcription** — faster-whisper with ffmpeg decoding, hallucination
  guards (`temperature=0.0`, `condition_on_previous_text=False`, minimum-length
  discard gate), Tagalog (`tl`) language support.
- **Bilingual AI summaries** — DeepSeek V4.1 Flash / OpenAI-compatible
  endpoints, including NVIDIA NIM; reasoning-model handling (empty-content
  recovery, budget doubling), map-reduce for long transcripts, 12 structured
  fields (EN/Filipino summary, key points, topics, entities, sentiment,
  warnings, virality signals, CTA, ...).
- **Storage** — SQLite (WAL) with three tables, append-only
  `data/extracted.jsonl`, WAL-safe verified backups with retention
  (`scripts/backup_db.py`), JSONL compaction tool.
- **Exports** — CSV (formula-injection guarded), Markdown report grouped by
  content type, full JSON dump.
- **Dashboard** — FastAPI + Jinja2, script-free with a strict CSP, filterable
  item table, per-item detail (metadata, caption, transcript segments, AI
  summary, raw JSON), WCAG AA/AAA-checked dark theme built on Radix Colors.
- **Manual import** — paste captions/transcripts or structured JSON for content
  Facebook will not serve publicly; import precedence rules (manual text is
  never downgraded by a weaker refresh).
- **Data-safety semantics** — failed refreshes keep previous data, transcript
  ranks (`subtitles > whisper > manual > description`) prevent downgrades.
- **Quality** — 199 offline checks (unit/audit/dashboard), ruff + strict mypy
  at zero findings, pre-commit hooks with tag-pinned revisions, pip-audit
  clean, exact-pin lockfile, GitHub Actions CI.
- **Documentation** — ship plan with a 20-item pre-ship gate, three audit
  rounds, primary-source research notes, troubleshooting guide, and a curated
  non-slop UI/backend resource guide.

[1.0.0]: https://github.com/jemimahbalintay-netizen/facebook-extractor/releases/tag/v1.0.0
