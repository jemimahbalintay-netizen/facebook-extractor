# Ship Plan — facebook-extractor v1.0 (local tool)

**Date:** 2026-10-13 · **Status:** feature-complete; audits complete; automated pre-ship
gates green. Remaining items are release mechanics that need your decision (git/GitHub)
and optional extras.

This plan is the deep pre-ship pass requested before declaring the tool "shipped".
The checklist is adapted from `docs/ANTI_SLOP_RESEARCH.md` (primary-source research on
AI-slop/vibe-coding failure modes); the audit evidence lives in `docs/AUDIT.md`
(rounds 1–3, including the frontend/backend pre-ship audit).

## 1. Definition of done

- 27 seed URLs ingested and stored; transcripts for 26; AI summaries for 26.
- All offline test suites pass: 90 unit + 54 audit + 41 dashboard checks.
- Zero `ruff` findings, zero `mypy` errors, zero vulture dead-code hits in app code.
- No known dependency CVEs; `pip check` clean; no hardcoded secrets.
- Verified DB backup + restore; documented rollback.
- Dashboard: WCAG-AA checks pass (badges AAA), strict CSP, localhost-only by default.

## 2. Current state snapshot

| Metric | Value |
| --- | --- |
| Items / summaries / transcript segments | 27 / 26 / 211 |
| Needs manual import (truncated posts) | 7 (awaiting your paste) |
| Offline checks | 199 (90 unit + 54 audit + 55 dashboard) |
| Static analysis | ruff 0 · mypy 0 strict (29 files) · vulture 0 app hits |
| Dependencies | `pip-audit` clean · `pip check` clean · `requirements-lock.txt` (74 pins) |
| DB | `PRAGMA integrity_check` ok · FK check clean · backup verified + restore drill passed |

## 3. Pre-ship gate (status as of today)

| # | Item | How to verify | Status |
| --- | --- | --- | --- |
| 1 | Tests pass | `python tests\unit_tests.py` + `tests\audit_suite.py` + `tests\dashboard_tests.py` all exit 0 (199 checks) | ✅ |
| 2 | Failure paths tested | bad URLs, malformed repair, HTTP 429/5xx/Retry-After, network errors, missing API key, invalid JSON, 404s | ✅ |
| 3 | Lint clean | `python -m ruff check .` → 0; enforced by `.pre-commit-config.yaml` (tag-pinned) | ✅ |
| 4 | Types clean | `python -m mypy .` → 0 errors in 29 files, strict (`disallow_untyped_defs`) | ✅ |
| 5 | Dead code reviewed | `python -m vulture .` → only intentional test lambdas | ✅ |
| 6 | Dependency audit + integrity | `python -m pip_audit` → none; `python -m pip check` → clean | ✅ |
| 7 | No secrets in files | regex scan → none outside `.env`; `.env`/`cookies.txt`/`data/`/`logs/` gitignored | ✅ |
| 8 | No silent failures | no bare excepts; scoped fallbacks logged; ignores documented | ✅ |
| 9 | DB backup + restore drill | `PRAGMA integrity_check` = ok; backup restored to scratch, counts match (27/26/211) | ✅ |
| 10 | Rollback possible | lockfile ✅; git tag ☐ (repo not initialised — your call) | ☐ |
| 11 | README quickstart accurate | every documented command executed this session; fresh-venv replay left as release step | ◐ |
| 12 | Jinja autoescape on | `Jinja2Templates(directory=...)` (no custom env); XSS payload tests pass | ✅ |
| 13 | Dashboard stays local | binds `127.0.0.1`; CLI warns on non-loopback binds | ✅ |
| 14 | /docs exposure decided | `/docs` + `/redoc` disabled; `/openapi.json` kept for tooling (documented) | ✅ |
| 15 | WCAG quick pass | measured: body 11.9–14.5:1, muted 5.7:1, badges AAA (7.1–8.4:1); focus rings; `th scope`; `color-scheme: dark` | ✅ |
| 16 | Encoding-safe on Windows | no `open()`/`read_text()` without `encoding="utf-8"` (grep clean) | ✅ |
| 17 | Cookie/env credential-safe | both gitignored; `cookies.txt` absent; key only in `.env` (never printed/logged) | ✅ |
| 18 | No autoescape bypass | grep for `\|safe` / `autoescape false` → none | ✅ |
| 19 | Full diff reviewed | reviewed live during rounds 1–3 (git not initialised, so no `git diff` yet) | ◐ |
| 20 | Input treated as hostile | bound SQL parameters only; captions/transcripts escaped everywhere; XSS tests | ✅ |

## 4. Remaining manual steps (release mechanics)

1. **Initialise version control** (recommended before any shipping/sync):
   ```powershell
   cd C:\path\to\facebook-extractor
   git init
   git add -A
   git commit -m "facebook-extractor v1.0.0"
   git tag -a v1.0.0 -m "first working release"
   ```
   `.gitignore` already excludes `.env`, `cookies.txt`, `data/`, `logs/`, `.venv/`.
   Nothing in this folder is pushed anywhere by the tool itself.
2. **Optional: fresh-venv replay** (proves the documented install works cleanly):
   ```powershell
   python -m venv .venv2
   .venv2\Scripts\pip install -r requirements-lock.txt
   .venv2\Scripts\python tests\audit_suite.py
   ```
   (1.7 GB with faster-whisper; the lock pins the exact working set.)
3. **Finish the 7 truncated posts** (manual paste), then summarize:
   ```powershell
   python main.py manual-import --url "https://www.facebook.com/share/p/<ID>/" --text-file captions\<ID>.txt
   python main.py summarize
   ```
4. **Optional extras**: `pip install playwright; playwright install chromium` and set
   `ENABLE_PLAYWRIGHT=true`; add `cookies.txt` only for content you are authorized to access.

## 5. Rollback plan

- **Database:** `python scripts\backup_db.py` writes a verified snapshot to
  `data\backups\` using the SQLite backup API (WAL-safe, integrity-checked,
  keeps the newest 10). Restore = copy the chosen backup over
  `data\facebook_content.db` (drill verified: counts identical, integrity ok).
  Exports and JSONL regenerate from the DB.
- **Code:** `requirements-lock.txt` + a git tag reproduce the exact working build.
- **Data loss paths:** a failed re-ingest can never empty a good row (preservation +
  transcript-rank rules); the DB is WAL-mode SQLite with backups before risky work.

## 6. Post-ship maintenance

- `pip install -U yt-dlp` monthly (Facebook changes its pages often — first response to
  extraction regressions).
- Re-run the gate: `ruff`, `mypy`, the three test suites, `pip_audit` — monthly or before
  any dependency bump.
- Log rotation is built in (`logs\extractor.log`, 2 MB × 3).

## 7. Accepted risks (documented, not fixed)

- Dashboard is unauthenticated by design (localhost; warning on remote bind, no TLS).
- Free NVIDIA NIM tier: undocumented limits (~40 RPM community-reported); retries + `--delay`.
- Whisper decodes audio to RAM (fine for short reels; long videos need memory).
- Facebook may serve only truncated public previews for some posts (7 items flagged).
- Summaries can go stale after large content changes: `python main.py summarize --all`.

## 8. Release command block

```powershell
cd C:\path\to\facebook-extractor
.venv\Scripts\activate

python -m compileall -q . ; python -m ruff check . ; python -m mypy .
python tests\unit_tests.py ; python tests\audit_suite.py ; python tests\dashboard_tests.py
python -m pip_audit ; python -m pip check
python main.py status
python main.py serve            # http://127.0.0.1:8765
```
