"""VirtualBackend — writes payloads to disk, no hardware. Powers `make dev` and tests (P3.3)."""

from __future__ import annotations

from pathlib import Path

from ..models import Capabilities
from .base import PrintPayload, SendResult


class VirtualBackend:
    type = "virtual"

    def __init__(self, printer_id: int, params: dict, out_dir: Path) -> None:
        self.printer_id = printer_id
        self.params = params
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def capabilities(self) -> Capabilities:
        return Capabilities(
            cut=True,
            qr=True,
            barcode=["CODE128", "EAN13", "CODE39"],
            raster=True,
            pulse=True,
            pdf=True,
            columns=self.params.get("columns", 48),
            paper_width_dots=self.params.get("paper_width_dots", 576),
        )

    def status(self) -> dict:
        return {"reachable": True, "state": "idle", "errors": []}

    def send(self, payload: PrintPayload) -> SendResult:
        ext = "pdf" if payload.kind == "pdf" else "bin"
        path = self.out_dir / f"printer-{self.printer_id}.{ext}"
        path.write_bytes(payload.data)
        # Virtual delivery is fully observable -> completed.
        return SendResult(bytes_sent=len(payload.data), completed=True)

    def close(self) -> None:  # nothing to release
        return
