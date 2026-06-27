"""Asset storage on the filesystem volume (Decision 14 / P9).

Files are content-addressed by sha256 prefix to avoid collisions; the DB records metadata.
Reference tracking is best-effort: delete is blocked if any format/template names the asset.
"""

from __future__ import annotations

import hashlib

from .db import Database, utcnow_iso
from .errors import ApiError
from .settings import Settings


class AssetStore:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        settings.assets_dir.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[dict]:
        return [dict(r) for r in self.db.query("SELECT * FROM assets ORDER BY id")]

    def save(self, name: str, mime: str, content: bytes) -> dict:
        if len(content) > self.settings.max_asset_bytes:
            raise ApiError("validation_error", "asset exceeds size limit", status=413)
        sha = hashlib.sha256(content).hexdigest()
        stored_name = f"{sha[:16]}-{name}"
        path = self.settings.assets_dir / stored_name
        path.write_bytes(content)
        cur = self.db.execute(
            "INSERT INTO assets(name,mime,path,size,sha256,created_at) VALUES (?,?,?,?,?,?)",
            (stored_name, mime, str(path), len(content), sha, utcnow_iso()),
        )
        row = self.db.query_one("SELECT * FROM assets WHERE id=?", (cur.lastrowid,))
        return dict(row)  # type: ignore[arg-type]

    def delete(self, asset_id: int) -> None:
        row = self.db.query_one("SELECT * FROM assets WHERE id=?", (asset_id,))
        if row is None:
            raise ApiError("not_found", "asset not found")
        refs = self.db.query_one(
            "SELECT COUNT(*) c FROM formats WHERE elements_json LIKE ?",
            (f'%"{row["name"]}"%',),
        )
        if refs and refs["c"] > 0:
            raise ApiError("conflict", "asset is referenced by a format", status=409)
        try:
            (self.settings.assets_dir / row["name"]).unlink(missing_ok=True)
        except OSError:
            pass
        self.db.execute("DELETE FROM assets WHERE id=?", (asset_id,))
