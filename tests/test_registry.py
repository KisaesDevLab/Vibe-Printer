"""Registry CRUD, optimistic concurrency, YAML round-trip (P24.1)."""

from __future__ import annotations


def _make_virtual(client, name="V1"):
    return client.post(
        "/v1/admin/printers",
        json={"name": name, "params": {"type": "virtual", "columns": 48}},
    )


def test_printer_crud(client):
    r = _make_virtual(client)
    assert r.status_code == 201
    pid = r.json()["id"]
    assert r.json()["version"] == 1

    r = client.get(f"/v1/admin/printers/{pid}")
    assert r.json()["name"] == "V1"

    r = client.put(
        f"/v1/admin/printers/{pid}",
        json={"name": "V1b", "params": {"type": "virtual", "columns": 32}, "version": 1},
    )
    assert r.status_code == 200
    assert r.json()["version"] == 2

    r = client.delete(f"/v1/admin/printers/{pid}")
    assert r.status_code == 204
    assert client.get(f"/v1/admin/printers/{pid}").status_code == 404


def test_optimistic_concurrency_conflict(client):
    pid = _make_virtual(client).json()["id"]
    # stale version -> 409
    r = client.put(
        f"/v1/admin/printers/{pid}",
        json={"name": "x", "params": {"type": "virtual"}, "version": 99},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


def test_unknown_printer_404_envelope(client):
    r = client.get("/v1/printers/999/status")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "unknown_printer"


def test_yaml_round_trip(client):
    _make_virtual(client, "RT")
    client.post("/v1/admin/formats", json={"name": "F", "elements": {"elements": []}})
    exported = client.post("/v1/admin/config/export").text
    assert "RT" in exported
    plan = client.post(
        "/v1/admin/config/import", json={"yaml": exported, "dry_run": True}
    ).json()
    # Re-importing the live config matches existing rows by name -> all updates, no creates.
    assert plan["printers"]["update"] >= 1
    assert plan["formats"]["update"] >= 1
    assert plan["printers"]["create"] == 0


def test_yaml_import_upsert_is_idempotent(client):
    _make_virtual(client, "UP")
    exported = client.post("/v1/admin/config/export").text
    before = len(client.get("/v1/admin/printers").json())
    # Apply the same config twice; upsert-by-name must not duplicate.
    client.post("/v1/admin/config/import", json={"yaml": exported, "dry_run": False})
    client.post("/v1/admin/config/import", json={"yaml": exported, "dry_run": False})
    after = len(client.get("/v1/admin/printers").json())
    assert after == before
