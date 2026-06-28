"""UI-managed Cloudflare tunnel: manager lifecycle, token masking, start/stop endpoints.

A long-running python process stands in for `cloudflared` so these run without the binary.
"""

from __future__ import annotations

import json
import sys

import pytest

from app import tunnel as T

SLEEP = [sys.executable, "-c", "import time; time.sleep(30)"]


async def test_manager_start_stop(monkeypatch):
    monkeypatch.setattr(T, "_quick_argv", lambda b, u, m: SLEEP)
    tm = T.TunnelManager()
    assert tm.running() is False
    await tm.start(metrics="127.0.0.1:2000")  # quick mode (no token)
    assert tm.running() is True
    assert tm.mode == "quick"
    await tm.stop()
    assert tm.running() is False


def test_tunnel_token_is_write_only(client):
    client.put("/v1/admin/remote", json={
        "mode": "cloudflare", "tunnel_mode": "named", "tunnel_token": "secret-token-xyz",
    })
    r = client.get("/v1/admin/remote").json()
    assert r["tunnel_token_set"] is True
    assert "tunnel_token" not in r
    assert "secret-token-xyz" not in json.dumps(r)  # never leaked


def test_named_start_requires_token(client):
    r = client.post("/v1/admin/remote/tunnel/start", json={"mode": "named"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_quick_tunnel_start_stop_via_api(client, monkeypatch):
    monkeypatch.setattr("app.tunnel._quick_argv", lambda b, u, m: SLEEP)
    start = client.post("/v1/admin/remote/tunnel/start", json={"mode": "quick"})
    assert start.status_code == 200 and start.json()["running"] is True
    # enabled persisted so it would auto-start on reboot
    assert client.get("/v1/admin/remote").json()["tunnel_enabled"] is True
    stop = client.post("/v1/admin/remote/tunnel/stop")
    assert stop.json()["running"] is False
    assert client.get("/v1/admin/remote").json()["tunnel_enabled"] is False


def test_token_persists_when_blank_on_update(client):
    client.put("/v1/admin/remote", json={"mode": "cloudflare", "tunnel_token": "keepme"})
    # A later save without a token must not wipe it.
    client.put("/v1/admin/remote", json={"mode": "cloudflare", "hostname": "x.example.com"})
    assert client.get("/v1/admin/remote").json()["tunnel_token_set"] is True


def test_real_cloudflared_present():
    import shutil

    if not shutil.which("cloudflared"):
        pytest.skip("cloudflared not installed (present in the Docker image)")
    assert shutil.which("cloudflared")
