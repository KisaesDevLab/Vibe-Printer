"""Test harness: isolated data dir + secret per session, TestClient that runs the worker."""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setenv("VIBE_PRINT_SECRET", "test-secret")
    monkeypatch.setenv("VIBE_PRINT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("VIBE_PRINT_WORKER_POLL_SECONDS", "0.05")

    from app.settings import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        c.headers.update({"Authorization": "Bearer test-secret"})
        yield c


@pytest.fixture()
def auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-secret"}


def wait_for_job(client: TestClient, job_id: str, *, terminal=("done", "failed", "dead",
                 "uncertain", "canceled"), timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/v1/jobs/{job_id}")
        body = r.json()
        if body.get("status") in terminal:
            return body
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish: {client.get(f'/v1/jobs/{job_id}').json()}")
