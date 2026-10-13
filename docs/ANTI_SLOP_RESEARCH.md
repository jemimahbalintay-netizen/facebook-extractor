# Anti-Slop Research — Preventing AI-Generated Code/Design Failures Before Shipping

Scope: facebook-extractor (local Python 3.11+ tool: yt-dlp extractors, FastAPI + Jinja2 dashboard, SQLite, CLI, OpenAI-compatible DeepSeek). Research date: 2026-10-13. Sources are primary (W3C, OWASP, USENIX/AAAI/CCS, Python/PyPA docs, FastAPI/Starlette/Uvicorn docs) unless marked otherwise. Unverifiable claims are marked "unverified".

How to use: §1 explains the failure modes so reviewers know what to look for; §2–§6 give the concrete defaults and commands; the PRE-SHIP GATE at the end is the executable checklist. Every gate row can be run by one person on a laptop.

## 1. Named failure classes of AI-generated code

- **"Vibe coding" (origin)**: Karpathy, 2025-02-02: accept-all, don't read diffs, "when I get error messages I just copy paste them in". Fine for throwaway projects; unsafe as a ship process. https://twitter.com/karpathy/status/1886192184808149383 (context: https://arxiv.org/abs/2506.23253)
- **Hallucinated dependencies ("slopsquatting")**: LLMs invent plausible package names; attackers register them. Spracklen et al., USENIX Security '25: 5.2% avg hallucinated packages (commercial models), 21.7% (open source), 205,474 unique fake names across 576k samples. https://www.usenix.org/conference/usenixsecurity25/presentation/spracklen — verify every AI-suggested package exists on PyPI before `pip install`.
- **Phantom APIs / code hallucinations**: CodeHalu (AAAI 2025) classifies mapping, naming, resource, and logic hallucinations — code that is "syntactically correct or even semantically plausible, but ultimately cannot execute as expected". https://arxiv.org/abs/2405.00253
- **"Almost right" output**: Stack Overflow Developer Survey 2025 (49k devs): #1 AI frustration is "almost right, but not quite" (66%); 45% say debugging AI code costs more time. https://survey.stackoverflow.co/2025/ai
- **Insecure code + overconfidence**: Perry et al., CCS '23: participants with AI assistants wrote significantly less secure code and were more likely to believe it was secure. https://arxiv.org/abs/2211.03622
- **Perceived vs measured speed**: METR RCT (July 2025): experienced OSS developers took 19% *longer* with AI while believing they were 20% faster — review/integration overhead is real. https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/
- **Copy-paste drift over abstraction**: GitClear (vendor research — treat as directional, not peer-reviewed) reports rising duplicated code blocks and falling refactoring since 2022. https://www.gitclear.com/ai_assistant_code_quality_2025_research
- **Test fabrication/deletion and weakened assertions**: a green suite written by the same generator proves little; require review of deleted tests/`assertNotNull` downgrades. OWASP Secure Coding with AI Cheat Sheet §8. https://cheatsheetseries.owasp.org/cheatsheets/Secure_Coding_with_AI_Cheat_Sheet.html
- **Out-of-scope edits and stale dependency versions**: agents touch lockfiles/CI/config beyond the request; models also suggest versions current at training time that now carry CVEs (OWASP cheat sheet §2, §7).
- **Silent failures / `try/except: pass`**: Ruff `S110` explains why suppressing exceptions hides errors. https://docs.astral.sh/ruff/rules/try-except-pass — "Errors should never pass silently" (Zen of Python, PEP 20). https://peps.python.org/pep-0020/
- **Rules files as persistent steering**: `.cursorrules`, `CLAUDE.md`, `AGENTS.md`, `.github/copilot-instructions.md` silently steer all future generations and can be modified by a malicious PR or by the agent itself — review them like CI config. OWASP Secure Coding with AI §6. Also treat issues/READMEs/changelogs read by agents as untrusted input (indirect prompt injection, §3).
- **Human accountability**: "AI tools do not accept responsibility for the code they generate. The developer who accepts and commits the code does." Every AI-assisted change needs a human owner who reviewed the full diff. OWASP cheat sheet §14.
- **Redundant comments and over-abstraction**: no rigorous source found; **unverified** as a measured phenomenon. Survey proxy: 16.3% of devs cite "hard to understand how or why the code works" as an AI problem (same SO 2025 source). Mitigation: dead-code tooling + human diff review (§2, §5).

## 2. Pre-ship checklist for a small local Python app (solo-dev runnable)

Anchors: OWASP ASVS 5.0 (verification-based requirements; reference as `v5.0.0-<ch>.<sec>.<req>`, e.g. `v5.0.0-1.2.5`). https://github.com/OWASP/ASVS — plus OWASP cheat sheets: Secure Coding with AI, Secrets Management §8 (detection), Error Handling, Logging, Vulnerable Dependency Management. https://cheatsheetseries.owasp.org/

- **Tests from a clean state**: `.venv\Scripts\python.exe -m pytest -q` (https://docs.pytest.org/); failure paths (bad URL, network error, empty API key) must be exercised, not just happy paths.
- **Lint + types**: `.venv\Scripts\python.exe -m ruff check .` and `-m mypy .` (https://docs.astral.sh/ruff/, https://mypy.readthedocs.io/en/stable/command_line.html). Zero findings, or every ignore has a written rationale (as in this repo's `ruff.toml`).
- **Dead code**: `.venv\Scripts\python.exe -m vulture .` — review hits; remove unused functions/imports left by refactors. https://github.com/jendrikseipp/vulture/
- **Dependency audit**: `python -m pip_audit` (PyPA tool, checks installed deps against the Python Packaging Advisory DB via PyPI) and `python -m pip check` for broken requirements. https://pypi.org/project/pip-audit/ ; https://cheatsheetseries.owasp.org/cheatsheets/Vulnerable_Dependency_Management_Cheat_Sheet.html
- **Secrets scan before first push/zip**: `gitleaks detect --source .` (https://github.com/gitleaks/gitleaks) and confirm `.env` is untracked + listed in `.gitignore`; rotate anything found. OWASP Secrets Management §8.
- **Error paths**: every `except` either logs with context, re-raises, or is a deliberate, commented fallback; no `except: pass` without justification (Ruff E722/S110/BLE001, §5).
- **Data-loss paths**: if SQLite is the store — back up via the SQLite backup API/`VACUUM INTO` (https://sqlite.org/backup.html; https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup), run `PRAGMA integrity_check` (https://sqlite.org/pragma.html#pragma_integrity_check) and restore the backup once for real. Any destructive migration (DELETE/DROP) gets a pre-run backup file.
- **Rollback**: ship tied to a git tag + a lockfile (§6) so "previous working version" is reproducible; keep the last good `requirements` lock.
- **Docs accuracy**: run the README quickstart verbatim in a fresh venv; every command must work exactly as written (no stale flags/paths).
- **Record decisions**: one line in `docs/` for choices like "dashboard bound to 127.0.0.1, no auth, single user" so future-you does not "fix" it accidentally.
- **Credential-grade local files**: `cookies.txt` contains authenticated session material — keep it gitignored (this repo does), out of AI-tool context (OWASP Secure Coding with AI §9), and rotate cookies if ever leaked. `.env` gets the same treatment.
- **Full-diff review of AI-assisted changes**: read every changed file, especially lockfiles, config, and tests; do not approve from the summary alone (OWASP cheat sheet §7).

## 3. FastAPI + Jinja2 correctness/security defaults

- **Template autoescape**: `Jinja2Templates(directory=...)` builds `jinja2.Environment(autoescape=jinja2.select_autoescape())`, so `.html` templates autoescape user data. If you pass your own `env=`, YOU must enable autoescape — it is not added. https://github.com/encode/starlette/blob/master/starlette/templating.py ; https://fastapi.tiangolo.com/advanced/templates/
- **Autoescape bypasses**: never use `|safe` / `{% autoescape false %}` on extracted content (captions, author names, transcripts are attacker-influenced Facebook data). Autoescape protects `{{ }}` only; `|safe` opts out. https://jinja.palletsprojects.com/en/stable/templates/#html-escaping
- **Response headers**: for a localhost dashboard the important ones are minimal — bind to loopback (§below), and suppress fingerprinting with `uvicorn --no-server-header`. Do not copy internet-app headers (HSTS/CORS) blindly; CORS is unnecessary for same-origin Jinja pages. OWASP FastAPI Security §ASGI Server Hardening. https://cheatsheetseries.owasp.org/cheatsheets/FastAPI_Security_Cheat_Sheet.html
- **Uvicorn**: `--host` defaults to `127.0.0.1` (keeps a personal tool local); `0.0.0.0` exposes it on the LAN and must be a deliberate choice. `--workers` is "not valid with --reload"; for a SQLite app prefer 1 worker (multi-process + SQLite = write contention). `--reload` is development-only. https://uvicorn.dev/settings/ ; https://fastapi.tiangolo.com/deployment/manually/ ; https://fastapi.tiangolo.com/deployment/concepts/
- **/docs exposure trade-off**: `/docs`, `/redoc`, `/openapi.json` are on by default. Disable with `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)`; hiding docs is not authorization, so decide based on data sensitivity, not obscurity. https://fastapi.tiangolo.com/reference/fastapi/ ; https://fastapi.tiangolo.com/how-to/conditional-openapi/
- **Static files & favicon**: mount once — `app.mount("/static", StaticFiles(directory="static"), name="static")` — and reference via `url_for('static', path=...)` in templates. The recurring `/favicon.ico` 404 is browser noise; serve one from `static/` (or a dedicated route returning `Response(status_code=204)`, common practice — unverified as an official recommendation). https://fastapi.tiangolo.com/tutorial/static-files/ ; https://fastapi.tiangolo.com/reference/staticfiles/

## 4. Web accessibility quick wins — WCAG 2.2 AA, dark-mode data dashboard

- **Text contrast**: ≥4.5:1 normal text, ≥3:1 large text (SC 1.4.3); verify against the actual dark background, including hover/focus text. https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html
- **Non-text contrast**: ≥3:1 for UI components, chart/icon strokes, and focus indicators against adjacent colors (SC 1.4.11). https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html
- **Focus visibility**: never remove outlines (failure F78); SC 2.4.7 (AA) + SC 2.4.11 Focus Not Obscured Minimum (new in 2.2). For a robust indicator use ~2px + 3:1 contrast — the SC 2.4.13 (AAA) size/contrast target is a good implementation guide even if not required at AA. https://www.w3.org/WAI/WCAG22/Understanding/focus-visible.html ; https://www.w3.org/WAI/WCAG22/Techniques/failures/F78 ; https://www.w3.org/WAI/WCAG22/Understanding/focus-appearance.html
- **Labels + names**: every input has a visible label (SC 3.3.2, A) that matches the accessible name (SC 2.5.3 Label in Name, A); pair labels/headers to controls via real semantics (SC 1.3.1). https://www.w3.org/WAI/WCAG22/Understanding/labels-or-instructions.html ; https://www.w3.org/WAI/WCAG22/Understanding/label-in-name.html
- **Semantics/landmarks**: one `<main>`, `<header>`, `<nav>`, `<footer>`; logical headings; a "skip to main content" link. https://www.w3.org/WAI/tutorials/page-structure/ ; https://www.w3.org/WAI/ARIA/apg/practices/landmark-regions/
- **Data tables**: `<caption>`, `<th scope="col|row">` (W3C technique H63); for a sorted column expose `aria-sort`. https://www.w3.org/WAI/WCAG22/Techniques/html/H63 ; https://www.w3.org/WAI/ARIA/apg/patterns/table/
- **Page basics**: `<html lang="en">` (SC 3.1.1) and a descriptive `<title>` (SC 2.4.2) — this repo's templates already set `lang="en"`; keep it that way. https://www.w3.org/WAI/WCAG22/Understanding/language-of-page.html
- **Don't use color alone**: status/severity must be conveyed with text or shape too (SC 1.4.1, A) — dark dashboards with red/green flags fail color-blind users otherwise. https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html
- **`color-scheme` meta**: `<meta name="color-scheme" content="dark light">` makes native controls/scrollbars match the theme. https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/meta/name/color-scheme
- **Reduced motion**: wrap non-essential animation in `@media (prefers-reduced-motion: reduce)`; SC 2.3.3 (AAA) is the guideline, and auto-moving content must be pausable under SC 2.2.2 (A). https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion ; https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html

## 5. Python hygiene that LLM-written code commonly breaks (and how to detect it)

- **Mutable default arguments** (`def f(x, cache={})`): defaults are evaluated once and shared across calls — Ruff **B006**; Python tutorial "Important warning". https://docs.astral.sh/ruff/rules/mutable-argument-default/ ; https://docs.python.org/3/tutorial/controlflow.html#default-argument-values
- **Shadowing builtins** (`list`, `id`, `type` as names): Ruff **A001** (variables) / **A002** (arguments). https://docs.astral.sh/ruff/rules/builtin-variable-shadowing/
- **Broad/bare excepts**: bare `except:` → **E722**; blind `except Exception` → **BLE001**; silent `try/except/pass` → **S110** (suggest **SIM105** `contextlib.suppress`). Documented, scoped ignores are acceptable (this repo does this in `ruff.toml`) — undocumented ones are the risk. https://docs.astral.sh/ruff/rules/bare-except/ ; https://docs.astral.sh/ruff/rules/blind-except/ ; https://docs.astral.sh/ruff/rules/suppressible-exception/
- **Resource leaks**: unclosed files → Ruff **SIM115** (`open` without context manager); use `with` per the Python tutorial, and `with requests.Session() as s:` for sessions. https://docs.astral.sh/ruff/rules/open-file-with-context-handler/ ; https://docs.python.org/3/tutorial/inputoutput.html#reading-and-writing-files ; https://requests.readthedocs.io/en/latest/user/advanced/#session-objects
- **Unbounded retries**: always set an explicit `total` and a `backoff_factor` on `urllib3.util.Retry` (older APIs treated `total=None` as "no constraint"); also set connect/read timeouts so retries cannot hang forever. https://urllib3.readthedocs.io/en/stable/reference/urllib3.util.html#urllib3.util.Retry
- **Timezone-naive datetimes**: `datetime.now()` returns naive; prefer `datetime.now(tz=timezone.utc)`/aware objects, store UTC ISO-8601. Detect via Ruff **DTZ005** (and DTZ001–DTZ007 family). https://docs.python.org/3/library/datetime.html#aware-and-naive-objects ; https://docs.astral.sh/ruff/rules/call-datetime-now-without-tzinfo/
- **Encoding on Windows**: text `open()` defaults to the locale encoding (often cp1252 on Windows) — always pass `encoding="utf-8"`, and/or run with `PYTHONUTF8=1`; Ruff **PLW1514** flags missing encodings (preview) and PEP 597 documents the `EncodingWarning` approach. https://docs.python.org/3/library/functions.html#open ; https://docs.python.org/3/library/os.html#utf8-mode ; https://peps.python.org/pep-0597/ ; https://docs.astral.sh/ruff/rules/unspecified-encoding/
- **Tool set**: `ruff` (lint) + `mypy` (types) + `vulture` (dead code) catches most of the above statically; retries, leaks under error paths, and backup/restore still need tests (§2).

## 6. Requirements pinning / versioning strategy for a shipped local tool

- **Apps pin, libraries range**: this is an application, so ship with a lock that captures all transitive pins. The Python Packaging User Guide's application-dependency workflow exists precisely for this and lists tooling (pip-tools, uv, PDM, Pipenv, Poetry). https://packaging.python.org/en/latest/tutorials/managing-dependencies/
- **Standard lockfile**: PEP 751 `pylock.toml` is Final and maintained as the canonical PyPA spec; it is "secure by default" with artifact hashes, unlike requirements.txt where hashes are opt-in. https://peps.python.org/pep-0751/ ; https://packaging.python.org/en/latest/specifications/pylock-toml/
- **Practical shape**: keep readable `requirements.txt`/`requirements-optional.txt` with bounded ranges as the human-editable constraint file, generate an exact-pin lock for release (`uv lock`+`uv sync --locked`, or `pip-compile` from pip-tools, or `uv export --format pylock.toml` — pip's `pip lock` was experimental per secondary source, **unverified**), and install the lock on the shipping machine. https://docs.astral.sh/uv/ ; https://github.com/jazzband/pip-tools
- **Automate bumps, don't auto-trust them**: enable Dependabot/Renovate plus a scheduled `pip-audit`; patch/patch-minor bumps can auto-PR, majors get manual review re-running the §2 checklist. https://cheatsheetseries.owasp.org/cheatsheets/Vulnerable_Dependency_Management_Cheat_Sheet.html
- **Range syntax is standardized**: use PEP 440-style specifiers (`>=2.32,<3`) in the constraint file — the packaging specs define accepted version and dependency specifier syntax. https://packaging.python.org/en/latest/specifications/version-specifiers/ ; https://packaging.python.org/en/latest/specifications/dependency-specifiers/
- **Version integrity**: frozen installs make rollback meaningful — the same lock + git tag reproduces the last known-good build.

## PRE-SHIP GATE

| # | Item | How to verify | Done |
|---|------|---------------|------|
| 1 | Tests pass from clean checkout | `.venv\Scripts\python.exe -m pytest -q` exits 0 | ☐ |
| 2 | Failure paths tested (bad URL, network error, missing API key) | audit test names + `-m pytest tests` coverage of error branches | ☐ |
| 3 | Lint clean | `.venv\Scripts\python.exe -m ruff check .` → 0 findings; every `ignore` has a rationale comment | ☐ |
| 4 | Types clean | `.venv\Scripts\python.exe -m mypy .` → 0 errors | ☐ |
| 5 | Dead code reviewed | `.venv\Scripts\python.exe -m vulture .` → hits triaged/removed | ☐ |
| 6 | Dependency audit + integrity | `python -m pip_audit` → no known vulns; `python -m pip check` → "No broken requirements" | ☐ |
| 7 | No secrets committed | `gitleaks detect --source .` → clean; `.env` untracked in `git status` | ☐ |
| 8 | No silent failures | grep for `except:` / `except Exception:` followed by `pass`; each has log or comment | ☐ |
| 9 | DB backup + restore drill | `PRAGMA integrity_check` returns `ok`; fresh backup restores into a scratch DB | ☐ |
| 10 | Rollback possible | release tagged in git; exact-pin lockfile committed and installs in a fresh venv | ☐ |
| 11 | README quickstart accurate | run every command verbatim in a fresh venv; no stale flags/paths | ☐ |
| 12 | Jinja autoescape on for `.html` | confirm `Jinja2Templates(directory=...)` (no custom `env=` without `select_autoescape`) | ☐ |
| 13 | Dashboard stays local by design | run command binds `127.0.0.1`; `0.0.0.0` only if documented | ☐ |
| 14 | /docs exposure decided | either `docs_url=None/openapi_url=None`, or accepted & recorded in docs | ☐ |
| 15 | WCAG quick pass (dark table UI) | contrast ≥4.5:1 text / ≥3:1 UI+focus; visible focus ring; `<th scope>`; `<meta name="color-scheme">` | ☐ |
| 16 | Encoding-safe on Windows | no bare `open()`/`Path.read_text()` without `encoding="utf-8"` (or `PYTHONUTF8=1` documented) | ☐ |
| 17 | Cookie/env files credential-safe | `git check-ignore cookies.txt .env` → both ignored; neither passed to AI tools | ☐ |
| 18 | No autoescape bypass | `grep -rn "|safe\|autoescape false" dashboard/templates` → only reviewed, data-free uses | ☐ |
| 19 | Full diff reviewed | `git diff --stat` + read every hunk of this release; no unexplained lockfile/config/test churn | ☐ |
| 20 | Input data treated as hostile | extracted captions/authors never rendered via `|safe`; SQL uses bound parameters only | ☐ |
