"""Cloudflare Access (Zero Trust) JWT verification (P12.5).

When a team domain + AUD tag are configured, requests to /v1/admin/* must carry a valid
``Cf-Access-Jwt-Assertion`` (injected by Cloudflare for both interactive SSO and service tokens).
We verify the RS256 signature against the team's JWKS, check ``aud`` and issuer, and return the
caller identity (email for users, client-id for service tokens) for audit.

PyJWT + cryptography are only needed when this is enabled (the `access` extra).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from .errors import ApiError


@lru_cache(maxsize=8)
def _jwks_client(team_domain: str) -> Any:
    import jwt  # lazy: only when Access is enabled

    certs_url = f"https://{team_domain}/cdn-cgi/access/certs"
    return jwt.PyJWKClient(certs_url)


def verify_access_token(token: str, team_domain: str, aud: str) -> str:
    try:
        import jwt
    except Exception as e:  # pragma: no cover
        raise ApiError(
            "internal_error",
            "Cloudflare Access is enabled but PyJWT is not installed (install the 'access' extra).",
        ) from e

    issuer = f"https://{team_domain}"
    try:
        signing_key = _jwks_client(team_domain).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=aud,
            issuer=issuer,
        )
    except Exception as e:
        raise ApiError("forbidden", f"invalid Cloudflare Access token: {e}", status=403) from e

    return claims.get("email") or claims.get("common_name") or claims.get("sub") or "access-user"
