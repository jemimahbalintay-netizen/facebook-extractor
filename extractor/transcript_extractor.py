"""Local audio transcription via faster-whisper (optional dependency).

Audio is decoded with ffmpeg into a 16 kHz mono float32 array when ffmpeg is
available.  This keeps transcription working even when the PyAV build shipped
with faster-whisper is incompatible with the installed PyAV version; the
native PyAV decoder is used as a fallback when ffmpeg is missing.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from config import Settings, ffmpeg_available
from models import TranscriptSegment

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000


class TranscriptionUnavailable(RuntimeError):
    """Raised when audio transcription cannot run in this environment."""


def faster_whisper_installed() -> bool:
    import importlib.util

    return importlib.util.find_spec("faster_whisper") is not None


def _decode_with_ffmpeg(audio_path: Path) -> Any:
    """Decode any audio file to a 16 kHz mono float32 numpy array via ffmpeg."""
    import numpy as np

    ffmpeg_binary = shutil.which("ffmpeg")
    if not ffmpeg_binary:
        raise TranscriptionUnavailable("ffmpeg is not on PATH")

    command = [
        ffmpeg_binary,
        "-nostdin",
        "-loglevel", "error",
        "-i", str(audio_path),
        "-f", "f32le",
        "-acodec", "pcm_f32le",
        "-ac", "1",
        "-ar", str(SAMPLE_RATE),
        "pipe:1",
    ]
    process = subprocess.run(command, capture_output=True, check=False)
    if process.returncode != 0:
        stderr = (process.stderr or b"").decode("utf-8", errors="replace")[:500]
        raise TranscriptionUnavailable(f"ffmpeg decoding failed: {stderr}")
    audio_bytes = process.stdout or b""
    if not audio_bytes:
        raise TranscriptionUnavailable("ffmpeg produced no audio data")
    return np.frombuffer(audio_bytes, dtype=np.float32)


def transcribe_audio(
    audio_path: Path | str,
    settings: Settings,
    language: str | None = None,
) -> tuple[list[TranscriptSegment], str, str | None]:
    """Transcribe a local audio file.

    Returns ``(segments, full_text, detected_language)``.  Raises
    :class:`TranscriptionUnavailable` when faster-whisper is missing.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise TranscriptionUnavailable(
            "faster-whisper is not installed; run "
            "`pip install faster-whisper` to enable audio transcription"
        ) from exc

    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise TranscriptionUnavailable(f"audio file not found: {audio_path}")

    configured_language: str | None = language or settings.whisper_language
    if configured_language and configured_language.lower() in ("", "auto"):
        configured_language = None

    audio_input: Any = str(audio_path)
    if ffmpeg_available():
        try:
            audio_input = _decode_with_ffmpeg(audio_path)
            logger.info(
                "decoded %s with ffmpeg (%d samples at %d Hz)",
                audio_path.name,
                len(audio_input),
                SAMPLE_RATE,
            )
        except Exception as exc:  # noqa: BLE001 - fall back to native decode
            logger.warning(
                "ffmpeg decoding failed for %s (%s); trying native decoder",
                audio_path,
                exc,
            )
            audio_input = str(audio_path)

    model_name = settings.whisper_model or "small"
    logger.info(
        "loading faster-whisper model '%s' (first run downloads the model)",
        model_name,
    )
    try:
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
    except Exception as exc:  # noqa: BLE001 - model download / backend issues
        raise TranscriptionUnavailable(
            f"could not load faster-whisper model '{model_name}': {exc}"
        ) from exc

    try:
        segment_iter, info = model.transcribe(
            audio_input,
            language=configured_language,
            vad_filter=True,
            beam_size=1,
            condition_on_previous_text=False,
            # Pin temperature to 0.0: without the sampling fallback, whisper is
            # far less likely to hallucinate on music-only / near-silent audio
            # (complementing the MIN_WHISPER_TEXT_CHARS discard gate).
            temperature=0.0,
        )
        segments: list[TranscriptSegment] = []
        for segment in segment_iter:
            text = (segment.text or "").strip()
            if not text:
                continue
            segments.append(
                TranscriptSegment(
                    start_seconds=float(segment.start) if segment.start is not None else None,
                    end_seconds=float(segment.end) if segment.end is not None else None,
                    text=text,
                )
            )
    except Exception as exc:  # noqa: BLE001 - decoding issues must degrade
        hint = ""
        if "metadata_errors" in str(exc):
            hint = (
                " (PyAV is incompatible with this faster-whisper build; "
                "install ffmpeg and it will be used to decode audio)"
            )
        raise TranscriptionUnavailable(f"transcription failed: {exc}{hint}") from exc

    full_text = " ".join(segment.text for segment in segments).strip()
    detected_language = getattr(info, "language", None) or configured_language
    return segments, full_text, detected_language
