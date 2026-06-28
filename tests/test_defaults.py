"""Bundled default formats/templates load on startup (create-if-missing)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_defaults_loaded_and_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBE_PRINT_SECRET", "test-secret")
    monkeypatch.setenv("VIBE_PRINT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("VIBE_PRINT_LOAD_DEFAULTS", "1")

    from app.settings import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        c.headers.update({"Authorization": "Bearer test-secret"})
        formats = {f["name"] for f in c.get("/v1/admin/formats").json()}
        templates = {t["name"] for t in c.get("/v1/admin/templates").json()}
        assert "Stripe Payment Receipt" in formats
        assert "Stripe Payment Receipt (PDF)" in templates
        assert "File Routing Sheet" in templates

        # create-if-missing: loading again creates nothing (never clobbers edits)
        from app.defaults import load_defaults

        assert load_defaults(app.state.ctx) == {"formats": 0, "templates": 0}
