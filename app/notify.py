"""Signed outbound webhooks (P14.4 amendment).

Every outbound POST carries an HMAC-SHA256 signature over ``"{timestamp}.{body}"`` in the
``X-Vibe-Signature: t=<ts>,v1=<hex>`` header, plus ``X-Vibe-Timestamp``. Receivers recompute
the MAC with the shared secret and reject stale timestamps. Payloads are PII-free by construction
(ids + metadata only — never job content).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx

from .obs import get_logger

log = get_logger("notify")


def sign(secret: str, timestamp: str, body: bytes) -> str:
    msg = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def verify(secret: str, timestamp: str, body: bytes, signature: str, *, max_age: int = 300) -> bool:
    if abs(int(time.time()) - int(timestamp)) > max_age:
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), signature)


async def post_signed(url: str, secret: str, payload: dict[str, Any]) -> bool:
    if not url:
        return False
    ts = str(int(time.time()))
    body = json.dumps(payload, sort_keys=True).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Vibe-Timestamp": ts,
        "X-Vibe-Signature": f"t={ts},v1={sign(secret, ts, body)}",
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, content=body, headers=headers)
        return resp.status_code < 400
    except Exception as e:  # pragma: no cover - network best-effort
        log.warning("webhook_failed", url=url, error=str(e))
        return False
