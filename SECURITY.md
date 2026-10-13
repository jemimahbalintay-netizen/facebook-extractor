# Security Policy

## Supported versions

Only the latest release (currently **v1.0.x**) receives security fixes.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Use GitHub's private reporting instead:
**Security tab → Report a vulnerability** on this repository
(this opens a private GitHub Security Advisory that only the maintainer sees).

You can expect an initial response within a few days. If the report is valid,
a fix will be released and you will be credited unless you prefer otherwise.

## Scope and threat model

This is a **local, single-user tool**. Understanding its design limits what
counts as a vulnerability:

- The dashboard is **unauthenticated by design** and binds to `127.0.0.1`. If
  you bind it to a reachable interface (`--host 0.0.0.0`) you are exposing your
  extracted content to the network; the CLI prints a warning when you do this.
  This is an accepted, documented risk — not a vulnerability.
- Extracted content (captions, transcripts, post text) is **untrusted input**
  from Facebook. It is escaped everywhere it is rendered (Jinja autoescape,
  no `|safe`), never executed, and never fetched server-side from stored URLs.
- SQLite stores data locally; no content leaves the machine except the URLs you
  explicitly ingest, the configured AI endpoint (DeepSeek/NIM), and any audio
  downloaded for transcription.

## Secrets policy

- No credentials belong in this repository. `.env`, `cookies.txt`, `data/`,
  `logs/` and `captions/` are gitignored; CI runs a dependency audit and the
  project ships a secret-scanning-friendly layout.
- A classic GitHub token once pasted into a chat transcript is compromised by
  definition: **revoke it** at `github.com/settings/tokens`, then create a
  fine-grained replacement (single repository, `Contents` + `Workflows`,
  short expiry).
- If a secret is ever committed: rotate it first, then purge it from history
  (`git filter-repo` / BFG) before making anything public.

## What this project will never do

- Bypass login walls, CAPTCHAs, or access controls (see the README's legal
  section). Reports requesting such features are out of scope.
