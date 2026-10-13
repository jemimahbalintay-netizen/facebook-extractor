"""Build a synthetic demo database so you can explore the dashboard safely.

Creates ``data/demo.db`` with realistic-but-fake items (varied types, statuses,
transcripts with segments, and AI summaries).  Nothing here touches your real
database; serve it with:

    $env:DATABASE_PATH="data/demo.db"      # PowerShell
    python main.py serve

Usage (from the project root):
    python scripts/make_demo_db.py [--path data/demo.db]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import ensure_directories, load_settings, setup_logging  # noqa: E402
from database import (  # noqa: E402
    init_db,
    replace_transcript_segments,
    save_summary,
    update_item_fields,
    upsert_item,
)
from models import (  # noqa: E402
    ExtractedItem,
    SummaryPayload,
    TranscriptSegment,
)
from utils import utc_now_iso  # noqa: E402

MODEL = "deepseek-ai/deepseek-v4.1-flash"


def _summarize(item_id: int, payload: SummaryPayload, db_path: Path) -> None:
    """Save a demo summary and mark the item as summarized (like the pipeline)."""
    save_summary(item_id, MODEL, payload, db_path)
    update_item_fields(
        db_path=db_path, item_id=item_id, summarized_at=utc_now_iso()
    )


def build(db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()
    init_db(db_path)

    # --- reel with a local Whisper transcript --------------------------------
    reel = ExtractedItem(
        source_url="https://www.facebook.com/share/r/DEMO0000001/",
        resolved_url="https://m.facebook.com/watch/?v=1000000000000001",
        content_type="reel",
        content_id="1000000000000001",
        status="extracted",
        title="3 agent patterns that actually ship",
        caption=(
            "Three agent patterns that actually ship: planner-executor, "
            "tool-first routing, and reflection loops. Save this for your next build."
        ),
        transcript_text=(
            "Most agent demos look great and fail in production. The first pattern is "
            "planner executor, where a model writes a plan and a smaller model executes "
            "each step. The second is tool first routing, where the router decides the "
            "tool before the model writes any prose. The third is reflection loops, "
            "where the agent critiques its own output before returning it."
        ),
        transcript_source="whisper",
        transcript_language="en",
        author="Demo Builder",
        page_name="Demo Builder",
        upload_date="2026-09-28",
        duration_seconds=58,
        view_count=18400,
        like_count=612,
        comment_count=48,
        share_count=95,
        thumbnail_url="https://example.com/demo/reel-thumb.jpg",
        language="en",
        extracted_at="2026-10-13T09:10:00+00:00",
    )
    reel_id = upsert_item(reel, db_path)
    replace_transcript_segments(
        reel_id,
        [
            TranscriptSegment(start_seconds=0.0, end_seconds=6.4, text="Most agent demos look great and fail in production."),
            TranscriptSegment(start_seconds=6.4, end_seconds=15.1, text="The first pattern is planner executor, where a model writes a plan and a smaller model executes each step."),
            TranscriptSegment(start_seconds=15.1, end_seconds=23.8, text="The second is tool first routing, where the router decides the tool before the model writes any prose."),
            TranscriptSegment(start_seconds=23.8, end_seconds=33.5, text="The third is reflection loops, where the agent critiques its own output before returning it."),
        ],
        db_path,
    )
    _summarize(
        reel_id,
        SummaryPayload(
            short_title="Three production-ready agent patterns",
            english_summary="A short reel explaining three agent design patterns that survive production: planner-executor, tool-first routing, and reflection loops, with a save-for-later call to action.",
            filipino_summary="Ipinaliliwanag ng reel ang tatlong pattern ng AI agent na gumagana sa produksyon: planner-executor, tool-first routing, at reflection loops, kasama ang paanyayang i-save ito.",
            key_points=[
                "Planner-executor splits planning from execution",
                "Tool-first routing chooses the tool before writing prose",
                "Reflection loops let the agent critique its own output",
            ],
            detected_topics=["AI agents", "system design", "production engineering"],
            hashtags=["aiagents", "llm", "softwareengineering"],
            entities=["planner-executor", "tool-first routing", "reflection loops"],
            sentiment="positive",
            content_warnings=[],
            suggested_tags=["agents", "architecture", "best-practices"],
            virality_signals=["save-worthy list format", "practical engineering advice"],
            call_to_action="Save this for your next build.",
        ),
        db_path,
    )

    # --- video with embedded subtitles --------------------------------------
    video = ExtractedItem(
        source_url="https://www.facebook.com/share/v/DEMO0000002/",
        content_type="video",
        content_id="1000000000000002",
        status="extracted",
        title="Local transcription with Whisper, end to end",
        caption="How local Whisper transcription works: decode with ffmpeg, filter with VAD, and guard against hallucinated output.",
        transcript_text="Local transcription starts by decoding audio to sixteen kilohertz mono. Voice activity detection removes silence, and a temperature of zero keeps the model from inventing sentences on music-only clips.",
        transcript_source="subtitles",
        transcript_language="en",
        author="Demo Builder",
        page_name="Demo Builder",
        upload_date="2026-10-02",
        duration_seconds=124,
        view_count=7300,
        like_count=204,
        language="en",
        extracted_at="2026-10-13T09:12:00+00:00",
    )
    video_id = upsert_item(video, db_path)
    replace_transcript_segments(
        video_id,
        [
            TranscriptSegment(start_seconds=1.2, end_seconds=9.0, text="Local transcription starts by decoding audio to sixteen kilohertz mono."),
            TranscriptSegment(start_seconds=9.0, end_seconds=17.4, text="Voice activity detection removes silence, and a temperature of zero keeps the model from inventing sentences."),
        ],
        db_path,
    )
    _summarize(
        video_id,
        SummaryPayload(
            short_title="Local Whisper transcription, explained",
            english_summary="A walkthrough of the local transcription pipeline: ffmpeg decoding, VAD filtering, and hallucination guards on music-only audio.",
            filipino_summary="Paliwanag ng lokal na pipeline ng transkripsyon: ffmpeg decoding, VAD filtering, at mga pananggalang laban sa hallucination sa music-only na audio.",
            key_points=["ffmpeg decodes to 16 kHz mono", "VAD removes silence", "temperature=0 prevents invented sentences"],
            detected_topics=["transcription", "whisper", "audio engineering"],
            hashtags=["whisper", "transcription"],
            entities=["ffmpeg", "Whisper", "VAD"],
            sentiment="neutral",
            content_warnings=[],
            suggested_tags=["transcription", "local-first"],
            virality_signals=["technical depth"],
            call_to_action=None,
        ),
        db_path,
    )

    # --- partial post awaiting manual import ---------------------------------
    post = ExtractedItem(
        source_url="https://www.facebook.com/share/p/DEMO0000003/",
        resolved_url="https://www.facebook.com/demopage/posts/1000000000000003",
        content_type="post",
        content_id="1000000000000003",
        status="partial",
        title="Demo Page",
        caption="Facebook only served the first ~200 characters of this public post to automated readers. Paste the full text with manual-import to complete it...",
        transcript_text="Facebook only served the first ~200 characters of this public post to automated readers. Paste the full text with manual-import to complete it...",
        transcript_source="description",
        author="Demo Page",
        page_name="Demo Page",
        upload_date="2026-10-05",
        language="en",
        needs_manual_import=True,
        error_message="notes: Facebook only served a truncated public preview for this post; the full text may require manual import",
        extracted_at="2026-10-13T09:13:00+00:00",
    )
    upsert_item(post, db_path)

    # --- manual import with Filipino summary ---------------------------------
    manual = ExtractedItem(
        source_url="https://www.facebook.com/share/r/DEMO0000004/",
        content_type="reel",
        content_id="1000000000000004",
        status="extracted",
        title="Tip: paano mag-file ng receipts para sa taxes",
        caption="I-save ang resibo! Simpleng sistema para sa freelancers: isang folder, isang spreadsheet, isang backup.",
        transcript_text="I-save ang resibo. Gumawa ng isang folder para sa lahat ng resibo, isang spreadsheet para sa mga gastos, at isang backup sa cloud para hindi mawala.",
        transcript_source="manual",
        transcript_language="tl",
        author="Demo Finance PH",
        page_name="Demo Finance PH",
        upload_date="2026-10-08",
        duration_seconds=41,
        view_count=9200,
        like_count=431,
        language="tl",
        extracted_at="2026-10-13T09:14:00+00:00",
    )
    manual_id = upsert_item(manual, db_path)
    replace_transcript_segments(
        manual_id,
        [TranscriptSegment(start_seconds=0.0, end_seconds=None, text=manual.transcript_text or "")],
        db_path,
    )
    _summarize(
        manual_id,
        SummaryPayload(
            short_title="Simpleng sistema ng resibo para sa freelancers",
            english_summary="A Tagalog reel recommending a simple receipt-filing system for freelancers: one folder, one expense spreadsheet, and a cloud backup.",
            filipino_summary="Isang reel sa Tagalog na nagrerekomenda ng simpleng sistema ng pag-file ng resibo para sa mga freelancer: isang folder, isang spreadsheet ng gastos, at backup sa cloud.",
            key_points=["One folder for all receipts", "One spreadsheet for expenses", "Back up to the cloud"],
            detected_topics=["personal finance", "freelancing", "record keeping"],
            hashtags=["freelancerPH", "taxes"],
            entities=[],
            sentiment="positive",
            content_warnings=["not tax advice"],
            suggested_tags=["finance", "filipino", "how-to"],
            virality_signals=["practical checklist", "save-worthy"],
            call_to_action="I-save ang post na ito.",
        ),
        db_path,
    )

    # --- malformed URL, repaired and manually completed ----------------------
    malformed = ExtractedItem(
        source_url="https://www.facebook.com/share/p/DEMO0000005/share/r/DEMO0000006/",
        resolved_url="https://www.facebook.com/share/p/DEMO0000005/",
        content_type="malformed",
        status="extracted",
        title="Malformed share link example",
        caption="This URL contained two share paths; the repaired candidate was attempted and the user completed the record manually.",
        transcript_text="Manually imported transcript after the repaired candidate failed.",
        transcript_source="manual",
        author="Demo Page",
        duration_seconds=22,
        view_count=1500,
        malformed=True,
        extracted_at="2026-10-13T09:15:00+00:00",
    )
    malformed_id = upsert_item(malformed, db_path)
    replace_transcript_segments(
        malformed_id,
        [TranscriptSegment(start_seconds=0.0, end_seconds=None, text=malformed.transcript_text or "")],
        db_path,
    )

    # --- homepage (skipped) ---------------------------------------------------
    upsert_item(
        ExtractedItem(
            source_url="https://www.facebook.com/",
            content_type="homepage",
            status="skipped",
            error_message="facebook homepage - nothing to extract",
            extracted_at="2026-10-13T09:16:00+00:00",
        ),
        db_path,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a synthetic demo database")
    parser.add_argument(
        "--path",
        default=None,
        help="output path (default: <data dir>/demo.db)",
    )
    args = parser.parse_args()

    settings = load_settings()
    ensure_directories(settings)
    setup_logging(settings)

    db_path = Path(args.path) if args.path else settings.data_dir / "demo.db"
    build(db_path)
    print(f"demo database written: {db_path}")
    print("serve it with:")
    print(f'  $env:DATABASE_PATH="{db_path}"; python main.py serve')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
