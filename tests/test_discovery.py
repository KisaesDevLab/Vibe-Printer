"""LAN discovery scan (P15)."""

from __future__ import annotations

import asyncio

import pytest

from app.discovery import scan
from app.errors import ApiError


async def _scan_against_open_port():
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        return await scan("127.0.0.1/32", ports={port: "escpos_network"}, timeout=0.5), port
    finally:
        server.close()
        await server.wait_closed()


def test_scan_finds_open_port():
    candidates, port = asyncio.run(_scan_against_open_port())
    assert any(c["port"] == port and c["host"] == "127.0.0.1" for c in candidates)


def test_scan_rejects_oversized_subnet():
    with pytest.raises(ApiError):
        asyncio.run(scan("10.0.0.0/16"))


def test_scan_invalid_subnet():
    with pytest.raises(ApiError):
        asyncio.run(scan("not-a-subnet"))
