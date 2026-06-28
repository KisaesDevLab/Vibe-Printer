"""Application settings (Pydantic BaseSettings).

The shared secret is intentionally NOT given a default — the service must refuse to
start when it is unset/empty (Decision 6 / P1.3 / P12.1).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VIBE_PRINT_", env_file=".env", extra="ignore")

    # --- Auth ---
    secret: str = Field(default="", description="Shared bearer secret. Empty => refuse to boot.")
    trusted_proxies: list[str] = Field(
        default_factory=list,
        description="Peer IPs/CIDRs whose CF-Connecting-IP / X-Forwarded-For headers we trust.",
    )

    # --- Storage ---
    data_dir: Path = Field(default=Path("./data"))

    # --- Queue / delivery ---
    max_attempts: int = 5
    retry_base_seconds: float = 2.0
    retry_max_seconds: float = 300.0
    queue_max_depth: int = 1000
    per_printer_max_depth: int = 100
    worker_poll_seconds: float = 0.5
    shutdown_drain_seconds: float = 20.0

    # --- Limits ---
    rate_limit_per_minute: int = 120
    max_body_bytes: int = 5 * 1024 * 1024
    max_asset_bytes: int = 10 * 1024 * 1024

    # --- Retention (days; pruned periodically) ---
    job_retention_days: int = 30
    audit_retention_days: int = 365
    idempotency_ttl_hours: int = 24

    # --- Rendering ---
    render_timeout_seconds: float = 15.0
    weasyprint_max_concurrency: int = 2

    # --- Misc ---
    timezone: str = "UTC"
    enable_metrics: bool = True
    image_digest: str = "dev"  # set by the deploy/update flow for /v1/version (P27.4)
    # seed bundled default formats/templates on startup (create-if-missing)
    load_defaults: bool = True

    # --- Compliance (P29) ---
    store_payloads: bool = True  # False => keep only a content hash + metadata after print
    encrypt_at_rest: bool = False  # opt-in SQLCipher if pysqlcipher3 is installed
    db_encryption_key: str = ""
    retention_sweep_minutes: int = 60

    # --- Outbound webhooks (signed) — P14.4 / P28.3 ---
    webhook_url: str = ""  # POSTed (HMAC-signed) on dead/uncertain jobs
    webhook_secret: str = ""

    # --- Fleet / heartbeat (P28) ---
    heartbeat_url: str = ""  # opt-in phone-home; never includes payloads
    heartbeat_secret: str = ""
    heartbeat_minutes: int = 15
    printer_offline_alert_minutes: int = 10

    # --- Remote access (P12.5 / P16) ---
    access_team_domain: str = ""  # e.g. myteam.cloudflareaccess.com — enables JWT enforcement
    access_aud: str = ""  # Application Audience (AUD) tag
    cloudflared_metrics_url: str = "http://127.0.0.1:2000"  # managed tunnel /ready health
    remote_access_mode: str = "lan"  # lan | cloudflare | tailscale (display)
    remote_hostname: str = ""  # display-only public hostname (Decision 12)
    # Enforce Cloudflare Access only on tunnelled requests so direct-LAN access keeps working
    # (LAN still requires the shared secret). Set false to enforce Access on every request.
    access_lan_bypass: bool = True

    @property
    def db_path(self) -> Path:
        return self.data_dir / "vibe-print.sqlite"

    @property
    def assets_dir(self) -> Path:
        return self.data_dir / "assets"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
