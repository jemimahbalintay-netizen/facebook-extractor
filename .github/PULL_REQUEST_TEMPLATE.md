## Summary

<!-- What changed and why, in 1-3 sentences. -->

## Checklist

- [ ] All three suites pass: `python tests/unit_tests.py`, `python tests/audit_suite.py`, `python tests/dashboard_tests.py`
- [ ] `ruff check .` → 0 findings
- [ ] `mypy .` → 0 errors
- [ ] New behaviour is covered by a test in the matching suite
- [ ] No scraped data, credentials, or `.env` content is included
- [ ] The change does not weaken the public-only stance (no login wall bypass)
