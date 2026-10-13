# Deep Audit Report — facebook-extractor

**Date:** 2026-10-12
**Scope:** the entire application (30 Python files, ~4,900 LOC, plus HTML templates and configs)
**Method:** static analysis (ruff 0.17.0, `compileall`), a 54-case functional/security suite
(`tests/audit_suite.py`), a live stored-XSS test against the dashboard, and live end-to-end
runs (27 real URLs, whisper transcription, NVIDIA NIM summarisation).
**Threat model:** single-user local application. Untrusted input is **Facebook page content**
(captions, titles, OG/meta fields, subtitle files) and operator CLI arguments. The dashboard is
unauthenticated and intended for localhost.

---

## 1. Results at a glance

| Check | Result |
| --- | --- |
| `ruff check` (E4/E7/E9/F/B/S/BLE/SIM/UP/I) | **0 findings** (171 fixed during this audit) |
| `python -m compileall` | clean |
| `tests/audit_suite.py` (functional + security + integrity) | **54/54 passed** |
| Dashboard stored-XSS test (script/svg/img/iframe payloads) | **7/7 passed** (all escaped) |
| SQL-injection negative tests | passed (whitelists reject hostile identifiers) |
| CSV formula-injection guard | passed |
| Live end-to-end extraction (27 URLs) | 19 extracted · 7 partial (truncated previews) · 1 skipped |
| Live whisper transcription | 10 videos transcribed; hallucinations guarded |
| Live DeepSeek V4.1 Flash (NVIDIA NIM) | 26/26 summaries stored |

---

## 2. Findings fixed during this audit

### F-01 — HTTP 429 was not retried (Medium)

`extractor/net.py` retried 5xx errors and connection failures but returned a bare `429`
(rate limit) to the caller immediately. Facebook and NVIDIA NIM both rate-limit.

**Fix:** 429 is now treated as transient, retried with exponential backoff, and a numeric
`Retry-After` header (capped at 60 s) overrides the backoff delay. Negative test: an
always-429 endpoint returns the final response after `MAX_RETRIES` attempts so the caller can
record the exact status code (covered by audit tests §2).

### F-02 — CSV formula injection (Medium)

Caption/title fields are attacker-influenced (they come from Facebook). A cell beginning with
`=`, `+`, `-`, `@`, tab or CR is executed as a formula by Excel/Google Sheets when the export
is opened (OWASP *CSV Injection*).

**Fix:** `export/csv_exporter.py` prefixes such string cells with an apostrophe
(`=HYPERLINK(...)` → `'=HYPERLINK(...)`). Numeric columns (e.g. negative durations) are
untouched, verified by test (§6).

### F-03 — Export artefacts ignored `DATABASE_PATH` (Medium)

`jsonl_path`, `csv_path`, `markdown_path` and `json_export_path` were always derived from the
default `data/` directory. Running with a custom `DATABASE_PATH` (e.g. a scratch copy) still
wrote exports into the live `data/` folder — this was caught live during the audit when a
scratch dashboard's `/export/csv` overwrote the production CSV with test data.

**Fix:** `config.load_settings()` now derives every artefact path from the database's parent
directory, so a custom `DATABASE_PATH` fully isolates a run. Production exports were
regenerated and verified clean (0 test rows).

### F-04 — Dashboard remote bind without warning (Low)

`python main.py serve --host 0.0.0.0` exposes all extracted content and export endpoints
without authentication.

**Fix:** the CLI now prints an explicit warning when binding to a non-loopback address and
recommends `127.0.0.1`.

### F-05 — `summarize --url` exact-match fragility (Low)

Matching was byte-exact, so a pasted URL differing only by a trailing slash matched nothing.

**Fix:** URL comparison is normalized (trim + strip trailing `/` + lowercase) in
`ai/summarizer.py`.

### F-06 — Code hygiene: 171 lint findings (Low)

7 unused imports, a `raise ... from` chain (B904), deprecated `typing.Optional` annotations
(now `X | None`), `StrEnum` modernization, collapsible-ifs, redundant noqa directives, etc.

**Fix:** auto-fixed with review, plus a documented `ruff.toml`. The four deliberate ignore
rules (S608 SQL f-strings, S603 subprocess, S110/BLE001 best-effort fallbacks) each carry a
justification comment. **`ruff check` now reports zero findings.**

### F-07 — Previously fixed in this session (re-verified by the suite)

| Bug | Impact | Fix |
| --- | --- | --- |
| Junk `<title>Error</title>` counted as content | items wrongly "extracted" | placeholder-title filter |
| Whisper hallucination accepted (`今だめか`, 4 chars) | junk transcript replaced real caption | min-length guard + `condition_on_previous_text=False` |
| 1-character subtitle track accepted | junk transcript | min-length guard (20 chars) |
| faster-whisper ↔ PyAV 19 incompatibility (`metadata_errors`) | transcription crashed | ffmpeg decode → 16 kHz float32 array; PyAV only as fallback |
| Windows cp1252 console crash on emoji in titles | CLI crashed after ingestion | UTF-8 stdout/stderr with `errors="replace"` |
| Manual import could not replace truncated captions | users could not fix partial items | longer text wins; subtitles/whisper protected |
| Re-ingest could wipe good data on transient failure | data loss | preservation path (`kept` flag) + error note |
| Re-ingest without `--transcribe` downgraded whisper→caption | transcript quality loss | rank rules `subtitles > whisper > manual > description` (`prev-kept` flag) |

---

## 3. Verified-safe (with evidence)

| Area | Verdict | Evidence |
| --- | --- | --- |
| **SQL injection** | Not exploitable | every value is a bound parameter (`?`/`:name`); identifiers come from constant lists (`ITEM_DB_COLUMNS`) or whitelists (`counts_by` allows only `status`/`content_type`; `update_item_fields` raises `ValueError` for unknown columns). Negative tests in §8 of the suite. |
| **Stored XSS (dashboard)** | Not exploitable | Starlette's `Jinja2Templates` enables autoescape; live test inserted items containing `<script>alert`, `<svg onload>`, `"><img src=x onerror>`, `<iframe src=javascript:>` and confirmed every payload renders escaped (`&lt;script&gt;`), including the index page and the `tojson` raw-JSON block. |
| **Command injection** | Not present | the only `subprocess` call (`ffmpeg` decode) uses an argument list, no `shell=True`; the file path is a locally generated temp file. |
| **Path traversal** | Not applicable to remote input | file paths come only from operator CLI arguments (`--text-file`, `--json-file`, export paths), never from fetched content. |
| **Secrets** | Handled | API key lives in `.env` (gitignored) and process env; never logged, never printed (the setup script copies it without echoing); `data/`, `logs/`, `cookies.txt` are gitignored. |
| **SSRF** | By design | the app fetches only the operator-provided seed URLs (and redirect targets of those); stored `thumbnail_url`/`media_url` are rendered as links, never fetched server-side. |
| **Deserialization** | Safe | only `json.loads` on text; no `pickle`/`yaml.load`. |
| **Data integrity** | Verified | invariants: no orphan summaries/segments, no real-transcript source with empty text, `extracted` never needs manual import, `manual` always has ≥1 segment, no segments for transcript-less items (§7). |

---

## 4. Accepted risks & recommendations

1. **Dashboard has no authentication** (by design, localhost). If you need remote access, put
   it behind a reverse proxy with auth/TLS — the CLI now warns when you bind beyond loopback.
2. **Summaries can go stale** when item content changes after summarisation. Run
   `python main.py summarize --all` after large re-ingests.
3. **Transcription memory**: audio is decoded fully into RAM (16 kHz float32 ≈ 230 MB/hour).
   Fine for reels/short videos; long-form videos will use more memory.
4. **Free NIM tier**: rate limits and occasional empty `reasoning_content`-only replies are
   handled by retries + budget doubling, but a busy tier may still make batch runs slow.
5. **yt-dlp is the most volatile dependency** (Facebook changes its pages). `pip install -U
   yt-dlp` is the first thing to try when video extraction regresses.
6. **Legal**: public-content-only extraction with ToS/authorised-use warnings in the README;
   see `docs/RESEARCH.md` for the researched legal context.

---

### F-08 — Research-driven hardening (external fact-finding, see `docs/RESEARCH.md`)

| Change | Research basis |
| --- | --- |
| `LOGIN_ERROR_MARKERS` extended with `registered users`, `cookies-from-browser`, `cannot parse data`, `unable to download webpage`, `http error 404` | Gated `/share/p/` posts redirect to `/posts/pfbid…` and fail with `Cannot parse data` / `HTTP Error 404`; yt-dlp's canonical login hint says "only available for registered users. Use --cookies-from-browser or --cookies …" (yt-dlp source + issue tracker). |
| Client recovers from endpoints that reject a too-large `max_tokens` (halves the budget instead of failing) | The documented sibling NIM endpoint caps `max_tokens` at 16,384; the hosted cap for v4.1-flash is undocumented. |
| Whisper now runs with `temperature=0.0` | faster-whisper's default 0.0→1.0 sampling fallback is a known hallucination vector on music/near-silent audio; pinning 0.0 complements the ≥20-char discard gate (faster-whisper/whisper source). |
| README notes: cookies are the only FB auth route since yt-dlp removed password login (Dec 2025); Tagalog uses `tl` (no `fil`); ~40 RPM unofficial NIM limit | yt-dlp PR #15434; whisper tokenizer language list; NVIDIA developer-forum threads (all cited in `docs/RESEARCH.md`). |

Two research findings **confirm** existing behaviour rather than change it: the link-preview crawler
strategy (crawler UA → HTTP 200 + OG tags, Chrome UA → HTTP 400, `og:description` truncated to
exactly 200 chars) and the client's tolerant JSON handling (NIM's hosted schema for the sibling
model excludes `response_format`).

---

## 5. Audit round 2 — static typing, dependencies, coverage (2026-10-13)

Deeper tooling pass: `mypy` 2.4.0 (with `check_untyped_defs`), `pip-audit` 2.10.1,
`coverage` 7.16.2, extended `ruff` complexity analysis.

| Check | Before | After |
| --- | --- | --- |
| `mypy` | 34 errors | **0 errors in 29 source files** (`mypy.ini` added) |
| `pip-audit` (known CVEs) | — | **none found** (exit 0) |
| Test coverage (offline suites) | 57% | **69%** (144 checks: 90 unit + 54 audit) |

**Type errors fixed (3 real, rest were intentional test fakes):**

1. `pipeline.py` — mypy could not narrow `existing` from the boolean
   `existing_has_content`; the log/restore branches now check `existing is not None`
   directly (type-safe without changing behaviour).
2. `transcript_extractor.py` — `configured_language` needed an explicit `str | None`
   annotation before the `None` assignment.
3. `ytdlp_extractor.py` — the subtitle URL from yt-dlp is now guarded for `None`
   before the HTTP fetch; `markdown_exporter.py` status lookup coerces the key to `str`.

**New coverage asset — `tests/unit_tests.py` (90 checks, offline):**
exercises every format parser (VTT/SRT/JSON3/TTML, tag/entity handling, track and
format selection), the count parser (`49K` → 49000, `1.2M`, `2B`), login-error
classification, yt-dlp info mapping, HTML/OG/JSON-LD extraction, junk-title filtering,
manual-import file loading (bad JSON handled), text chunking and utils.

**Real bug caught by the new tests (fixed):** subtitle tag stripping replaced inline
tags with a space, leaving a stray space before punctuation ("tama ?" instead of
"tama?") in parsed captions. `subtitles._clean_text` now collapses space-before-punctuation.

**Dependency audit:** no known CVEs in the installed set. `yt-dlp` remains the most
volatile dependency (update regularly; see `docs/RESEARCH.md`).

**Complexity profile (informational, accepted):** the branchiest functions are
`process_url` (28), `extract_post` (17) and `classify` (15) — orchestration code with
dense fallback ladders, now covered by 144 offline checks plus live end-to-end runs.
No refactor deemed worth the churn at this stage.

**Log-injection hardening (F-09):** remote content (URLs, captions, error strings) is
interpolated into log records; a crafted value could previously forge extra lines in
`logs/extractor.log`. `config._SanitizingFormatter` now collapses CR/LF and control
characters in messages and arguments (exception tracebacks intentionally untouched).

**Live re-verification (2026-10-13, after a host restart):** dashboard `/health` 200;
live ingest of a reel succeeded and correctly reported `prev-kept` (stored whisper
transcript preserved against a weaker fresh extraction); log output is single-line.

---

## 6. How to reproduce

```powershell
cd C:\path\to\facebook-extractor
.venv\Scripts\activate

# static analysis
python -m compileall -q .
python -m ruff check .

# full functional + security + integrity suite (never touches real data)
python tests/audit_suite.py

# dashboard stored-XSS test: create an item whose caption contains
# <script>alert('xss')</script>, open http://127.0.0.1:8765/item/<id> and verify
# the page source contains &lt;script&gt; and no raw <script> tag.
```

**Artefacts added by this audit:** `ruff.toml`, `tests/audit_suite.py`, `docs/AUDIT.md`
(this file), `docs/RESEARCH.md` (external fact-finding, citations included).

---

## 7. Audit round 3 — pre-ship frontend/backend (AI-slop) audit (2026-10-13)

Method: the `impeccable` craft-floor and `audit` skill dimensions, a **visual screenshot
pass** of both pages, a new committed dashboard test suite (41 render/header checks),
`vulture` dead-code scan, a Jinja attribute-collision scan, and the primary-source
anti-slop research in `docs/ANTI_SLOP_RESEARCH.md`.

### Score card (audit-skill dimensions)

| # | Dimension | Score | Key finding |
| --- | --- | --- | --- |
| 1 | Accessibility | 4 / 4 | badges were AA-large only → now AAA (measured 7.1–8.4:1); focus rings, scopes, landmarks added |
| 2 | Performance | 4 / 4 | zero JS, one 6 KB stylesheet, no images beyond a 300-byte SVG favicon, no animation |
| 3 | Responsive | 4 / 4 | table wraps + scrolls with sticky header; metric strip wraps; 44 px touch targets on mobile |
| 4 | Theming | 4 / 4 | Radix Colors dark scales with documented step roles; machine-checked contrast in the test suite |
| 5 | Anti-patterns | 4 / 4 | card grids, glyph-as-icon and the generic dark-slate/sky palette all replaced with sourced, intentional choices |
| **Total** | | **20 / 20** | **Excellent** |

### Anti-pattern verdict

Not AI-slop. The objective tells were removed (hero-metric card row → metric strip; Unicode
glyph icon → plain value; Tailwind-default slate/sky palette → **Radix Colors dark scales**
with documented step roles and attribution). No gradient text, no glass/blur decoration, no
nested cards, no sparklines, no emoji iconography, no kicker labels, and no gratuitous
animation (motion is deliberately absent for a data-review tool).

### Findings fixed

| # | Sev | Finding | Fix |
| --- | --- | --- | --- |
| F-10 | **P1 functional** | `{{ stats.items }}` rendered the dict's bound method (`<built-in method items of dict…>`) — **caught by the screenshot pass**, invisible to string tests | bracket access `stats['items']` + committed regression test |
| F-11 | P1 a11y | `needs_login`/`skipped` badges failed WCAG AA (4.26 / 4.40:1 at 12 px) | AAA badge tokens (7.1–8.4:1), measured |
| F-12 | P2 anti-pattern | hero-metric stat cards (impeccable craft-floor "refuse") | single metric strip, weight over size, tabular figures |
| F-13 | P2 anti-pattern | Unicode `⚠` glyph standing in for an icon | removed; type column carries the value |
| F-14 | P2 responsive | wide table overflowed narrow viewports; no sticky header | `.table-wrap` scroll container + sticky `thead`, mobile tweaks |
| F-15 | P2 a11y | no focus-visible rings; default selection/scrollbars/caret unthemed | browser-surface theming from the palette (craft-floor "cheapest built-not-assembled signal") |
| F-16 | P2 a11y | row headers lacked `scope`; meta tables lacked `tbody`; segments header cells overflowed | `scope="row"`, explicit `tbody`, `<time>` elements |
| F-17 | P3 smell | the same CSS block was duplicated across two templates (copy-paste drift) | one shared `dashboard/static/style.css` + `/static` mount |
| F-18 | P2 security | no CSP/nosniff/referrer policy; `/docs` loaded CDN assets; HTML was cacheable | strict CSP middleware, `/docs`+`/redoc` disabled, `Cache-Control: no-store` on HTML, `server_header=False` |
| F-19 | P3 polish | `/favicon.ico` 404 noise on every visit | authored SVG favicon |
| F-20 | P3 polish | uvicorn banner header fingerprinting | suppressed |
| F-21 | P3 anti-pattern (resolved) | palette was a recognisable "AI starter" (Tailwind-default slate + sky) | replaced with **Radix Colors** dark scales (slate/teal/green/amber/red), step roles documented in the stylesheet, every pairing verified by a committed test (worst text ratio 7.6:1, ring 5.7:1) |
| F-22 | P3 backend rigor | 5 untyped function signatures; mypy not enforcing annotations | annotated; `disallow_untyped_defs = True` added to `mypy.ini` — still 0 errors across 29 files |
| F-23 | P3 backend rigor | quality checks lived only in docs, not in an enforced pipeline | `.pre-commit-config.yaml` with tag-verified revisions (ruff-pre-commit v0.17.0, mirrors-mypy v2.4.0) plus local hooks running all three offline suites |

### Backend "vibe-code" scan (clean)

- `vulture`: no dead code in the app (only intentional `*a, **k` test lambdas).
- No `TODO`/`FIXME`/placeholder stubs; no bare `except:`; no `print()` in library code.
- Jinja attribute/key-collision scan across templates: only `stats.items` existed (F-10) — now clean.
- Template↔route contract: every variable the templates use is provided by its route —
  proven by the 41-case render suite rather than by inspection.
- All `open()`/`read_text()` calls pass an explicit encoding; all SQL values are bound
  parameters (rounds 1–2 evidence).

### Verification of record

| Check | Result |
| --- | --- |
| `tests/dashboard_tests.py` (committed, offline, scratch DB) | **55/55 passed** (includes machine-checked palette contrast) |
| HTML-level checks (headers, assets, CSP, no inline style/script, no leak) | 33/33 passed |
| Strengthened strip checks (real counts, attention class, missing markers) | 8/8 passed |
| Visual screenshot pass | defect found (F-10) and fixed; re-verified in served HTML |
| Full battery after all changes | ruff 0 · mypy 0 (strict) · compile OK · unit 90/90 · audit 54/54 · dashboard 55/55 · `pip check` clean |

**Verdict:** ready to ship locally. Release mechanics and the 20-item gate live in
`docs/SHIP_PLAN.md`.

---

## 8. Audit round 4 — `/audit` re-run with live browser tooling (2026-10-13)

Method: fresh audit with headless Chromium (Playwright) — **axe-core 4.10.2**
(executed through the DevTools channel; the page's CSP intentionally blocks CDN
script injection, which was itself control-tested), performance timing, keyboard
tab-order probes, and a 390×844 mobile reflow check of both pages.

### Findings

| # | Sev | Finding | Fix | Verified |
| --- | --- | --- | --- | --- |
| A-1 | **P1** (WCAG 1.4.10 Reflow) | The item page expanded to 791 px inside a 390 px viewport: the global `table { min-width }` rule leaked into `.meta` tables (only the index table sits in a scroll container) | `min-width` scoped to `.table-wrap table`; `table.meta { min-width: 0 }` added defensively | `scrollWidth == innerWidth == 390`, `pageOverflows: false` on both pages |
| A-2 | P2 (WCAG 2.1.1; axe `scrollable-region-focusable`, serious) | The transcript scroller `.segments` could not be scrolled with the keyboard; same rule applied preemptively to `.table-wrap` when it overflows | `tabindex="0"` + `role="region"` + `aria-label` on both regions | axe: **0 violations** on desktop index/item and mobile item |
| A-3 | Informational | axe `color-contrast` reported "incomplete" on mobile (cannot evaluate sticky/off-viewport nodes) | none — covered by the committed machine-checked contrast test (14 pairs, all ≥ 4.5, badges AAA) | test suite |

### Controls verified live

- **CSP blocks script injection**: a CDN `<script>` insert was refused by
  `default-src 'none'` at runtime (recorded as evidence).
- Console clean; visible focus ring on the first tab stop (screenshot); logical
  tab order (downloads → filters → first row link).
- Performance: DCL 45–82 ms · load 51–88 ms · 6.8–7.3 KB HTML · one 6 KB
  stylesheet · zero JavaScript.

### Score (audit-skill dimensions)

Accessibility **4/4** · Performance **4/4** · Theming **4/4** · Responsive
**4/4** · Anti-patterns **4/4** → **20/20 (Excellent)**.
