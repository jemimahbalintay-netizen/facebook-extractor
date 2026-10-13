# Roadmap

Direction for facebook-extractor after v1.1.0. Priorities reflect "local-first,
public-only, no surprises": every new capability must keep the archive private,
the dashboard script-free, and the extraction stance unchanged (no login-wall
bypass, no scraping of private content).

## Shipped

- **v1.0.0** — extraction pipeline (classifier, yt-dlp, link-preview posts,
  local Whisper, manual import), bilingual AI summaries, SQLite + JSONL,
  CSV/Markdown/JSON exports, zero-JS dashboard, 199 offline checks.
- **v1.1.0** — full-text search (FTS5) in CLI and dashboard, sortable columns +
  pagination, XLSX export, stale-summary detection (`summarize --stale`),
  ingestion backlog flags (`--retry-failed`, `--skip-existing`), CI on
  Python 3.14 + Windows, 242 offline checks.

## Next (v1.2)

| Item | Why | Notes |
| --- | --- | --- |
| Whisper model bake-off → new default | `small` is the accuracy weak spot; community guidance favours `large-v3-turbo` on CPU | Measured table committed to docs; `--whisper-model` per-run override; expected ~1.6 GB model download |
| Recurring runs | `scripts/watch_seed.py` + a `runs` table + Task Scheduler snippet | Uses `ingest --skip-existing` and `--retry-failed` under the hood |
| Weekly digest | `data/digests/YYYY-WW.md`: new items, top by engagement, topic deltas, leftover manual imports | Optional SMTP email (off by default) |
| Restore & maintenance UX | `restore --from <backup>`, `vacuum` | Pairs with the existing verified backups |
| PEP 751 lockfile | `pylock.toml` via uv alongside `requirements-lock.txt` | Modern standard for exact releases |

## Later (v2.0)

| Item | Why | Notes |
| --- | --- | --- |
| **Archive MCP server** | Let Claude / OpenCode / Cursor query the local archive (search, items, transcripts, stats) | Official MCP Python SDK v2; stdio transport by default; read-only tools; ingest tool gated behind an explicit flag |
| **"Ask my archive" (RAG)** | Semantic search + cited answers over everything stored | Local ONNX embeddings (no torch); deepseek synthesises with `[item:ID]` citations; zero-JS answer page |
| Trends view | Items/week, top authors, topic frequency | Pure SQL aggregates over existing tables |

## Explicit non-goals

- No CAPTCHA solving, login-wall bypass, or private-content access — ever.
- No cloud sync, accounts, or telemetry; the archive stays on your machine.
- No JavaScript in the dashboard (the strict CSP is a feature).
- Multi-platform input (YouTube/Instagram/TikTok via yt-dlp) is **not planned
  yet** — it would change the tool's scope and documentation; revisit on
  request.

## Quality bar for everything above

Right-sized tests in the matching suite, CHANGELOG + docs updates, ruff/mypy at
zero findings, CI green on Linux + Windows, migrations tested against a copy of
a real v1.x database.
