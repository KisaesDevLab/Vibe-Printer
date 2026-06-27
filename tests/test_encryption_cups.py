"""SQLCipher-at-rest wiring + CUPS queue provisioning (deferred items, now built).

SQLCipher round-trip only runs where a driver is installed (Linux image / CI with the
`encrypt` extra). On Windows the driver is unavailable, so we assert the fail-loud path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.db import Database

_HAS_SQLCIPHER = (
    importlib.util.find_spec("sqlcipher3") is not None
    or importlib.util.find_spec("pysqlcipher3") is not None
)


def test_encryption_requested_without_driver_fails_loud(tmp_path):
    if _HAS_SQLCIPHER:
        pytest.skip("driver present; covered by the round-trip test")
    with pytest.raises(RuntimeError):
        Database(tmp_path / "enc.sqlite", encryption_key="topsecret")


@pytest.mark.skipif(not _HAS_SQLCIPHER, reason="SQLCipher driver not installed")
def test_encrypted_db_round_trip(tmp_path):
    path = tmp_path / "enc.sqlite"
    db = Database(path, encryption_key="topsecret")
    db.migrate()
    db.execute("INSERT INTO formats(name) VALUES ('secret-format')")
    db.close()

    # Plaintext bytes must not contain our data.
    raw = Path(path).read_bytes()
    assert b"secret-format" not in raw

    # Wrong key cannot open it.
    with pytest.raises(Exception):  # noqa: B017 - any driver error is acceptable here
        bad = Database(path, encryption_key="wrong")
        bad.query("SELECT * FROM formats")


def test_provision_queue_requires_cups_printer(client):
    pid = client.post(
        "/v1/admin/printers", json={"name": "V", "params": {"type": "virtual"}}
    ).json()["id"]
    r = client.post(f"/v1/admin/printers/{pid}/provision-queue", json={"device_uri": "ipp://x"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "unsupported_for_printer"


def test_provision_queue_validates_device_uri(client):
    cid = client.post(
        "/v1/admin/printers", json={"name": "C", "params": {"type": "cups", "queue": "q"}}
    ).json()["id"]
    r = client.post(f"/v1/admin/printers/{cid}/provision-queue", json={})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
