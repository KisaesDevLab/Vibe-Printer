"""FastAPI dependencies: context accessor + bearer/rate-limit/body-cap guard."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request

from .auth import check_secret, get_real_ip
from .context import Context
from .errors import ApiError


def get_ctx(request: Request) -> Context:
    return request.app.state.ctx


@dataclass
class AuthInfo:
    real_ip: str
    actor: str


def require_auth(request: Request, ctx: Context = Depends(get_ctx)) -> AuthInfo:
    check_secret(request, ctx.settings.secret)
    real_ip = get_real_ip(request, ctx.settings.trusted_proxies)
    ctx.rate_limiter.check(real_ip)

    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > ctx.settings.max_body_bytes:
        raise ApiError("validation_error", "request body too large", status=413)

    # If Cloudflare Access ran first (admin routes), use the verified identity as the actor.
    actor = getattr(request.state, "access_identity", None) or "secret"
    return AuthInfo(real_ip=real_ip, actor=actor)


def require_access(request: Request, ctx: Context = Depends(get_ctx)) -> str | None:
    """Enforce Cloudflare Access on admin routes when configured (P12.5). No-op otherwise."""
    from .auth import _peer_trusted
    from .remote import resolve_remote

    r = resolve_remote(ctx)
    if not r["access_enabled"]:
        return None
    # Coexist with LAN: enforce the Cloudflare JWT only for requests that arrived via a trusted
    # proxy (the tunnel). Direct-LAN requests still require the shared secret (Bearer), so both
    # access paths work at once. Set access_lan_bypass=false to enforce Access everywhere.
    peer = request.client.host if request.client else ""
    if r["access_lan_bypass"] and not _peer_trusted(peer, ctx.settings.trusted_proxies):
        return None
    token = request.headers.get("Cf-Access-Jwt-Assertion")
    if not token:
        raise ApiError("forbidden", "missing Cloudflare Access assertion", status=403)
    from .access import verify_access_token

    identity = verify_access_token(token, r["access_team_domain"], r["access_aud"])
    request.state.access_identity = identity
    return identity
