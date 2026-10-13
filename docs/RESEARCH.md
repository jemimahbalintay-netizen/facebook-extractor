# RESEARCH.md — facebook-extractor fact-finding (compiled 2026-10-12)

Method: primary sources first (official docs, model cards, extractor source, court opinion PDF, spec sites); each claim links its source. Local probes run on this machine on 2026-10-12: yt-dlp 2026.08.19 (temp venv), curl with two user-agents against live public share URLs, and extraction of the 9th Circuit opinion text from the court's own PDF. Claims with no verifiable primary source are marked **unverified**.

## 1. yt-dlp + Facebook (2025–2026)

- Current `yt_dlp/extractor/facebook.py` (master, fetched 2026-10-12) matches `/reel/<id>` (FacebookReelIE), `/videos/`, `/posts/`, `watch`, `groups/...` etc. The regex contains **no** `share/r`, `share/v` or `share/p` entries, and no test cases use share URLs: https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/facebook.py
- Despite that, `share/r` and `share/v` work **via redirect handling**: GenericIE fetches the share URL, follows Facebook's HTTP redirect, and re-dispatches the canonical URL to the Facebook extractor. Probe (yt-dlp 2026.08.19, 2026-10-12): `[generic] → [redirect] Following redirect to .../reel/965857485908178/ → [facebook:reel] → success` for https://www.facebook.com/share/r/1CPCCnxYvr/ and https://www.facebook.com/share/v/14tydnP6xFo/ (same trace, id 1551874222589289). GenericIE redirect logic: https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/generic.py
- `share/p` post links resolve to `/<user>/posts/pfbid...` and then fail when the post is only visible logged-in. Probe outcome: `ERROR: [facebook] pfbid...: Unable to download webpage: HTTP Error 404`. The classic user-visible error for gated Facebook pages is `Cannot parse data` (raised at facebook.py L828); maintainers confirm it is intentionally generic and that such URLs are not accessible without cookies (issue #16482, closed): https://github.com/yt-dlp/yt-dlp/issues/16482
- Login wall handling: the extractor detects `id="login_form"` / `id="loginbutton"` and calls `raise_login_required()`: https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/facebook.py (L760-762). Resulting message (common.py `_login_hint`): "This video is only available for registered users. Use --cookies-from-browser or --cookies for the authentication. See https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp for how to manually pass cookies." https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/common.py (L595, L1246)
- Password login for Facebook was removed as broken in Dec 2025 (PR #15434), so cookies are the supported auth path: https://github.com/yt-dlp/yt-dlp/pull/15434
- Ongoing breakage is visible in the tracker (open facebook issues as of 2026-10-12): #17797 (2026-10-09), #17720 "Cannot parse data" (2026-09-23, triage), #17643 (2026-09-07, site-bug), #16880, #16652: https://github.com/yt-dlp/yt-dlp/issues/17720 · https://github.com/yt-dlp/yt-dlp/issues/17643
- Implications for this project:
  - Keep feeding share URLs to yt-dlp as-is; the GenericIE redirect path is what makes share/r & share/v work. Resolving the redirect first (already in `extractor/net.py`) and passing the `/reel/` URL is an equally valid path.
  - Add `HTTP Error 404` / `unable to download webpage` to `LOGIN_ERROR_MARKERS` — the observed gated-post failure is not matched by the current marker list.
  - Cookie support (`cookies.txt`) is correct and the only documented route; never assume password login.

## 2. Meta link previews (facebookexternalhit vs browser UA)

- Meta documents the crawler: "FacebookExternalHit … crawls the content of an app or website that was shared… gathers, caches, and displays information … such as its title, description, and thumbnail image"; UA strings `facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)` and `facebookexternalhit/1.1`; requirements include gzip/deflate and OG properties within the first 1 MB: https://developers.facebook.com/docs/sharing/webmasters/crawler
- Meta's sharing guide defines `og:description` as "A brief description of the content, usually between 2 and 4 sentences"; ogp.me calls it "A one to two sentence description". Neither specifies a character cap: https://developers.facebook.com/docs/sharing/webmasters/ · https://ogp.me/
- Empirical probe (2026-10-12, this machine):
  - `GET https://www.facebook.com/share/p/1JA3RuYHBE/` with crawler UA → HTTP 200, redirected to `/0xSojalSec/posts/pfbid0s3...`, `og:title` = author ("Md Ismail Sojal"), `og:description` = **exactly 200 characters** ending in "…".
  - Same URL with normal Chrome UA → HTTP 400, no OG tags. `https://www.facebook.com/share/r/1CPCCnxYvr/` behaved the same (crawler 200 → `/reel/965857485908178/`, description 203 raw chars incl. entities; browser 400). `https://www.facebook.com/share/v/14tydnP6xFo/` crawler 200 → `/reel/1551874222589289/`.
  - The ~200-char `og:description` truncation is therefore observed Facebook preview behavior, **not documented by Meta** (unverified as an official limit).
- Implications for this project:
  - The crawler-UA strategy in `extractor/facebook_post_extractor.py` is confirmed correct; keep the link-preview-first ordering and the browser fallback for non-share pages.
  - Truncated og:description must not be treated as the full caption — the existing `_looks_truncated_preview` warning is right; prefer yt-dlp descriptions when available (local `data/extracted.jsonl` shows both ~150–200-char preview captions and much longer full captures).
  - A browser-UA HTTP 400 on a share URL is expected behavior, not a bug; the crawler-UA result should win.

## 3. NVIDIA NIM hosted API (integrate.api.nvidia.com)

- Endpoint: `https://integrate.api.nvidia.com`, `POST /v1/chat/completions`, "Compatible with OpenAI" (LLM APIs reference): https://docs.api.nvidia.com/nim/reference/llm-apis
- Auth: HTTP bearer; official sample snippets use `Authorization: Bearer $NVIDIA_API_KEY` with the OpenAI SDK (`base_url="https://integrate.api.nvidia.com/v1"`): https://docs.api.nvidia.com/nim/reference/deepseek-ai-deepseek-v4-flash-infer . Keys issued by the portal start with `nvapi-` ("Both Personal API Keys (starting with nvapi-) and Legacy API Keys are supported"): https://docs.nvidia.com/nim/large-language-models/2.0.4-pb6/deployment/model-download.html
- Reasoning models are exposed with `chat_template_kwargs` (`{"thinking": true|false, "reasoning_effort": ...}`) and reasoning text is returned as `reasoning` **or** `reasoning_content` on the message/delta (official generated snippets: `getattr(message, "reasoning", None) or getattr(message, "reasoning_content", None)`): https://docs.api.nvidia.com/nim/reference/deepseek-ai-deepseek-v4-flash-infer
- Rate limits: no official numeric page found — docs.api.nvidia.com's model list is silent, `build.nvidia.com/faq` returns 404, and the NVIDIA API Trial Terms of Service PDF contains no "rate limit", "throttle", "fair use" or 429 language (text extracted 2026-10-12): https://assets.ngc.nvidia.com/products/api-catalog/legal/NVIDIA%20API%20Trial%20Terms%20of%20Service.pdf . NVIDIA's own developer forum has multiple 2026 threads reporting a default of **40 requests/minute** and 429 errors; an NVIDIA moderator replies that increases cannot be approved via the forum: https://forums.developer.nvidia.com/t/api-rate-limit-increase-for-nvidia-nim/366043 · https://forums.developer.nvidia.com/t/request-to-increase-nvidia-nim-api-rate-limit-40-200-rpm/379653 . The 40 RPM figure is **unverified as official documentation**.
- Implications for this project:
  - To use NIM, set `DEEPSEEK_BASE_URL=https://integrate.api.nvidia.com/v1`, `DEEPSEEK_MODEL=deepseek-ai/deepseek-v4.1-flash` and an `nvapi-` key (main.py already prints this guidance).
  - The client's 429/timeout backoff is appropriate; add optional pacing near 40 RPM for batching (`cmd_summarize --delay` exists).
  - Only `message.content` is the answer; `reasoning_content` must stay out of summaries (client already tolerates and logs it).

## 4. deepseek-ai/deepseek-v4.1-flash on NIM

- HuggingFace model card: multimodal 552B MoE (8B active prefill / 16B decode), text+image → text, context up to **1M tokens**, continuously controllable reasoning effort **1–100**, recommended sampling `temperature=1.0`, `top_p=0.95/1.0`, `max_tokens >= 256K`, MIT license, released Sept 2026: https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash
- NVIDIA model card (build.nvidia.com): "Combined input and output context length is **1,048,576 tokens**"; "continuously controllable reasoning effort"; "the prompt protocol supports thinking content, tool calls, and structured API responses"; OpenAI-compatible NIM API; NGC container released 2026-09-30: https://build.nvidia.com/deepseek-ai/deepseek-v4.1-flash/modelcard · https://catalog.ngc.nvidia.com/orgs/nim/teams/deepseek-ai/models/deepseek-v4.1-flash
- Hosted parameter limits: the model is **not listed** in the docs.api.nvidia.com LLM reference (page updated 2026-10-05 lists only deepseek-v4-flash, -0731 and v4-pro; the v4.1-flash slugs return 404): https://docs.api.nvidia.com/nim/reference/llm-apis . Exact hosted `max_tokens` ceiling and JSON-mode behavior for v4.1-flash are therefore **unverified**.
- `response_format={"type":"json_object"}`: the documented hosted schema for the closest sibling (deepseek-v4-flash) sets `additionalProperties: false` and does **not** include `response_format` → unsupported on that hosted endpoint; self-hosted NIM (vLLM containers) does document `json_object` support, but that is not the hosted service: https://docs.api.nvidia.com/nim/reference/deepseek-ai-deepseek-v4-flash-infer · https://docs.nvidia.com/nim/large-language-models/1.8.0/structured-generation.html
- Max output: base-model guidance is only "max_tokens >= 256K"; the sibling hosted endpoint documents `max_tokens` max **16,384**: https://docs.api.nvidia.com/nim/reference/deepseek-ai-deepseek-v4-flash-infer (v4.1 hosted cap unverified).
- Implications for this project:
  - The client's "try json_object, fall back to plain prompt" logic matches the evidence; do not make JSON mode a hard requirement.
  - Keep budgets modest (current default 8,192 / ceiling 32,768) instead of assuming 256K on hosted NIM.
  - Reasoning is enabled/controllable per request; for cheap summaries consider `extra_body={"chat_template_kwargs": {"thinking": false}}` (documented pattern for v4 NIM models) and keep the empty-content retry path.

## 5. faster-whisper parameters to reduce hallucinations

- Defaults in `WhisperModel.transcribe` (source, fetched 2026-10-12): `temperature=[0.0,0.2,0.4,0.6,0.8,1.0]`, `compression_ratio_threshold=2.4`, `log_prob_threshold=-1.0`, `no_speech_threshold=0.6`, `condition_on_previous_text=True`, `prompt_reset_on_temperature=0.5`, `vad_filter=False`; `BatchedInferencePipeline` defaults `vad_filter=True` (README: "Vad filter is enabled by default for batched transcription"): https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py · https://github.com/SYSTRAN/faster-whisper/blob/master/README.md
- Skip rule (transcribe.py ~L1219): a segment is skipped when `no_speech_prob > no_speech_threshold`, **unless** `avg_logprob > log_prob_threshold` (then it is not treated as silence). Same semantics in openai/whisper: https://github.com/openai/whisper/blob/main/whisper/transcribe.py (L296-303)
- Temperature fallback: if decoding fails `compression_ratio_threshold` or `logprob_threshold`, the next temperature is tried; when temperature >0.5 whisper stops feeding previous text as prompt (`condition_on_previous_text` guard, whisper L503-504): https://github.com/openai/whisper/blob/main/whisper/transcribe.py
- README guidance/samples: canonical example uses `condition_on_previous_text=False`; VAD section says Silero VAD removes non-speech and is "conservative … only removes silence longer than 2 seconds" (tunable via `vad_parameters`): https://github.com/SYSTRAN/faster-whisper/blob/master/README.md
- `hallucination_silence_threshold` (default `None`) skips silence before suspected hallucinations when set (seconds): https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py (L1298-1330)
- Implications for this project:
  - Current call (`vad_filter=True`, `condition_on_previous_text=False`, `beam_size=1`) already matches the README example; keep it.
  - For music/near-silent clips, additionally pin `temperature=0.0` (no sampling fallback), optionally set `hallucination_silence_threshold`, and keep the ≥20-char discard gate (`MIN_WHISPER_TEXT_CHARS`).
  - Leave `no_speech_threshold`/`log_prob_threshold` at defaults unless measured; they already implement the documented silence check.

## 6. Whisper language codes for Filipino / Taglish

- The official language list contains `"tl": "tagalog"` (tokenizer.py L100); there is **no `fil`** and no Taglish/mixed-language code: https://github.com/openai/whisper/blob/main/whisper/tokenizer.py#L100
- Whisper README points to that list and notes "Whisper's performance varies widely depending on the language": https://github.com/openai/whisper/blob/main/README.md
- faster-whisper: `language` is a code such as `"en"`/`"fr"`; "If not set, the language will be detected in the first 30 seconds of audio" (docstring): https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py (L304) ; the detector runs on the first window in whisper: https://github.com/openai/whisper/blob/main/whisper/transcribe.py
- Trade-offs (analysis; no primary code-switching guarantee exists): language is fixed per file. With `auto`, short music-heavy clips can misdetect and hallucinate in the wrong language; with `language="tl"` output stays Filipino-leaning but Whisper has no documented Taglish/code-switch handling, so English-mixed spans may be transliterated or dropped. Neither option is documented as correct for Taglish.
- Implications for this project:
  - Keep `auto` as default; support a per-video override to `tl` (settings key already exists) and persist the detected language (already stored as `transcript_language`).
  - Never pass `fil`; optionally re-run `tl` when a Filipino-targeted item auto-detects a third language (en/tl are both plausible for Taglish).

## 7. Legal / ToS (brief, neutral)

- Meta Terms of Service (fetched 2026-10-12): "You may not access or collect data from our Products using automated means (without our prior permission) or attempt to access data you do not have permission to access, regardless of whether such automated access or collection is undertaken while logged-in to a Facebook account." https://www.facebook.com/legal/terms (a separate "Automated Data Collection Terms" page exists but returned HTTP 400 to our request — content **unverified**: https://www.facebook.com/legal/automated_data_collection_terms)
- hiQ Labs, Inc. v. LinkedIn Corp., No. 17-16783 (9th Cir. Sept. 9, 2019) affirmed a preliminary injunction against LinkedIn blocking scraping of public profiles, holding the CFAA's "without authorization" language is a poor fit for public data: "when a computer network generally permits public access to its data, a user's accessing that publicly available data will not constitute access without authorization under the CFAA." It distinguished password-protected/restricted systems (Konop; Power Ventures) and notes other claims — "breach of contract … may also lie" — meaning it did **not** decide whether scraping breaches a site's ToS/contract. Opinion PDF (text extracted for this research): https://cdn.ca9.uscourts.gov/datastore/opinions/2019/09/09/17-16783.pdf
- Implications for this project:
  - The app's stance (public link-preview data only, no login-wall bypass, `needs_login` flag) is consistent with the CFAA distinction above; the ToS clause means automated collection still carries contract risk regardless of CFAA.
  - Keep throttle (`facebook_delay_seconds=2.0`), identifiable UAs, no crawling of gated content by default, and document that cookie usage is an explicit user opt-in. This is not legal advice.
