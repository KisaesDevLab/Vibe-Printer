"""LAN printer discovery (P15): bounded scan for open :9100 (ESC/POS) and :631 (IPP).

Scope/rate are bounded — a /24 max, capped concurrency, short per-host timeout — so a scan can't
hammer the network or hang the box. Returns candidates the UI's discover modal can turn into a
printer (prefilled form).
"""

from __future__ import annotations

import asyncio
import ipaddress

from .errors import ApiError

MAX_HOSTS = 256
DEFAULT_PORTS = {9100: "escpos_network", 631: "cups"}


async def _probe(host: str, port: int, timeout: float) -> bool:
    try:
        fut = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(fut, timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except (OSError, TimeoutError):
        return False


async def scan(
    subnet: str,
    *,
    ports: dict[int, str] | None = None,
    timeout: float = 0.5,
    concurrency: int = 64,
) -> list[dict]:
    ports = ports or DEFAULT_PORTS
    try:
        net = ipaddress.ip_network(subnet, strict=False)
    except ValueError as e:
        raise ApiError("validation_error", f"invalid subnet: {e}") from e

    hosts = [str(h) for h in net.hosts()] or [str(net.network_address)]
    if len(hosts) > MAX_HOSTS:
        raise ApiError(
            "validation_error", f"subnet too large ({len(hosts)} hosts, max {MAX_HOSTS})"
        )

    sema = asyncio.Semaphore(concurrency)
    candidates: list[dict] = []

    async def check(host: str, port: int, kind: str) -> None:
        async with sema:
            if await _probe(host, port, timeout):
                candidates.append({"host": host, "port": port, "type": kind})

    await asyncio.gather(
        *(check(h, p, kind) for h in hosts for p, kind in ports.items())
    )
    candidates.sort(key=lambda c: (c["host"], c["port"]))
    return candidates
