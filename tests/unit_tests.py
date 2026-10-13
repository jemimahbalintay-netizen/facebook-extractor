"""Offline unit tests for the pure parsing/mapping functions.

These complement ``tests/audit_suite.py`` (which focuses on pipeline
behaviour, security and integrity) by exercising the format parsers, count
parsers, HTML metadata extraction and text chunking directly.  No network,
no database, no API calls.

Usage (from the project root):
    python tests/unit_tests.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from ai.summarizer import _has_summariable_content, chunk_text  # noqa: E402
from extractor.facebook_post_extractor import (  # noqa: E402
    _clean_title,
    _looks_truncated_preview,
    extract_content_id,
    fields_from_html,
    parse_html_metadata,
    parse_json_ld,
)
from extractor.manual_extractor import (  # noqa: E402
    ManualImportError,
    read_json_file,
    read_text_file,
)
from extractor.subtitles import (  # noqa: E402
    parse_json3,
    parse_srt,
    parse_subtitle_payload,
    parse_timestamp,
    parse_ttml,
    parse_vtt,
    pick_subtitle_format,
    pick_subtitle_track,
)
from extractor.ytdlp_extractor import (  # noqa: E402
    fill_missing_counts_from_text,
    looks_like_login_error,
    map_info_to_fields,
    parse_compact_number,
)
from utils import (  # noqa: E402
    compute_content_hash,
    detect_language,
    extract_external_links,
    extract_hashtags,
    extract_mentions,
    humanize_duration,
    humanize_number,
    safe_int,
)

results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    ok = bool(condition)
    results.append((name, ok, detail))
    suffix = f"  [{detail}]" if detail and not ok else ""
    print(f"{'PASS' if ok else 'FAIL'}  {name}{suffix}")


print("=== subtitles: timestamps ===")
check("parse_timestamp vtt", parse_timestamp("00:01:02.500") == 62.5)
check("parse_timestamp srt", parse_timestamp("00:01:02,500") == 62.5)
check("parse_timestamp seconds", parse_timestamp("1.5s") == 1.5)
check("parse_timestamp milliseconds", parse_timestamp("150ms") == 0.15)
check("parse_timestamp minutes", parse_timestamp("2m") == 120.0)
check("parse_timestamp invalid", parse_timestamp("nope") is None)

print("\n=== subtitles: WebVTT / SRT ===")
vtt = (
    "WEBVTT\nKind: captions\nLanguage: en\n\n"
    "00:00:01.000 --> 00:00:03.500\nHello <b>world</b> &amp; friends\n\n"
    "00:00:04.000 --> 00:00:05.000\nSecond line\n"
)
vtt_segments = parse_vtt(vtt)
check("vtt segment count", len(vtt_segments) == 2, str(len(vtt_segments)))
check("vtt timing parsed", vtt_segments[0].start_seconds == 1.0 and vtt_segments[0].end_seconds == 3.5)
check("vtt tags + entities cleaned", vtt_segments[0].text == "Hello world & friends", vtt_segments[0].text)
check("vtt second cue", vtt_segments[1].text == "Second line")

srt = "1\n00:00:01,000 --> 00:00:02,000\nUna linea\n\n2\n00:00:03,000 --> 00:00:04,000\nIkalawa\n"
srt_segments = parse_srt(srt)
check("srt parses two cues", len(srt_segments) == 2 and srt_segments[0].start_seconds == 1.0)

print("\n=== subtitles: JSON3 / TTML / dispatch ===")
json3 = json.dumps(
    {
        "events": [
            {"tStartMs": 1000, "dDurationMs": 2000, "segs": [{"utf8": "Hi "}, {"utf8": "there"}]},
            {"tStartMs": 3000, "segs": [{"utf8": "\n"}]},
        ]
    }
)
json3_segments = parse_json3(json3)
check("json3 skips newline-only events", len(json3_segments) == 1, str(len(json3_segments)))
check("json3 text joined", json3_segments[0].text == "Hi there", json3_segments[0].text)
check(
    "json3 timing",
    json3_segments[0].start_seconds == 1.0 and json3_segments[0].end_seconds == 3.0,
)

ttml = (
    '<tt xmlns="http://www.w3.org/ns/ttml"><body><div>'
    '<p begin="00:00:01.000" end="00:00:02.500">Alin ang <span>tama</span>?</p>'
    '<p begin="3s" dur="1.5s">Salamat</p>'
    "</div></body></tt>"
)
ttml_segments = parse_ttml(ttml)
check("ttml two cues", len(ttml_segments) == 2, str(len(ttml_segments)))
check("ttml inline tags cleaned", ttml_segments[0].text == "Alin ang tama?", ttml_segments[0].text)
check(
    "ttml dur converted to end time",
    ttml_segments[1].start_seconds == 3.0 and ttml_segments[1].end_seconds == 4.5,
)
check("dispatch vtt ext", len(parse_subtitle_payload(vtt, "vtt")) == 2)
check("dispatch unknown ext falls back", len(parse_subtitle_payload(vtt, "weird")) == 2)
check("dispatch garbage payload returns empty", parse_subtitle_payload("???", "json3") == [])

print("\n=== subtitles: track/format selection ===")
language, entries = pick_subtitle_track({"es": [{"ext": "vtt", "url": "u1"}], "en": [{"ext": "vtt", "url": "u2"}]})
check("prefers english track", language == "en" and entries == [{"ext": "vtt", "url": "u2"}], str(language))
language, entries = pick_subtitle_track({"pt": [{"ext": "vtt", "url": "u"}]})
check("falls back to first available track", language == "pt")
check("empty tracks", pick_subtitle_track({}) == (None, None))
chosen = pick_subtitle_format([{"ext": "vtt", "url": "u1"}, {"ext": "json3", "url": "u2"}])
check("prefers json3 format", chosen is not None and chosen["ext"] == "json3", str(chosen))
check("format without url rejected", pick_subtitle_format([{"ext": "json3"}]) is None)

print("\n=== yt-dlp extractor: counts and error classification ===")
check("compact 49K", parse_compact_number("49K") == 49000)
check("compact 1.2M", parse_compact_number("1.2M") == 1200000)
check("compact 2B", parse_compact_number("2B") == 2000000000)
check("compact comma groups", parse_compact_number("12,345") == 12345)
check("compact invalid", parse_compact_number("abc") is None)

fields = {"title": "49K views \u00b7 387 reactions | some caption", "caption": None}
fill_missing_counts_from_text(fields)
check("counts parsed from title", fields["view_count"] == 49000 and fields["like_count"] == 387, str(fields))
fields = {"title": "1.4K reactions", "caption": None, "view_count": 123}
fill_missing_counts_from_text(fields)
check("existing counts not overwritten", fields["view_count"] == 123 and fields["like_count"] == 1400, str(fields))

check("login error: cannot parse data", looks_like_login_error("ExtractorError: Cannot parse data"))
check("login error: http 404", looks_like_login_error("Unable to download webpage: HTTP Error 404"))
check("login error: registered users", looks_like_login_error("This video is only available for registered users"))
check("login error: cookies hint", looks_like_login_error("Use --cookies-from-browser for the authentication"))
check("not a login error: timeout", not looks_like_login_error("Connection timed out"))

info = {
    "title": "Reel title",
    "description": "caption text",
    "uploader": "Page Name",
    "upload_date": "20260131",
    "duration": 42.7,
    "view_count": 1000,
    "like_count": 50,
    "comment_count": 5,
    "repost_count": 3,
    "id": "123456789",
    "webpage_url": "https://www.facebook.com/reel/123456789/",
    "url": "https://video.example/stream.mp4",
    "thumbnails": [{"url": "https://img.example/small.jpg"}, {"url": "https://img.example/large.jpg"}],
}
mapped = map_info_to_fields(info, "https://fallback.example/")
check("maps upload_date", mapped["upload_date"] == "2026-01-31", str(mapped["upload_date"]))
check("maps duration as int", mapped["duration_seconds"] == 42)
check("maps counts", mapped["view_count"] == 1000 and mapped["like_count"] == 50 and mapped["comment_count"] == 5)
check("maps share count from repost_count", mapped["share_count"] == 3)
check("maps author/page", mapped["author"] == "Page Name" and mapped["page_name"] == "Page Name")
check("thumbnail prefers explicit", mapped["thumbnail_url"] == "https://img.example/large.jpg", str(mapped["thumbnail_url"]))
check("maps content id and resolved url", mapped["content_id"] == "123456789" and mapped["resolved_url"].endswith("/reel/123456789/"))
info_no_thumb = {"title": "t", "thumbnails": []}
check("thumbnail missing tolerated", map_info_to_fields(info_no_thumb, "https://x/")["thumbnail_url"] is None)

print("\n=== post extractor: HTML metadata ===")
html = (
    '<html><head>'
    "<title>Fallback title</title>"
    '<meta property="og:title" content="OG Title" />'
    '<meta content="OG description &amp; more" property="og:description" />'
    "<meta name='description' content=\"name description\" />"
    '<meta property="og:image" content="https://img.example/t.jpg">'
    '<meta property="article:published_time" content="2026-02-01T10:00:00+0000">'
    "</head><body></body></html>"
)
metadata = parse_html_metadata(html)
check("og:title (property first)", metadata.get("og:title") == "OG Title")
check("og:description (content first)", metadata.get("og:description") == "OG description & more")
check("name=description captured", metadata.get("description") == "name description")
check("title tag fallback", metadata.get("title") == "Fallback title")

json_ld_html = (
    '<script type="application/ld+json">'
    '{"headline": "LD headline", "articleBody": "Full body text", '
    '"datePublished": "2026-01-15", "author": {"name": "LD Author"}}'
    "</script>"
)
ld = parse_json_ld(json_ld_html)
check("json-ld articleBody", ld.get("articleBody") == "Full body text")
check("json-ld author dict", ld.get("author") == "LD Author")
bad_ld = parse_json_ld('<script type="application/ld+json">{not json}</script>')
check("json-ld invalid tolerated", bad_ld == {})

check("junk title: 'Error'", _clean_title("Error") is None)
check("junk title: 'Log in'", _clean_title("Log in") is None)
check("junk title: 'Facebook'", _clean_title("  Facebook ") is None)
check("normal title kept", _clean_title("Md Ismail Sojal") == "Md Ismail Sojal")

check("truncation: three dots", _looks_truncated_preview("Free notebook turns Qwen into a..."))
check(
    "truncation: see more + log in",
    _looks_truncated_preview("See more of Some Page on Facebook. Log in or sign up."),
)
check("truncation: normal caption unaffected", not _looks_truncated_preview("A complete sentence about AI."))

post_html = (
    "<html><head>"
    '<meta property="og:title" content="Some Page" />'
    '<meta property="og:description" content="Truncated text that keeps going and then just sto..." />'
    '<meta property="og:url" content="https://www.facebook.com/somepage/posts/123456789" />'
    '<meta property="og:image" content="https://img.example/p.jpg" />'
    "</head><body></body></html>"
)
outcome = fields_from_html(post_html, "https://www.facebook.com/somepage/posts/123456789")
check("post fields: caption captured", outcome.fields.get("caption", "").startswith("Truncated text"))
check("post fields: author from og:title", outcome.fields.get("author") == "Some Page", str(outcome.fields.get("author")))
check("post fields: content id from URL", outcome.fields.get("content_id") == "123456789")
check(
    "post fields: truncation warning added",
    any("truncated" in warning.lower() for warning in outcome.warnings),
    str(outcome.warnings),
)
check("extract_content_id: story_fbid", extract_content_id("https://www.facebook.com/permalink.php?story_fbid=987&id=1") == "987")
check("extract_content_id: reel", extract_content_id("https://www.facebook.com/reel/555/") == "555")
check("extract_content_id: none", extract_content_id("https://www.facebook.com/somepage/") is None)

print("\n=== manual extractor: file loading ===")
with tempfile.TemporaryDirectory(prefix="fbx_unit_") as tmp:
    tmp_path = Path(tmp)
    text_file = tmp_path / "caption.txt"
    text_file.write_text("Kumusta mundo \u2014 hello world", encoding="utf-8")
    check("read_text_file utf-8", read_text_file(text_file) == "Kumusta mundo \u2014 hello world")

    json_file = tmp_path / "meta.json"
    json_file.write_text('{"title": "T", "view_count": 5}', encoding="utf-8")
    payload = read_json_file(json_file)
    check("read_json_file parses object", payload == {"title": "T", "view_count": 5})

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not json", encoding="utf-8")
    try:
        read_json_file(bad_json)
        check("read_json_file rejects invalid JSON", False, "no exception")
    except ManualImportError:
        check("read_json_file rejects invalid JSON", True)

    list_json = tmp_path / "list.json"
    list_json.write_text("[1, 2]", encoding="utf-8")
    try:
        read_json_file(list_json)
        check("read_json_file rejects non-object JSON", False, "no exception")
    except ManualImportError:
        check("read_json_file rejects non-object JSON", True)

print("\n=== summarizer: chunking and filtering ===")
check("chunk_text empty input", chunk_text("", 2000) == [])
check("chunk_text short input single chunk", chunk_text("short text", 2000) == ["short text"])
long_text = "Sentence number 0 about artificial intelligence. " + ". ".join(
    f"Part {i} of this long transcript" for i in range(400)
)
chunks = chunk_text(long_text, 2000)
check("chunk_text splits long text", len(chunks) >= 3, str(len(chunks)))
check("chunk_text sizes bounded", all(len(chunk) <= 2000 for chunk in chunks))
check("chunk_text no empty chunks", all(chunk.strip() for chunk in chunks))
check("chunk_text terminates and covers text", len("".join(chunks)) >= len(long_text) * 0.9)

check("summariable: skipped item", not _has_summariable_content({"status": "skipped", "caption": "x"}))
check("summariable: caption present", _has_summariable_content({"status": "partial", "caption": "hello"}))
check("summariable: transcript only", _has_summariable_content({"status": "extracted", "transcript_text": "t"}))

print("\n=== utils: text helpers ===")
tags = extract_hashtags("Great #AI and #ai tools #Dev_Tips")
check("hashtags deduped case-insensitively", tags == ["AI", "Dev_Tips"], str(tags))
mentions = extract_mentions("thanks @juan_dela and @Maria! email me at a@b.com")
check("mentions without emails", mentions == ["juan_dela", "Maria"], str(mentions))
links = extract_external_links("see https://github.com/user/repo and https://www.facebook.com/page and https://fb.watch/x/")
check("external links exclude facebook", links == ["https://github.com/user/repo"], str(links))
check("duration humanized", humanize_duration(3725) == "1h 02m 05s")
check("duration minutes", humanize_duration(95) == "1m 35s")
check("number humanized", humanize_number(12345) == "12.3K")
check("number small", humanize_number(999) == "999")
check("safe_int handles comma text", safe_int("1,234") == 1234)
check("safe_int invalid", safe_int("abc") is None)
check("detect_language empty", detect_language("") is None)
check("detect_language english", (detect_language("This is a simple English sentence about software and testing.") or "").startswith("en"))

hash_one = compute_content_hash("t", "c", "x")
check(
    "content hash deterministic (sha256)",
    hash_one == compute_content_hash("t", "c", "x") and len(hash_one) == 64,
)
check("content hash changes with content", compute_content_hash("t", "c", "y") != hash_one)
check(
    "content hash treats None as empty",
    compute_content_hash(None, None, None) == compute_content_hash("", "", ""),
)

failed = [name for name, ok, _ in results if not ok]
print(f"\n{'=' * 60}")
print(f"UNIT TESTS: {len(results) - len(failed)}/{len(results)} passed")
if failed:
    print("FAILED:")
    for name in failed:
        print("  -", name)
sys.exit(1 if failed else 0)
