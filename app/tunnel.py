"""In-container managed Cloudflare tunnel — start/stop/status from the admin UI.

Runs `cloudflared` as a child process of the app (no Docker socket needed), in one of two modes:
- **named**: `--token <token>` for a stable, dashboard-provisioned hostname.
- **quick**: `--url http://localhost:<port>` for an instant ephemeral *.trycloudflare.com URL
  (no Cloudflare account/token required).

The token is supplied from the DB (entered in the UI) — never logged. `--metrics` exposes
`/ready` for health.
"""

from __future__ import annotations

import asyncio
import re
from asyncio.subprocess import DEVNULL, PIPE, STDOUT

from .obs import get_logger

log = get_logger("tunnel")

_QUICK_URL = re.compile(r"https://[\w-]+\.trycloudflare\.com")


def _named_argv(binary: str, token: str, metrics: str) -> list[str]:
    return [binary, "tunnel", "--no-autoupdate", "run", "--metrics", metrics, "--token", token]


def _quick_argv(binary: str, local_url: str, metrics: str) -> list[str]:
    return [binary, "tunnel", "--no-autoupdate", "--metrics", metrics, "--url", local_url]


class TunnelManager:
    def __init__(self, binary: str = "cloudflared") -> None:
        self.binary = binary
        self._proc: asyncio.subprocess.Process | None = None
        self._mode: str | None = None
        self._url: str | None = None  # discovered quick-tunnel URL

    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    @property
    def mode(self) -> str | None:
        return self._mode

    @property
    def url(self) -> str | None:
        return self._url

    async def start(
        self,
        *,
        token: str | None = None,
        local_url: str = "http://localhost:8080",
        metrics: str = "127.0.0.1:2000",
    ) -> None:
        await self.stop()
        if token:
            argv = _named_argv(self.binary, token, metrics)
            self._mode = "named"
            capture = False
        else:
            argv = _quick_argv(self.binary, local_url, metrics)
            self._mode = "quick"
            capture = True
        self._url = None
        self._proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=PIPE if capture else DEVNULL,
            stderr=STDOUT if capture else DEVNULL,
        )
        if capture:
            asyncio.create_task(self._scan_url())
        log.info("tunnel_started", mode=self._mode)

    async def _scan_url(self) -> None:
        proc = self._proc
        if not proc or not proc.stdout:
            return
        try:
            async for raw in proc.stdout:
                m = _QUICK_URL.search(raw.decode("utf-8", "replace"))
                if m:
                    self._url = m.group(0)
                    log.info("tunnel_url", url=self._url)
        except Exception:  # pragma: no cover
            pass

    async def stop(self) -> None:
        proc = self._proc
        self._proc = None
        self._mode = None
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), 5)
            except (TimeoutError, ProcessLookupError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            log.info("tunnel_stopped")

    def status(self) -> dict:
        return {"running": self.running(), "mode": self._mode, "url": self._url}
