"""Thin client for DeepSeek V4.1 Flash via NVIDIA NIM (any OpenAI-compatible
chat completions API).

Handles the quirks of reasoning models such as ``deepseek-ai/deepseek-v4.1-flash``:
they emit ``reasoning_content`` first and only then the JSON answer, so the
token budget must cover both.  When the model returns an empty ``content``
(typical when reasoning consumed the whole budget) the call is retried with a
doubled budget.  Transient API errors (rate limits, 5xx, timeouts) are retried
with exponential backoff.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import time
from typing import Any

from config import Settings

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 4
_DEFAULT_MAX_TOKENS = 8192
_MAX_TOKEN_CEILING = 32768

_RETRYABLE_MARKERS = (
    "429",
    "rate limit",
    "too many requests",
    "timed out",
    "timeout",
    "502",
    "503",
    "504",
    "overloaded",
    "temporarily unavailable",
    "server error",
)

# Endpoint capability cache: None = not tried yet, True = json_object works,
# False = json_object produces empty content (leave the answer to the prompt).
_json_mode_state: bool | None = None


class DeepSeekError(RuntimeError):
    """Any failure while talking to the DeepSeek endpoint."""


class DeepSeekNotConfigured(DeepSeekError):
    """Raised when no API key is configured."""


def is_configured(settings: Settings) -> bool:
    return bool(settings.deepseek_api_key)


def _strip_code_fences(text: str) -> str:
    text = (text or "").strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL | re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    return text


def parse_json_response(text: str) -> dict[str, Any]:
    """Parse model output into a dict, tolerating fences and surrounding prose."""
    cleaned = _strip_code_fences(text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise DeepSeekError(
                f"model did not return JSON; first 300 chars: {cleaned[:300]!r}"
            ) from exc
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise DeepSeekError(f"could not parse model JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise DeepSeekError("model returned JSON that is not an object")
    return data


def _is_retryable(message: str) -> bool:
    lowered = (message or "").lower()
    return any(marker in lowered for marker in _RETRYABLE_MARKERS)


def _build_client(settings: Settings) -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - requirements include openai
        raise DeepSeekError(
            "the `openai` package is required for summarisation; "
            "run `pip install openai`"
        ) from exc
    return OpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        timeout=300.0,
    )


def _create_completion(
    client: Any,
    settings: Settings,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    use_json_format: bool = True,
) -> Any:
    """Create a chat completion.

    ``use_json_format`` requests strict JSON output; when the endpoint rejects
    that parameter the call is retried without it.
    """
    request_kwargs: dict[str, Any] = {
        "model": settings.deepseek_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if not use_json_format:
        return client.chat.completions.create(**request_kwargs)
    try:
        return client.chat.completions.create(
            response_format={"type": "json_object"}, **request_kwargs
        )
    except Exception as exc:  # noqa: BLE001 - endpoint may not support json_object
        if _is_retryable(str(exc)):
            raise
        global _json_mode_state
        _json_mode_state = False
        logger.info("json_object response_format unsupported, retrying plain: %s", exc)
        return client.chat.completions.create(**request_kwargs)


def _extract_message(response: Any) -> Any:
    try:
        return response.choices[0].message
    except (AttributeError, IndexError) as exc:
        raise DeepSeekError(f"unexpected DeepSeek response shape: {exc}") from exc


def chat_json(
    settings: Settings,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
) -> dict[str, Any]:
    """Call the chat completions endpoint and parse a JSON object reply."""
    global _json_mode_state
    if not is_configured(settings):
        raise DeepSeekNotConfigured(
            "DEEPSEEK_API_KEY is not set; add it to .env to enable summarisation"
        )

    client = _build_client(settings)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    budget = max(1024, int(max_tokens))
    use_json_format = _json_mode_state is not False
    last_error: str | None = None

    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = _create_completion(
                client, settings, messages, temperature, budget, use_json_format
            )
        except Exception as exc:  # noqa: BLE001 - normalize all client errors
            message = f"{type(exc).__name__}: {exc}"
            last_error = message
            lowered = message.lower()
            # Some hosted endpoints cap max_tokens (the documented sibling caps
            # at 16,384): recover by halving the budget instead of failing.
            if (
                ("max_tokens" in lowered or "maximum context" in lowered or "token limit" in lowered)
                and budget > 2048
                and attempt < _MAX_ATTEMPTS - 1
            ):
                budget = max(2048, budget // 2)
                logger.warning(
                    "endpoint rejected the token budget (%s) - retrying with max_tokens=%d",
                    message[:160],
                    budget,
                )
                continue
            if _is_retryable(message) and attempt < _MAX_ATTEMPTS - 1:
                delay = 5.0 * (3 ** attempt)  # 5s, 15s, 45s
                logger.warning(
                    "retryable DeepSeek/NIM error (%s) - retrying in %.0fs",
                    message[:160],
                    delay,
                )
                time.sleep(delay)
                continue
            raise DeepSeekError(f"DeepSeek request failed: {message}") from exc

        message_obj = _extract_message(response)
        content = (getattr(message_obj, "content", None) or "").strip()
        if content:
            if use_json_format:
                _json_mode_state = True
            return parse_json_response(content)

        # Empty content. Two common causes, handled in this order:
        #  1. the endpoint's json_object mode suppresses reasoning-model
        #     output -> retry without response_format;
        #  2. reasoning consumed the token budget (finish_reason=length)
        #     -> retry with a doubled budget.
        finish_reason = None
        with contextlib.suppress(AttributeError, IndexError):
            finish_reason = response.choices[0].finish_reason
        reasoning = getattr(message_obj, "reasoning_content", None) or ""
        logger.warning(
            "model returned empty content (finish_reason=%s, reasoning=%d chars, "
            "max_tokens=%d, json_format=%s)",
            finish_reason,
            len(reasoning),
            budget,
            use_json_format,
        )

        if use_json_format and attempt < _MAX_ATTEMPTS - 1:
            _json_mode_state = False
            use_json_format = False
            logger.info(
                "retrying without response_format=json_object "
                "(reasoning models often return empty content in json mode)"
            )
            continue

        if budget < _MAX_TOKEN_CEILING and attempt < _MAX_ATTEMPTS - 1:
            budget = min(budget * 2, _MAX_TOKEN_CEILING)
            logger.info("retrying with a larger token budget: max_tokens=%d", budget)
            continue

        raise DeepSeekError(
            "model returned no content after "
            f"{_MAX_ATTEMPTS} attempts (finish_reason={finish_reason}); "
            "the response budget was likely consumed by reasoning tokens"
        )

    raise DeepSeekError(f"DeepSeek request failed: {last_error}")
