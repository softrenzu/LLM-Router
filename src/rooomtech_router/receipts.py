"""Tamper-evident route receipts that contain no prompt or model output text."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def sign_receipt(receipt: dict[str, Any], secret: str | None) -> tuple[str, str | None]:
    digest = sha256_json(receipt)
    if not secret:
        return digest, None
    signature = hmac.new(secret.encode("utf-8"), canonical_json(receipt), hashlib.sha256)
    return digest, f"sha256={signature.hexdigest()}"


def verify_receipt(receipt: dict[str, Any], secret: str, signature: str) -> bool:
    _, expected = sign_receipt(receipt, secret)
    return bool(expected and hmac.compare_digest(expected, signature))

