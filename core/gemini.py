"""Gemini client helpers: singleton, model cascade, error classification (ported from Arbitale)."""

from __future__ import annotations

import logging
import os
from typing import Literal

log = logging.getLogger("polytale.gemini")

_client = None

# Read timeout for every Gemini HTTP call. A hung generate_content would
# otherwise pin the per-session turn lock forever.
DEFAULT_TIMEOUT_SECONDS = 120.0


def request_timeout_ms() -> int:
    """Per-request Gemini timeout in milliseconds (env: GEMINI_TIMEOUT_SECONDS)."""
    raw = os.environ.get("GEMINI_TIMEOUT_SECONDS", "")
    try:
        seconds = float(raw) if raw.strip() else DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        seconds = DEFAULT_TIMEOUT_SECONDS
    return int(max(1.0, seconds) * 1000)


def get_client():
    """Return a module-level singleton Gemini client (created on first call)."""
    global _client
    if _client is None:
        from google import genai
        from google.genai import types

        _client = genai.Client(
            api_key=os.environ["GEMINI_API_KEY"],
            http_options=types.HttpOptions(timeout=request_timeout_ms()),
        )
    return _client


def model_cascade() -> list[str]:
    """Primary Gemini model plus overflow models (read live from env)."""
    # Quality first: full flash narrates committed turns; lite tiers are
    # overflow only. Override via GEMINI_MODEL / GEMINI_MODEL_FALLBACKS.
    primary = os.environ.get("GEMINI_MODEL", "gemini-3.7-flash")
    extras = os.environ.get(
        "GEMINI_MODEL_FALLBACKS",
        "gemini-flash-latest,gemini-3.1-flash-lite,gemini-3.5-flash-lite",
    )
    ordered: list[str] = []
    for item in (primary, *extras.split(",")):
        name = item.strip()
        if name and name not in ordered:
            ordered.append(name)
    return ordered


def is_credits_exhausted(exc: BaseException) -> bool:
    """True only for unambiguous empty-balance refusals.

    Every Gemini 429 carries RESOURCE_EXHAUSTED / "quota exceeded", so those
    markers must NOT classify as credits — a routine rate limit has to stay
    transient so the model cascade continues instead of surfacing a fatal
    "top up billing" message to the player.
    """
    detail = str(exc).casefold()
    return any(
        token in detail
        for token in (
            "credits are depleted",
            "credit is empty",
            "insufficient credit",
            "insufficient_quota",
            "limit: 0",
        )
    )


def friendly_api_error(exc: BaseException) -> str:
    """Player-facing message — never dump raw provider payloads."""
    if is_credits_exhausted(exc):
        return "Ran out of AI tokens/credits. Top up Gemini billing and try again."
    return "Something went wrong on the story side. Nothing changed. Try again."


def error_kind(exc: Exception) -> Literal["transient", "missing", "credits", "other"]:
    if is_credits_exhausted(exc):
        return "credits"
    detail = str(exc).casefold()
    if any(
        token in detail
        for token in (
            "503",
            "unavailable",
            "high demand",
            "429",
            "overloaded",
            "try again later",
            "resource_exhausted",
            "quota exceeded",
            "exceeded your current quota",
            "rate limit",
        )
    ):
        return "transient"
    if any(
        token in detail for token in ("404", "not_found", "no longer available", "is not found")
    ):
        return "missing"
    return "other"


def thinking_config(types_module):
    level = os.environ.get("GEMINI_THINKING_LEVEL", "low").strip().lower()
    if level in {"", "off", "none"}:
        level = "minimal"
    try:
        return types_module.ThinkingConfig(thinking_level=level)
    except Exception:
        return types_module.ThinkingConfig(thinking_budget=0)


def call_with_cascade(
    prompt: str,
    config,
    *,
    response_parser=None,
    models: list[str] | None = None,
    max_attempts: int = 2,
    sleep_fn=None,
):
    """Call Gemini with model cascade, retry on transient errors, and structured parsing.

    Args:
        prompt: The prompt string.
        config: GenerateContentConfig to pass.
        response_parser: Callable(response) -> parsed result. If None, returns raw text.
        models: Override model list (defaults to model_cascade()).
        max_attempts: Retry count per model.
        sleep_fn: Callable(seconds) for backoff. Defaults to time.sleep.

    Returns:
        Parsed result from response_parser, or raw text string if no parser.

    Raises:
        RuntimeError with aggregated error details if all models fail.
    """
    import time as _time

    if sleep_fn is None:
        sleep_fn = _time.sleep

    client = get_client()

    model_list = models or model_cascade()
    errors: list[str] = []
    for model_name in model_list:
        for attempt in range(max_attempts):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=config,
                )
                text = (response.text or "").strip()
                if not text:
                    raise RuntimeError("Empty Gemini response")
                if response_parser is not None:
                    return response_parser(text)
                return text
            except Exception as exc:
                kind = error_kind(exc)
                errors.append(f"{model_name}: {exc}")
                if kind == "missing":
                    break
                if kind == "transient" and attempt == 0:
                    sleep_fn(0.8)
                    continue
                break
    raise RuntimeError("Gemini call failed: " + " | ".join(errors[-6:]))
