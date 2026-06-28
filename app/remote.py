"""Remote-access config resolution + tunnel health.

Settings can come from env (Settings) or be overridden at runtime via device config
(``device.config.remote_access``) so the admin UI can edit them. Device config wins when set.
Tunnel creation itself stays in the Cloudflare dashboard — the appliance holds no CF API token
(Decision 12); these values are display/enforcement only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .context import Context

_KEYS = ("mode", "hostname", "access_team_domain", "access_aud", "cloudflared_metrics_url")


def resolve_remote(ctx: Context) -> dict[str, Any]:
    s = ctx.settings
    cfg = ctx.registry.get_device()["config"].get("remote_access", {})
    defaults = {
        "mode": s.remote_access_mode,
        "hostname": s.remote_hostname,
        "access_team_domain": s.access_team_domain,
        "access_aud": s.access_aud,
        "cloudflared_metrics_url": s.cloudflared_metrics_url,
    }
    out: dict[str, Any] = {}
    for k in _KEYS:
        v = cfg.get(k)
        out[k] = v if v not in (None, "") else defaults[k]
    bypass = cfg.get("access_lan_bypass")
    out["access_lan_bypass"] = s.access_lan_bypass if bypass is None else bool(bypass)
    out["access_enabled"] = bool(out["access_team_domain"] and out["access_aud"])
    # Managed tunnel (token is write-only — never returned).
    out["tunnel_mode"] = cfg.get("tunnel_mode", "named")
    out["tunnel_enabled"] = bool(cfg.get("tunnel_enabled", False))
    out["tunnel_token_set"] = bool(cfg.get("tunnel_token"))
    return out


def tunnel_token(ctx: Context) -> str:
    return ctx.registry.get_device()["config"].get("remote_access", {}).get("tunnel_token", "")


async def tunnel_status(metrics_url: str) -> str:
    """Poll cloudflared's /ready (P16.4). Returns ready | not_ready | unreachable | unknown."""
    if not metrics_url:
        return "unknown"
    import httpx

    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(metrics_url.rstrip("/") + "/ready")
        return "ready" if r.status_code == 200 else "not_ready"
    except Exception:
        return "unreachable"
