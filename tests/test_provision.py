"""Version + first-boot provisioning (P27)."""

from __future__ import annotations


def test_version_endpoint(client):
    r = client.get("/v1/version")
    assert r.status_code == 200
    body = r.json()
    assert body["app"]
    # schema = latest applied migration file name
    assert body["schema"] and body["schema"].endswith(".sql")


def test_provision_flow(client):
    status = client.get("/v1/admin/provision/status").json()
    assert status["provisioned"] is False

    r = client.post(
        "/v1/admin/provision",
        json={"name": "shop-01", "timezone": "America/New_York"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "shop-01"

    status = client.get("/v1/admin/provision/status").json()
    assert status["provisioned"] is True
