"""Data classification and policy helpers.

The router deliberately keeps policy evaluation deterministic and inspectable. It does
not ask an LLM whether a request is safe to send to another LLM.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

from .config import DATA_CLASSES


_SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "restricted",
        re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}\b"),
        "api_credential",
    ),
    (
        "restricted",
        re.compile(
            r"(?i)\b(?:password|passwd|secret|api[_ -]?key|access[_ -]?token)\s*[:=]\s*\S+"
        ),
        "credential_assignment",
    ),
    (
        "restricted",
        re.compile(r"(?<!\d)\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}(?!\d)"),
        "payment_card_like",
    ),
    (
        "confidential",
        re.compile(r"(?i)\b(?:confidential|strictly confidential)\b|(?:社外秘|極秘|機密)"),
        "confidential_marker",
    ),
    (
        "internal",
        re.compile(r"(?i)\b(?:internal only|do not distribute)\b|(?:社内限り|部外秘)"),
        "internal_marker",
    ),
)


def class_rank(data_class: str) -> int:
    try:
        return DATA_CLASSES.index(data_class)
    except ValueError:
        return 0


def max_class(first: str, second: str) -> str:
    return first if class_rank(first) >= class_rank(second) else second


def message_text(messages: Iterable[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text") or item.get("input_text")
                    if isinstance(text, str):
                        chunks.append(text)
        elif content is not None:
            chunks.append(json.dumps(content, ensure_ascii=False, sort_keys=True))
    return "\n".join(chunks)


def detect_data_class(text: str) -> tuple[str, tuple[str, ...]]:
    detected = "public"
    reasons: list[str] = []
    for data_class, pattern, reason in _SENSITIVE_PATTERNS:
        if pattern.search(text):
            detected = max_class(detected, data_class)
            reasons.append(reason)
    return detected, tuple(sorted(set(reasons)))


def detect_capabilities(body: dict[str, Any], messages: list[dict[str, Any]]) -> tuple[str, ...]:
    required = {"chat"}
    if body.get("tools") or body.get("functions"):
        required.add("tools")
    response_format = body.get("response_format")
    if isinstance(response_format, dict) and response_format.get("type") in {
        "json_object",
        "json_schema",
    }:
        required.add("json")
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") in {"image", "image_url", "input_image"}:
                    required.add("vision")
                if item.get("type") in {"input_audio", "audio"}:
                    required.add("audio")
    return tuple(sorted(required))


def estimate_tokens(value: Any) -> int:
    """Provider-neutral conservative token estimate for planning only."""

    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    ascii_chars = sum(1 for char in serialized if ord(char) < 128)
    non_ascii_chars = len(serialized) - ascii_chars
    return max(1, (ascii_chars + 3) // 4 + (non_ascii_chars + 1) // 2)
