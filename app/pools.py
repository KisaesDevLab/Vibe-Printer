"""Printer pools / failover (deferred plan item, now built).

A ``pool`` printer routes to one of its ESC/POS-family members:
- ``failover``     — first reachable member, in listed order.
- ``round_robin``  — rotate the starting point each dispatch, then fall through to reachable.

Capabilities are the safe intersection of members (so any chosen member can render the job).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from .backends.base import PrinterUnreachable
from .backends.factory import make_backend
from .errors import ApiError
from .models import Capabilities, PrinterRead

if TYPE_CHECKING:
    from .context import Context


def _members(ctx: Context, printer: PrinterRead) -> list[PrinterRead]:
    ids = printer.params.get("members", [])
    members: list[PrinterRead] = []
    for mid in ids:
        try:
            m = ctx.registry.get_printer(int(mid))
        except ApiError:
            continue
        if m.type == "pool":
            raise ApiError("validation_error", "pools cannot contain pools")
        members.append(m)
    return members


def aggregate_capabilities(ctx: Context, printer: PrinterRead) -> Capabilities:
    members = _members(ctx, printer)
    if not members:
        return Capabilities()
    caps = [ctx.backend_capabilities(m) for m in members]
    barcode = set(caps[0].barcode)
    for c in caps[1:]:
        barcode &= set(c.barcode)
    return Capabilities(
        cut=all(c.cut for c in caps),
        qr=all(c.qr for c in caps),
        barcode=sorted(barcode),
        raster=all(c.raster for c in caps),
        pulse=all(c.pulse for c in caps),
        pdf=all(c.pdf for c in caps),
        columns=min((c.columns for c in caps if c.columns), default=None),
        paper_width_dots=min(
            (c.paper_width_dots for c in caps if c.paper_width_dots), default=None
        ),
    )


async def pool_status(ctx: Context, printer: PrinterRead) -> dict:
    members = _members(ctx, printer)
    statuses = []
    for m in members:
        backend = make_backend(m, data_dir=ctx.settings.data_dir)
        try:
            st = await asyncio.wait_for(asyncio.to_thread(backend.status), 3.0)
        except Exception as e:  # pragma: no cover
            st = {"reachable": False, "errors": [str(e)]}
        statuses.append({"id": m.id, "name": m.name, **st})
    return {
        "reachable": any(s.get("reachable") for s in statuses),
        "state": "pool",
        "members": statuses,
    }


async def resolve_target(
    ctx: Context, printer: PrinterRead, rr_state: dict[int, int]
) -> PrinterRead:
    """Pick a concrete reachable member; raise PrinterUnreachable (retryable) if none are up."""
    if printer.type != "pool":
        return printer
    members = _members(ctx, printer)
    if not members:
        raise PrinterUnreachable("pool has no members")
    order = list(members)
    if printer.params.get("strategy") == "round_robin":
        idx = rr_state.get(printer.id, 0) % len(members)
        order = members[idx:] + members[:idx]
        rr_state[printer.id] = (idx + 1) % len(members)
    for m in order:
        backend = make_backend(m, data_dir=ctx.settings.data_dir)
        try:
            st = await asyncio.wait_for(asyncio.to_thread(backend.status), 3.0)
            if st.get("reachable"):
                return m
        except Exception:
            continue
    raise PrinterUnreachable("no pool member is reachable")
