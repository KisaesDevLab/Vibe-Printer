"""Cash-drawer kick: configurable pin/timing (ESC/POS + Star) and the open-drawer endpoint."""

from __future__ import annotations

from conftest import wait_for_job

from app.models import Capabilities
from app.render import _drawer_kick, render_escpos, render_star


def test_drawer_kick_bytes_pin2_default():
    b = _drawer_kick({"type": "pulse"})
    assert b[:2] == b"\x1bp"  # ESC p
    assert b[2] == 0  # m=0 -> pin 2


def test_drawer_kick_bytes_pin5_and_timing():
    b = _drawer_kick({"type": "pulse", "pin": 5, "on_ms": 100, "off_ms": 200})
    assert b[:2] == b"\x1bp"
    assert b[2] == 1  # m=1 -> pin 5
    assert b[3] == 50 and b[4] == 100  # 2ms units


def test_render_escpos_emits_drawer_kick():
    out = render_escpos([{"type": "pulse", "pin": 5}], {}, Capabilities(pulse=True), None)
    assert b"\x1bp\x01" in out


def test_render_star_drawer():
    caps = Capabilities(pulse=True, cut=True)
    assert b"\x07" in render_star([{"type": "pulse", "pin": 2}], {}, caps)
    assert b"\x1a" in render_star([{"type": "pulse", "pin": 5}], {}, caps)


# --- endpoint ---
def test_open_drawer_endpoint_virtual(client):
    pid = client.post(
        "/v1/admin/printers", json={"name": "till", "params": {"type": "virtual"}}
    ).json()["id"]
    r = client.post(f"/v1/admin/printers/{pid}/open-drawer", json={"pin": 5})
    assert r.status_code == 200
    assert wait_for_job(client, r.json()["job_id"])["status"] == "done"


def test_open_drawer_rejected_for_cups(client):
    pid = client.post(
        "/v1/admin/printers", json={"name": "C", "params": {"type": "cups", "queue": "q"}}
    ).json()["id"]
    r = client.post(f"/v1/admin/printers/{pid}/open-drawer")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "unsupported_for_printer"
