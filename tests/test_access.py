"""Cloudflare Access enforcement gating on /v1/admin/* (P12.5)."""

from __future__ import annotations


def test_admin_open_when_access_not_configured(client):
    # Default: no team domain/aud -> Access is a no-op, shared secret still required.
    assert client.get("/v1/admin/printers").status_code == 200


def test_admin_requires_access_assertion_when_configured(client):
    ctx = client.app.state.ctx
    ctx.settings.access_team_domain = "team.cloudflareaccess.com"
    ctx.settings.access_aud = "aud-tag"
    # Valid shared secret but no Cf-Access-Jwt-Assertion header -> 403.
    r = client.get("/v1/admin/printers")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


def test_non_admin_routes_unaffected_by_access(client):
    ctx = client.app.state.ctx
    ctx.settings.access_team_domain = "team.cloudflareaccess.com"
    ctx.settings.access_aud = "aud-tag"
    # /v1/printers is not under /v1/admin -> Access not enforced there.
    assert client.get("/v1/printers").status_code == 200
