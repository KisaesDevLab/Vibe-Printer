"""Auth, real-IP resolution, and rate limiting (P12).

- Single shared secret, constant-time compared. Fail-fast on unset secret is enforced at
  startup (app.main), not here.
- Bearer on all /v1/*; /healthz, /readyz, /metrics, and the /admin static UI are open.
- Real client IP trusted from CF-Connecting-IP / X-Forwarded-For ONLY when the socket peer is
  in `trusted_proxies`; otherwise the socket IP (anti-spoofing, P12.3).
- Rate limit + body caps are per real IP (P12.4).
"""

from __future__ import annotations

import ipaddress
import secrets
import time
from collections import defaultdict, deque

from fastapi import Request

from .errors import ApiError


def get_real_ip(request: Request, trusted_proxies: list[str]) -> str:
    peer = request.client.host if request.client else "unknown"
    if _peer_trusted(peer, trusted_proxies):
        cf = request.headers.get("CF-Connecting-IP")
        if cf:
            return cf.strip()
        xff = request.headers.get("X-Forwarded-For")
        if xff:
            return xff.split(",")[0].strip()
    return peer


def _peer_trusted(peer: str, trusted: list[str]) -> bool:
    try:
        ip = ipaddress.ip_address(peer)
    except ValueError:
        return False
    for entry in trusted:
        try:
            if "/" in entry:
                if ip in ipaddress.ip_network(entry, strict=False):
                    return True
            elif ip == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False


def check_secret(request: Request, expected: str) -> None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise ApiError("unauthorized", "missing bearer token")
    token = header[len("Bearer ") :]
    if not secrets.compare_digest(token, expected):
        raise ApiError("unauthorized", "invalid token")


class RateLimiter:
    """Sliding-window limiter keyed by real client IP."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        window = self._hits[key]
        while window and window[0] < now - 60:
            window.popleft()
        if len(window) >= self.per_minute:
            raise ApiError("rate_limited", "rate limit exceeded", status=429)
        window.append(now)
