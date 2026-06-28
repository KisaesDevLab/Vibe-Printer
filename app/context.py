"""Shared singletons assembled at startup and stored on app.state.ctx."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .assets import AssetStore
from .audit import Audit
from .auth import RateLimiter
from .backends import PrinterLocks
from .backends.factory import make_backend
from .db import Database
from .models import Capabilities, PrinterRead
from .queue import JobStore
from .registry import Registry
from .settings import Settings
from .tunnel import TunnelManager

if TYPE_CHECKING:
    from .queue import Worker


@dataclass
class Context:
    settings: Settings
    db: Database
    registry: Registry
    assets: AssetStore
    audit: Audit
    locks: PrinterLocks
    jobs: JobStore
    rate_limiter: RateLimiter
    tunnel: TunnelManager
    worker: Worker | None = None
    started_at: float = 0.0  # monotonic seconds, set at lifespan startup (for uptime)

    def backend_capabilities(self, printer: PrinterRead) -> Capabilities:
        if printer.capabilities is not None:
            return printer.capabilities
        if printer.type == "pool":
            from .pools import aggregate_capabilities

            return aggregate_capabilities(self, printer)
        backend = make_backend(printer, data_dir=self.settings.data_dir)
        caps = backend.capabilities()
        # cache so /v1/printers is cheap
        self.registry.set_capabilities(printer.id, caps.model_dump())
        return caps


def build_context(settings: Settings) -> Context:
    settings.ensure_dirs()
    key = settings.db_encryption_key if settings.encrypt_at_rest else ""
    db = Database(settings.db_path, encryption_key=key)
    db.migrate()
    registry = Registry(db)
    return Context(
        settings=settings,
        db=db,
        registry=registry,
        assets=AssetStore(db, settings),
        audit=Audit(db),
        locks=PrinterLocks(),
        jobs=JobStore(db),
        rate_limiter=RateLimiter(settings.rate_limit_per_minute),
        tunnel=TunnelManager(),
    )
