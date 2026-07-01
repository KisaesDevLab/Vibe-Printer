"""CUPS/IPP backend via pycups. Submits a PDF and polls job-state to true completion (P6.2).

CUPS has its own spooler, so the worker does NOT serialize behind the per-printer lock for
this backend. Lazy import keeps pycups optional for local dev/test.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any

from ..models import Capabilities
from .base import BackendError, PrinterUnreachable, PrintPayload, SendResult


class CupsBackend:
    type = "cups"

    def __init__(self, printer_id: int, params: dict) -> None:
        self.printer_id = printer_id
        self.queue = params["queue"]
        self.media = params.get("media")
        self.params = params

    def _conn(self) -> Any:
        try:
            import cups
        except Exception as e:  # pragma: no cover
            raise BackendError(
                "CUPS support unavailable: install the 'cups' extra (pycups) and run cupsd."
            ) from e
        try:
            return cups.Connection()
        except Exception as e:
            raise PrinterUnreachable(f"cannot connect to cupsd: {e}") from e

    def provision_queue(self, device_uri: str, *, make_model: str = "everywhere",
                        info: str | None = None) -> None:
        """Create/configure the CUPS queue from the registry (P6.1). Driverless by default."""
        conn = self._conn()
        try:
            conn.addPrinter(
                self.queue,
                device=device_uri,
                ppdname=make_model,  # 'everywhere' = IPP Everywhere driverless
                info=info or self.queue,
            )
            conn.enablePrinter(self.queue)
            conn.acceptJobs(self.queue)
        except Exception as e:
            raise BackendError(f"failed to provision CUPS queue {self.queue}: {e}") from e

    def capabilities(self) -> Capabilities:
        return Capabilities(
            cut=False, qr=False, barcode=[], raster=True, pulse=False, pdf=True,
            document_formats=["pdf", "postscript", "pcl"],
        )

    def status(self) -> dict:
        try:
            conn = self._conn()
            printers = conn.getPrinters()
            info = printers.get(self.queue)
            if info is None:
                return {"reachable": False, "state": "unknown", "errors": ["queue not found"]}
            return {
                "reachable": True,
                "state": info.get("printer-state-message", "idle"),
                "errors": info.get("printer-state-reasons", []),
            }
        except (PrinterUnreachable, BackendError) as e:
            return {"reachable": False, "state": "offline", "errors": [str(e)]}

    _EXT = {"pdf": ".pdf", "postscript": ".ps", "pcl": ".pcl"}

    def send(self, payload: PrintPayload) -> SendResult:
        if payload.kind not in self._EXT:
            raise BackendError("CUPS backend requires a pdf/postscript/pcl payload")
        conn = self._conn()
        options = {}
        if self.media:
            options["media"] = self.media
        if payload.options.get("media"):
            options["media"] = payload.options["media"]
        copies = int(payload.options.get("copies", 1))
        if copies > 1:
            options["copies"] = str(copies)
        if self.params.get("output_bin"):
            options["output-bin"] = str(self.params["output_bin"])
        if self.params.get("input_tray"):
            options["media-source"] = str(self.params["input_tray"])
        # PCL is device-native: pass it through CUPS unfiltered. PDF/PostScript are auto-filtered
        # (and converted for IPP-Everywhere printers).
        if payload.kind == "pcl":
            options["document-format"] = "application/vnd.cups-raw"
        with tempfile.NamedTemporaryFile(suffix=self._EXT[payload.kind], delete=False) as f:
            f.write(payload.data)
            tmp = Path(f.name)
        try:
            job_id = conn.printFile(self.queue, str(tmp), "vibe-print", options)
            completed = self._poll(conn, job_id)
        finally:
            tmp.unlink(missing_ok=True)
        return SendResult(bytes_sent=len(payload.data), completed=completed)

    def _poll(self, conn: Any, job_id: int, timeout: float = 60.0) -> bool:
        import cups

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            attrs = conn.getJobAttributes(job_id)
            state = attrs.get("job-state")
            if state in (cups.IPP_JOB_COMPLETED,):
                return True
            if state in (cups.IPP_JOB_CANCELED, cups.IPP_JOB_ABORTED):
                raise BackendError(f"CUPS job {job_id} failed: state {state}")
            time.sleep(0.5)
        return False  # still processing — report as sent, not confirmed

    def close(self) -> None:
        return
