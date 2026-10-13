# Design & Backend Resources for Builders Who Don't Want to Ship AI Slop

Curated for vibe-coders and AI-assisted builders: every entry is a primary source (official site, docs, or repo)
verified on **2026-10-13**. House rules: one link per entry; `free` / `paid` / `freemium` tags; anything I could not
confirm from the primary source is marked. Slop comes from skipped decisions, so this list favors tools that already
encode a human's decisions — use them to make choices explicit, not to avoid making them.

## SECTION A — FRONTEND / UI / UX (no-slop toolkit)

### A1. Animation & motion (the "animate.js" question)

The library people mean by "animate.js" is **anime.js**. Decide *why* something moves before picking a tool — unused
motion is itself a slop tell.

- **anime.js** — https://animejs.com — `free` (MIT; npm `animejs` 4.5.0, Jun 2026). v4 (2025) is an ESM-first rewrite: `animate()` + `createTimeline()` replace v3's `anime()` API; the site keeps v3 docs in a version switcher. *Use when:* framework-free timeline animation in vanilla JS.
- **Motion** — https://motion.dev — `free` (MIT; motion@14.1.0, Oct 2026). Ex-Framer Motion; React/Vue/vanilla. Motion+ extras are `paid`: https://motion.dev/plus. *Use when:* enter/exit, layout, and gesture animation in a JS app.
- **GSAP** — https://gsap.com/standard-license — `free` ("Standard no-charge license"; banner: "GSAP is now free for everyone, thanks to Webflow's support"). *Use when:* long choreographed scroll timelines (ScrollTrigger) that small libs handle poorly.
- **Lottie** — https://airbnb.io/lottie — `free` (lottie-web is MIT). *Use when:* motion designers hand you After Effects animation as JSON vectors; don't hand-roll complex icon animation.
- **Rive** — https://rive.app — `freemium` (verified on pricing page: free exports play a Rive splash screen; pay to remove). Runtimes are open source, MIT (https://github.com/rive-app/rive-runtime). *Use when:* interactive state-machine motion (hover/click-driven) rather than linear playback.
- **AutoAnimate** — https://auto-animate.formkit.com — `free` (MIT; 0.10.0, Jul 2026). *Use when:* you want list add/remove/move transitions with one line and zero config.
- **View Transitions API** — https://developer.mozilla.org/en-US/docs/Web/API/View_Transition_API — `free` (web standard). Same-document via JS; cross-document via CSS `@view-transition { navigation: auto }`. *Use when:* page/route changes should feel continuous — often beats adding a library.
- **`prefers-reduced-motion`** — https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion — `free` (web standard). **Every** animation must be gated behind it; it is the most common accessibility miss in AI-built UIs. Non-negotiable.

### A2. Human-designed design systems & component foundations

- **shadcn/ui** — https://ui.shadcn.com — React/Tailwind components copied into your repo (you own the code); see the registry for distributing your own: https://ui.shadcn.com/docs/registry. *Right when:* you want full ownership and to stop fighting a component library's defaults.
- **Radix Primitives** — https://www.radix-ui.com/primitives — unstyled, accessible behavior (menus, dialogs, tooltips). *Right when:* you already have a visual language and only need correct interaction semantics.
- **Radix Colors** — https://www.radix-ui.com/colors — accessible 12-step scales designed for specific UI roles. *Right when:* you need a color system, not just "some hexes" (see A3 for how to use steps).
- **Tailwind CSS** — https://tailwindcss.com — `free` (v4.3). *Right when:* you bring your own design decisions; bare Tailwind ships no taste, so generic spacing/cliché gradients are a *you* problem.
- **Tailwind Plus** (ex-Tailwind UI) — https://tailwindcss.com/plus — `paid` (price is login-gated; unverifiable without an account). *Right when:* you have no designer and need professionally designed sections to adapt.
- **Headless UI** — https://headlessui.com — `free` (v2.1, React/Vue, from the Tailwind team). *Right when:* you want unstyled accessible components with a smaller surface than Radix.
- **IBM Carbon** — https://carbondesignsystem.com — `free`. *Right when:* enterprise/dense data UI; the strongest public guidance on data tables and forms.
- **Shopify Polaris** — https://polaris.shopify.com — `free`. *Right when:* commerce or admin-style resource lists and back-office flows.
- **Atlassian Design System** — https://atlassian.design — `free`. *Right when:* complex collaborative/workflow product UI; excellent content and accessibility guidance.
- **Apple Human Interface Guidelines** — https://developer.apple.com/design/human-interface-guidelines — `free`. *Right when:* building anything that should feel native on Apple platforms — or when you need platform conventions stated plainly.
- **Material 3** — https://m3.material.io — `free`. *Right when:* Android/cross-platform Google-style UI; dynamic color and theming tokens.
- **Microsoft Fluent 2** — https://fluent2.microsoft.design — `free`. *Right when:* Microsoft-adjacent or desktop-style enterprise apps; strong interaction-state patterns.

### A3. Color & typography systems (anti-generic)

- **Radix Colors — "Understanding the scale"** — https://www.radix-ui.com/colors/docs/palette-composition/understanding-the-scale — the canonical pointer for step roles: 1–2 backgrounds, 3–5 component states, 6–8 borders, 9–10 solid fills, 11–12 text; dark mode reuses the same step numbers. Set tokens by *role*, never by hue name.
- **Open Color** — https://yeun.github.io/open-color — `free` (MIT). Small, opinionated scales; good for simple or early-stage projects.
- **Carbon color usage** — https://carbondesignsystem.com/elements/color/usage — `free`. Documented, accessible enterprise palette with token guidance.
- **OKLCH picker** — https://oklch.com — `free` (by Evil Martians). Build custom, perceptually even palettes; copy modern `oklch()` CSS values.
- **Typescale** — https://typescale.com — `free` core ("Go Pro" tier exists). Generate an internally consistent type scale and export CSS.
- **Practical Typography** — https://practicaltypography.com — `free` web edition (Butterick's honor system: pay if it earns its keep). Read "Typography in ten minutes"; adopt the key rules this week.
- **Refactoring UI** — https://www.refactoringui.com — `paid`, two free chapters (sold 30k+ copies). Visual design tactics written for developers, not designers.
- **Fontshare** — https://www.fontshare.com — `free` (commercial-use fonts from Indian Type Foundry). Professional typefaces to replace the default stack.
- **Variable fonts guide (MDN)** — https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_fonts/Variable_fonts_guide — `free`. One file, many weights/axes; fewer requests, more typographic range.
- **Opinion, not fact:** "Inter (or Roboto) everywhere" reads as a tell — it is the zero-decision default of AI-generated UIs. No primary source exists for that claim; treat it as design judgment. Pick one text face with character, pair it deliberately, and set a scale.

### A4. Inspiration with a quality bar (not Dribbble slop)

- **Awwwards** — https://www.awwwards.com — `free` (juries and scores; study *why* winners work, not just screenshots).
- **Godly** — https://godly.website — `free` — "the best design inspiration on the internet"; high signal-to-noise.
- **Land-book** — https://land-book.com — `freemium` — hand-picked landing pages; ideal for hero/marketing sections.
- **Mobbin** — https://mobbin.com — `freemium` — 620k+ real product screens; study flows and states, not just visuals.
- **siteInspire** — https://www.siteinspire.com — `free` — long-running curated gallery; good for typographic/layout ideas.
- **HTTPSTER** — https://httpster.net — `free` — style-filtered showcase (minimal, brutalist, monotone…); good for range.
- **NN/g: 10 Usability Heuristics** — https://www.nngroup.com/articles/ten-usability-heuristics/ — `free` — the classic audit checklist; run it against every flow you ship.
- **Laws of UX** — https://lawsofux.com — `free` site (book is `paid`) — psychology principles; use to justify decisions and prevent cargo-cult patterns.
- **Vercel Web Interface Guidelines** — https://vercel.com/design/guidelines — `free` (MIT repo: https://github.com/vercel-labs/web-interface-guidelines) — concrete, checkable rules for focus, forms, motion, dark mode, and i18n. Ideal PR review checklist for non-designers.

### A5. Automated slop / accessibility checks to wire into CI

Automation catches the mechanical failures; keyboard testing and the A4 heuristics catch the rest.

- **axe-core** — https://github.com/dequelabs/axe-core — `free` (MPL-2.0). Engine behind most a11y audits; run via `@axe-core/playwright` in tests.
- **Pa11y CI** — https://github.com/pa11y/pa11y-ci — `free` (LGPL-3.0). Crawl a URL list and fail builds on WCAG violations.
- **Lighthouse CI** — https://github.com/GoogleChrome/lighthouse-ci — `free` (Apache-2.0). Per-commit performance, accessibility, SEO, and best-practice budgets.
- **WebAIM Contrast Checker** — https://webaim.org/resources/contrastchecker/ — `free`. Manual pair-checking; do this for every text/background token pair.
- **W3C Markup Validation Service** — https://validator.w3.org — `free`. Catch broken markup (run on rendered HTML, not raw templates).
- **Playwright ARIA snapshots** — https://playwright.dev/docs/aria-snapshots — `free`. Structural snapshots that catch accessibility regressions; pair with `toHaveScreenshot` for visual drift.

## SECTION B — BACKEND (Python-first, non-sloppy engineering)

### B1. Reference architectures & boilerplates

- **FastAPI docs + tutorial** — https://fastapi.tiangolo.com/tutorial/ — `free`. Copy: Pydantic request/response models, dependency injection, routers; skip the anything-goes tutorials elsewhere.
- **full-stack-fastapi-template** — https://github.com/fastapi/full-stack-fastapi-template — `free` (MIT, official). Copy: project layout, env config, Docker/CI, auth wiring — only if you actually need a full app scaffold.
- **fastapi-best-practices** — https://github.com/zhanymkanov/fastapi-best-practices — `free`. Copy: domain-first layout, dependency and settings patterns. **No license file (verified 2026-10-13)** — read for ideas, don't copy code wholesale.
- **Architecture Patterns with Python** — https://cosmicpython.com — `free` online (print via O'Reilly). Copy: Repository + Unit of Work patterns, dependency inversion, explicit boundaries around I/O.
- **Pydantic docs (v2)** — https://docs.pydantic.dev/latest/ — `free`. Copy: models at system boundaries, validators, strict config; validation is the cheapest bug defense.
- **Litestar** — https://litestar.dev — `free`. Alternative ASGI framework with DI, plugins, and OpenAPI built in; choose only if its all-in-one style beats FastAPI's ecosystem for you.

### B2. Data layer

- **SQLite: Write-Ahead Logging** — https://sqlite.org/wal.html — `free`. One writer, many concurrent readers; enable WAL for any database that serves + ingests at once.
- **SQLite PRAGMA reference** — https://sqlite.org/pragma.html#pragma_integrity_check — `free`. Set `foreign_keys=ON` per connection; schedule `PRAGMA integrity_check` in maintenance.
- **SQLite Backup API** — https://sqlite.org/backup.html — `free`. Use the online backup API (`sqlite3.Connection.backup`); never copy a live `.db` file.
- **PostgreSQL docs** — https://www.postgresql.org/docs/ — `free`. Graduate when you need concurrent writers, remote/multi-user access, rich types, or extensions. Until then SQLite is a legitimate production choice.
- **Alembic tutorial** — https://alembic.sqlalchemy.org/en/latest/tutorial.html — `free`. Migrations with autogenerate; always hand-review generated scripts before committing.
- **SQLAlchemy 2.0 docs** — https://docs.sqlalchemy.org/en/20/ — `free`. If you outgrow raw SQL: typed Core/ORM, sessions, connection pooling, multiple backends.

### B3. Quality toolchain

- **Ruff** — https://docs.astral.sh/ruff/ — `free` (MIT). One Rust-fast tool for lint + format; a single config, a single CI gate.
- **mypy** — https://mypy.readthedocs.io/en/stable/ — `free` (2.4.0 docs). Static types; start with files that matter and tighten over time.
- **Vulture** — https://github.com/jendrikseipp/vulture — `free` (MIT). Dead-code finder; run periodically and expect some false positives.
- **pip-audit** — https://github.com/pypa/pip-audit — `free` (Apache-2.0, PyPA). Audits environments/requirements for known CVEs; run in CI and on a schedule.
- **pre-commit** — https://pre-commit.com — `free` (MIT). Hook runner; wire it once, keep history clean forever.
- **ruff-pre-commit** — https://github.com/astral-sh/ruff-pre-commit — the `ruff` and `ruff-format` hooks.
- **pre-commit-hooks** — https://github.com/pre-commit/pre-commit-hooks — basic hygiene: `trailing-whitespace`, `end-of-file-fixer`, `check-yaml`, `check-added-large-files`.
- **pytest "Good Integration Practices"** — https://docs.pytest.org/en/stable/explanation/goodpractices.html — `free`. Copy: src layout, per-module test files, fixtures only for real boundaries.
- **Coverage.py** — https://coverage.readthedocs.io/ — `free` (7.16). Measure branch coverage; set `fail_under` in CI so it can't quietly rot.
- **Official Python CI workflow** — https://github.com/actions/starter-workflows/blob/main/ci/python-app.yml — `free`. GitHub's starter: install deps, lint, test — extend it with mypy and pip-audit.
- **actions/setup-python** — https://github.com/actions/setup-python — `free` (official Action docs). Pin the Python version and enable pip caching.

### B4. Operating, observability & security

- **Python Logging HOWTO** — https://docs.python.org/3/howto/logging.html — `free`. Levels and configuration; log at boundaries (network, DB, subprocess), not everywhere.
- **logging.handlers** — https://docs.python.org/3/library/logging.handlers.html — `free`. `RotatingFileHandler` / `TimedRotatingFileHandler` so logs never fill a disk.
- **structlog** — https://www.structlog.org/en/stable/ — `free` (26.1). Structured, key-value/JSON logs with context; adopt when logs need to be queried, not read.
- **The Twelve-Factor App** — https://12factor.net — `free`. Config from env, logs as event streams, dev/prod parity; still the cleanest ops checklist for small apps.
- **OWASP ASVS** — https://owasp.org/www-project-application-security-verification-standard/ — `free`. Verification checklist; aim for Level 1 on a local tool, Level 2 if it becomes internet-facing.
- **OWASP FastAPI Security Cheat Sheet** — https://cheatsheetseries.owasp.org/cheatsheets/FastAPI_Security_Cheat_Sheet.html — `free`. Concrete items: auth, input validation, headers, CORS, rate limiting.
- **PyPA: Managing Application Dependencies** — https://packaging.python.org/en/latest/tutorials/managing-dependencies/ — `free`. Lock your application's dependencies; don't ship floating versions.
- **PEP 751 (`pylock.toml`)** — https://peps.python.org/pep-0751/ — `free`. The standardized lockfile format (2025); moves locking out of tool-specific files.
- **uv** — https://docs.astral.sh/uv/ — `free` (Apache-2.0). Fast resolver/installer; can produce standard lockfiles and speed up CI installs dramatically.

## Adopt for THIS project (facebook-extractor)

Context: a local, single-user tool — Python 3.14, FastAPI + Jinja2 dashboard (script-free by design, strict CSP), raw
SQLite with backups, ruff/mypy already at zero findings, offline test suites, rotating logs, pinned `requirements-lock.txt`.

**Adopt now:**

- Map the dashboard's CSS tokens to **Radix "Understanding the scale"** step roles, then verify every text pair with **WebAIM** — it is a token-renaming exercise, not a redesign.
- Replace "system default everywhere" with one intentional typeface (**Fontshare**) and a deliberate scale (**Typescale**); apply via the existing documented tokens.
- Use **Vercel Web Interface Guidelines** + **NN/g heuristics** as the review checklist for `dashboard/templates/` before any ship.
- Add a written `prefers-reduced-motion` rule to the token block now, even before motion exists, so future additions comply by default.
- Add **pre-commit** with `ruff`, `ruff-format`, and the hygiene hooks — the config (`ruff.toml`, `mypy.ini`) is already clean; hooks keep it that way off-CI.
- Stand up the **official Python CI workflow** extended with `mypy`, `pytest`, and **pip-audit**; keep `coverage` fail-under as a floor.
- Make SQLite pragmas explicit: `foreign_keys=ON` per connection, WAL for runtime DB, and `PRAGMA integrity_check` around the existing backup path (SQLite **backup API**, not file copy).
- Read two free things once: **Practical Typography** "Typography in ten minutes" and **cosmicpython** chapters 1–4.
- Tighten **Pydantic v2** models as the boundary type for extractor payloads (already a dependency — get the validation value you paid for).
- Skim **ASVS Level 1** + the **OWASP FastAPI Cheat Sheet** against `dashboard/app.py`; the headers/CSP are already there, confirm the rest of the list.

**Adopt if it grows (multi-user, public, or hosted):**

- Postgres + Alembic + SQLAlchemy 2.0 when concurrent writers or multi-user access arrive — keep SQL portable until then.
- structlog when logs must be queried; Lighthouse CI + axe-core when a public web surface exists.
- full-stack-fastapi-template as an auth/CI reference (mine it, don't fork it); uv + PEP 751 lockfiles when install reproducibility outgrows `requirements-lock.txt`.
- shadcn/ui + Radix + Motion only if the dashboard becomes a JS frontend — with reduced-motion gating and the same review checklist.

**Explicitly do NOT adopt (for now):**

- GSAP/anime.js/Lottie/Rive in the dashboard: the script-free CSP is a deliberate feature; adding JS motion weakens the security posture for zero functional gain. CSS-only motion is enough.
- Paid design products (Tailwind Plus, Refactoring UI, Mobbin Pro): nothing to convert to yet — the dashboard is hand-authored CSS and templates by design.
- A React/Next/Tailwind rewrite: scope creep for a local tool; the current server-rendered dashboard is the correct architecture.
- Wholesale copying from **fastapi-best-practices**: no license file — uncopyable; extract ideas only.
- Docker/K8s/queues/postgres-now: no deployment target; SQLite + backups is the right fit for this project's shape.
