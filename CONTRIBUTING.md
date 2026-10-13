# Contributing

Thanks for considering a contribution! This is a small, focused local tool —
the best contributions are bug reports with reproduction steps, extraction
regressions (Facebook changes often), and documentation fixes.

## Ground rules

- **No login-wall bypass, CAPTCHA solving, or private-content access.** PRs
  that try to defeat authentication will be closed. The tool's public-only
  stance is a feature, not a limitation (see `SECURITY.md`).
- **No scraped data in the repository.** `data/`, `logs/`, `captions/` and
  `.env` are gitignored — keep it that way.
- **Every change keeps the quality gates green.**

## Development setup

```powershell
git clone https://github.com/jemimahbalintay-netizen/facebook-extractor.git
cd facebook-extractor
python -m venv .venv
.venv\Scripts\activate                 # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt -r requirements-optional.txt
pip install pre-commit ruff==0.17.0 mypy==2.4.0 vulture pip-audit
pre-commit install
```

## Before you open a PR

```powershell
python tests/unit_tests.py        # 90 parsing/mapping checks
python tests/audit_suite.py       # 54 pipeline/security/integrity checks
python tests/dashboard_tests.py   # 55 render/header/contrast checks
ruff check .                      # 0 findings
mypy .                            # strict, 0 errors
```

All suites run offline against scratch databases and never touch real data.

## Style

- Python 3.11+ syntax, type annotations everywhere (mypy strict is enforced).
- Follow the existing module layout: extractors in `extractor/`, AI in `ai/`,
  exporters in `export/`, routes/templates in `dashboard/`.
- Log with `logging` (never `print` outside CLI/scripts); errors carry context.
- New behaviour needs a test in the matching suite. Parser changes belong in
  `tests/unit_tests.py`; pipeline semantics in `tests/audit_suite.py`;
  anything rendered by the dashboard in `tests/dashboard_tests.py`.
- Keep the dashboard script-free (the strict CSP is load-bearing).

## Commit messages

Conventional commits: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`,
`chore:`. One logical change per commit; reference an issue when one exists.

## Reporting extraction regressions

Facebook's pages change frequently. A good bug report includes:

1. The URL shape (you may redact the ID): e.g. `share/r/…`, `share/p/…`.
2. The exact command you ran.
3. The stored row from `python main.py status` or the `error_message` field.
4. Your yt-dlp version (`pip show yt-dlp`) — most video regressions are fixed
   upstream by updating yt-dlp first.

## License

By contributing you agree that your contributions are licensed under the
[MIT License](LICENSE).
