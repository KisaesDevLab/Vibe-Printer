"""Tiny Vibe Print client with idempotency-key usage (P23.6).

    python examples/client.py http://localhost:8080 <secret> <printer_id>
"""

from __future__ import annotations

import sys
import time
import uuid

import httpx


def main() -> None:
    base, secret, printer = sys.argv[1], sys.argv[2], int(sys.argv[3])
    h = {"Authorization": f"Bearer {secret}", "Idempotency-Key": uuid.uuid4().hex}

    doc = {
        "elements": [
            {"type": "text", "value": "{{ data.company }}", "align": "center", "bold": True},
            {"type": "rule"},
            {"type": "text", "value": "TOTAL {{ data.total }}", "align": "right"},
            {"type": "cut"},
        ]
    }
    body = {"printer": printer, "document": doc, "data": {"company": "Acme", "total": "12.00"}}

    r = httpx.post(f"{base}/v1/print", json=body, headers=h)
    r.raise_for_status()
    job_id = r.json()["job_id"]
    print("enqueued", job_id)

    # Final outcome is observed by polling the job, not the enqueue response.
    for _ in range(20):
        s = httpx.get(f"{base}/v1/jobs/{job_id}", headers=h).json()
        print("status:", s["status"], "delivery:", s.get("delivery"))
        if s["status"] in ("done", "failed", "dead", "uncertain", "canceled"):
            break
        time.sleep(0.5)


if __name__ == "__main__":
    main()
