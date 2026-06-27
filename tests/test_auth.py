"""Auth + real-IP spoofing + fail-fast-on-unset-secret (P12 / P24.3)."""

from __future__ import annotations

import pytest


def test_missing_token_401(client):
    r = client.get("/v1/printers", headers={"Authorization": ""})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"


def test_wrong_token_401(client):
    r = client.get("/v1/printers", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_health_open(client):
    assert client.get("/healthz", headers={"Authorization": ""}).status_code == 200
    assert client.get("/readyz", headers={"Authorization": ""}).status_code in (200, 503)


def test_spoofed_forwarded_ip_ignored(client):
    # Peer is testclient (not a trusted proxy) -> XFF must be ignored, request still authorized.
    r = client.get("/v1/printers", headers={"X-Forwarded-For": "1.2.3.4"})
    assert r.status_code == 200


def test_unset_secret_refuses_boot(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBE_PRINT_SECRET", "")
    monkeypatch.setenv("VIBE_PRINT_DATA_DIR", str(tmp_path / "d"))
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.settings import get_settings

    get_settings.cache_clear()
    app = create_app()
    with pytest.raises(RuntimeError):
        with TestClient(app):
            pass
