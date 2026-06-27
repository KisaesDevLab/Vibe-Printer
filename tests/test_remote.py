"""Remote-access config (UI-editable, device-config backed) + Access enforcement from config."""

from __future__ import annotations


def test_remote_defaults(client):
    r = client.get("/v1/admin/remote").json()
    assert r["mode"] == "lan"
    assert r["access_enabled"] is False
    assert r["tunnel"] == "unknown"


def test_put_remote_persists(client):
    client.put("/v1/admin/remote", json={
        "mode": "cloudflare",
        "hostname": "print.example.com",
        "cloudflared_metrics_url": "",
    })
    r = client.get("/v1/admin/remote").json()
    assert r["mode"] == "cloudflare"
    assert r["hostname"] == "print.example.com"


def test_enabling_access_via_config_enforces_jwt(client):
    # Enabling Access through the UI config must make admin routes require the assertion.
    resp = client.put("/v1/admin/remote", json={
        "mode": "cloudflare",
        "access_team_domain": "team.cloudflareaccess.com",
        "access_aud": "aud-tag",
    })
    assert resp.status_code == 200  # the PUT itself ran before enforcement flipped on

    # Now any admin call without the Cloudflare assertion is rejected.
    blocked = client.get("/v1/admin/remote")
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "forbidden"

    # Non-admin routes are unaffected.
    assert client.get("/v1/printers").status_code == 200
