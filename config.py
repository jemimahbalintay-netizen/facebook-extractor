"""Central configuration for the facebook-extractor project.

All values can be overridden through environment variables or a local ``.env``
file (see ``.env.example``).  Importing this module never fails because of a
missing optional dependency; callers use the dedicated helper functions
(``ffmpeg_available``) to degrade gracefully instead.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_FILE = PROJECT_ROOT / ".env"

# Load the local .env file if it exists. Variables already present in the
# process environment are NOT overwritten.
load_dotenv(ENV_FILE)

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Standard link-preview crawler identification used by Facebook itself when it
# generates previews for shared URLs.  Only public preview metadata is read.
LINK_PREVIEW_USER_AGENT = (
    "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"
)


def _env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env_str(name, "")
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = _env_str(name, "")
    if not raw:
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = _env_str(name, "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_path(name: str, default: Path) -> Path:
    raw = _env_str(name, "")
    if not raw:
        return default
    path = Path(raw)
    return path if path.is_absolute() else (PROJECT_ROOT / path)


@dataclass
class Settings:
    """Runtime settings shared by the CLI, pipeline, exporters and dashboard."""

    # Locations
    project_root: Path = PROJECT_ROOT
    data_dir: Path = PROJECT_ROOT / "data"
    logs_dir: Path = PROJECT_ROOT / "logs"
    seed_file: Path = PROJECT_ROOT / "seed_urls.txt"

    # DeepSeek / OpenAI-compatible endpoint
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-v4.1-flash"

    # Facebook extraction behaviour
    facebook_delay_seconds: float = 2.0
    enable_playwright: bool = False
    playwright_headless: bool = True
    cookie_file: Path = PROJECT_ROOT / "cookies.txt"

    # Local transcription
    whisper_model: str = "small"
    whisper_language: str = "auto"

    # AI summarisation
    max_transcript_chars: int = 20000
    auto_summarize: bool = False

    # Network robustness
    request_timeout: int = 30
    max_retries: int = 3
    retry_backoff: float = 2.0
    user_agent: str = BROWSER_USER_AGENT

    # Storage artefacts
    database_path: Path = PROJECT_ROOT / "data" / "facebook_content.db"
    jsonl_path: Path = PROJECT_ROOT / "data" / "extracted.jsonl"
    csv_path: Path = PROJECT_ROOT / "data" / "export_items.csv"
    markdown_path: Path = PROJECT_ROOT / "data" / "report.md"
    json_export_path: Path = PROJECT_ROOT / "data" / "export_items.json"
    log_path: Path = PROJECT_ROOT / "logs" / "extractor.log"

    def summary_enabled(self) -> bool:
        """True when a DeepSeek API key is configured."""
        return bool(self.deepseek_api_key)


def load_settings() -> Settings:
    """Build a :class:`Settings` instance from the environment / .env file."""
    database_path = _env_path(
        "DATABASE_PATH", PROJECT_ROOT / "data" / "facebook_content.db"
    )
    # Keep every local artefact next to the database, so a custom
    # DATABASE_PATH (e.g. a scratch copy) fully isolates a run.
    data_dir = database_path.parent

    return Settings(
        data_dir=data_dir,
        deepseek_api_key=_env_str("DEEPSEEK_API_KEY"),
        deepseek_base_url=_env_str(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"
        ),
        deepseek_model=_env_str("DEEPSEEK_MODEL", "deepseek-v4.1-flash"),
        facebook_delay_seconds=_env_float("FACEBOOK_DELAY_SECONDS", 2.0),
        enable_playwright=_env_bool("ENABLE_PLAYWRIGHT", False),
        playwright_headless=_env_bool("PLAYWRIGHT_HEADLESS", True),
        cookie_file=_env_path("COOKIE_FILE", PROJECT_ROOT / "cookies.txt"),
        whisper_model=_env_str("WHISPER_MODEL", "small"),
        whisper_language=_env_str("WHISPER_LANGUAGE", "auto"),
        max_transcript_chars=_env_int("MAX_TRANSCRIPT_CHARS", 20000),
        auto_summarize=_env_bool("AUTO_SUMMARIZE", False),
        database_path=database_path,
        jsonl_path=data_dir / "extracted.jsonl",
        csv_path=data_dir / "export_items.csv",
        markdown_path=data_dir / "report.md",
        json_export_path=data_dir / "export_items.json",
        request_timeout=_env_int("REQUEST_TIMEOUT", 30),
        max_retries=_env_int("MAX_RETRIES", 3),
        retry_backoff=_env_float("RETRY_BACKOFF", 2.0),
    )


def ensure_directories(settings: Settings) -> None:
    """Create the data/ and logs/ directories when missing."""
    for directory in (settings.data_dir, settings.logs_dir):
        directory.mkdir(parents=True, exist_ok=True)


class _SanitizingFormatter(logging.Formatter):
    """Collapse newlines/control characters in log messages and arguments.

    URLs, captions and error strings from Facebook are untrusted; without this,
    a crafted value could forge extra lines in ``logs/extractor.log`` (log
    injection).  Exception tracebacks are left untouched.
    """

    _CONTROL_RE = re.compile(r"[\r\n\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+")

    def _clean(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._CONTROL_RE.sub(" ", value)
        return value

    def format(self, record: logging.LogRecord) -> str:
        record.msg = self._clean(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: self._clean(value) for key, value in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(self._clean(value) for value in record.args)
            else:
                record.args = self._clean(record.args)
        return super().format(record)


def setup_logging(settings: Settings, level: int = logging.INFO) -> logging.Logger:
    """Configure application logging exactly once.

    Handlers are attached to the root logger so every module logger
    (``extractor.pipeline``, ``database``, ``utils``, ...) is captured.
    """
    root = logging.getLogger()
    if getattr(root, "_facebook_extractor_configured", False):
        return logging.getLogger("facebook_extractor")

    ensure_directories(settings)
    root.setLevel(level)

    formatter = _SanitizingFormatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )

    file_handler = logging.handlers.RotatingFileHandler(
        settings.log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.WARNING)

    root.addHandler(file_handler)
    root.addHandler(console_handler)
    root._facebook_extractor_configured = True  # type: ignore[attr-defined]

    # Keep third-party libraries reasonably quiet in the log file.
    for noisy in ("urllib3", "requests", "httpx", "httpcore", "openai", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return logging.getLogger("facebook_extractor")


def ffmpeg_available() -> bool:
    """True when an ``ffmpeg`` binary is reachable on PATH."""
    return shutil.which("ffmpeg") is not None
