# Troubleshooting

## "needs_login" / "needs_manual_import" — Facebook served a login wall or a truncated preview

Facebook increasingly requires a session even for public share links. This tool
will not bypass that; it flags the item instead. Options:

1. **Manual import** (recommended): copy the post text from your own browser and
   paste it:
   ```powershell
   python main.py manual-import --url "https://www.facebook.com/share/p/…/" --text-file captions\post.txt
   ```
2. **Your own cookies** (only for content you are authorized to process): export
   cookies from a browser where you are logged in as *yourself* (Netscape
   format), save as `cookies.txt` next to the project, and set
   `COOKIE_FILE=cookies.txt`. Note: yt-dlp removed Facebook password login in
   December 2025 — cookies are the only supported auth route.
3. **Playwright fallback**: `pip install playwright; playwright install chromium`,
   then set `ENABLE_PLAYWRIGHT=true`.

Login-gated posts usually surface as `Cannot parse data` or
`Unable to download webpage: HTTP Error 404`; both are classified as
`needs_login` here. Public posts that Facebook only previews at ~200 characters
are stored as `partial` + `needs_manual_import`.

## Region restrictions

Some content is geo-blocked. yt-dlp reports the exact error and it is stored in
`error_message`. Nothing local can fix this — manual import is the fallback.

## ffmpeg missing

Whisper can still decode many files via PyAV, but installing ffmpeg is
recommended: `winget install ffmpeg` (Windows), `brew install ffmpeg` (macOS),
`apt install ffmpeg` (Debian/Ubuntu). The tool prints a warning and continues
without it.

## yt-dlp errors (videos suddenly stop working)

Facebook changes its pages constantly. **Update yt-dlp first**:

```powershell
pip install -U yt-dlp
```

Common messages and what they mean:

| Message | Meaning / action |
|---|---|
| `Cannot parse data` | gated or layout change — cookies or wait for a yt-dlp update |
| `HTTP Error 404` | post deleted **or** login-gated (Facebook uses the same response) |
| `Unsupported URL` | the link is a text post, not a video — the post extractor handles it |
| `Sign in to confirm you're not a bot` | rate limiting or gating — slow down, retry later |

## DeepSeek / NVIDIA NIM API errors

- `DEEPSEEK_API_KEY is not set` → copy `.env.example` to `.env` and add the key.
- **NVIDIA NIM**: `DEEPSEEK_BASE_URL=https://integrate.api.nvidia.com/v1` and
  `DEEPSEEK_MODEL=deepseek-ai/deepseek-v4.1-flash`. Keys start with `nvapi-`.
- HTTP 401/403 → wrong key or no credit. HTTP 429 → rate limited (retried
  automatically with backoff).
- **Empty content from reasoning models**: models like `deepseek-v4.1-flash`
  first emit `reasoning_content`; if the budget runs out or the endpoint's
  `json_object` mode is used, the answer can be empty. The client handles both
  (drops JSON mode, doubles the budget) — see `ai/deepseek_client.py`.
- Summaries are always optional: ingestion succeeds and leaves summary fields
  empty.

## Whisper / transcription

- **Model missing**: the first run downloads the model (e.g. `small` ≈ 460 MB)
  to your Hugging Face cache. `faster-whisper` is in
  `requirements-optional.txt`.
- **`metadata_errors` / PyAV error**: the tool decodes audio with **ffmpeg**
  first, so installing ffmpeg fixes this class of failure entirely.
- **Whisper "returned no segments"** on music-only reels: that is expected —
  the caption is used as the transcript instead, and the note is stored.
- **Hallucinations**: the tool runs with `temperature=0.0`,
  `condition_on_previous_text=False` and discards results under 20 characters.
  If you still see junk, transcribe the item again with an explicit language.
- **Filipino / Taglish**: Whisper's official code for Tagalog is `tl` (there is
  no `fil` code and no mixed-language mode). `WHISPER_LANGUAGE=auto` detects the
  language from the first 30 seconds and can misdetect music-heavy openings —
  set `WHISPER_LANGUAGE=tl` or `en` for those clips.

## Dashboard

- **Port already in use**: `python main.py serve --port 8766`.
- **Stale content**: HTML is served `no-store`, so a refresh always shows the
  current database. If you re-ran an ingest while the page was open, refresh.
- **Remote access**: the dashboard has **no authentication**. Binding it to
  `0.0.0.0` exposes all extracted content and the export endpoints to your
  network; the CLI prints a warning when you do this. Keep it on `127.0.0.1`.

## CSV looks odd in Excel (values starting with an apostrophe)

That is deliberate. Cells that start with `=`, `+`, `-` or `@` are prefixed
with `'` to prevent spreadsheet formula injection from attacker-influenced
captions (OWASP CSV injection). Excel hides the apostrophe; the raw CSV
contains it.

## Windows console: UnicodeEncodeError / broken emoji

`main.py` reconfigures stdout/stderr to UTF-8 with `errors="replace"`, so
content with emoji never crashes the CLI. If glyphs still render oddly, run
`chcp 65001` or use Windows Terminal.

## "database is locked"

SQLite runs in WAL mode with short-lived connections; concurrent CLI + dashboard
access is expected to work. If you see this under heavy parallel use, retry the
command — or stop the dashboard while running big batch ingests.

## Backups and restore

```powershell
python scripts/backup_db.py            # verified snapshot, keeps the newest 10
```

Restore: stop any running commands, copy the chosen file from `data/backups/`
over `data/facebook_content.db`, then run `python main.py status` to verify.
