"""DB-backed config registry: printers, formats, templates, device settings.

- In-memory cache, invalidated on every write.
- Optimistic concurrency: updates carry a ``version``; a stale version raises 409.
- YAML import/export round-trips printers + formats + templates.

Audit writing is the API layer's responsibility (it knows actor + real_ip); the registry
just mutates and bumps versions.
"""

from __future__ import annotations

import json
import threading
from typing import Any

import yaml

from .db import Database, utcnow_iso
from .errors import ApiError
from .models import (
    DeviceUpdate,
    FormatCreate,
    FormatUpdate,
    PrinterCreate,
    PrinterRead,
    PrinterUpdate,
    TemplateCreate,
    TemplateUpdate,
)


def _loads(s: str | None, default: Any) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return default


class Registry:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._lock = threading.Lock()
        self._cache: dict[str, Any] = {}

    def _invalidate(self) -> None:
        with self._lock:
            self._cache.clear()

    # ----------------------------------------------------------------- printers
    def list_printers(self) -> list[PrinterRead]:
        rows = self.db.query("SELECT * FROM printers ORDER BY id")
        return [self._printer_row(r) for r in rows]

    def get_printer(self, printer_id: int) -> PrinterRead:
        row = self.db.query_one("SELECT * FROM printers WHERE id=?", (printer_id,))
        if row is None:
            raise ApiError("unknown_printer", f"No printer with id {printer_id}")
        return self._printer_row(row)

    def _printer_row(self, row: Any) -> PrinterRead:
        caps = _loads(row["capabilities_json"], None)
        params = _loads(row["params_json"], {})
        params["type"] = row["type"]
        return PrinterRead(
            id=row["id"],
            name=row["name"],
            type=row["type"],
            params=params,
            capabilities=caps,
            default_format_id=row["default_format_id"],
            default_template_id=row["default_template_id"],
            allow_raw=bool(row["allow_raw"]),
            version=row["version"],
        )

    def create_printer(self, data: PrinterCreate) -> PrinterRead:
        params = data.params.model_dump()
        ptype = params.pop("type")
        cur = self.db.execute(
            "INSERT INTO printers(name,type,params_json,default_format_id,default_template_id,"
            "allow_raw,version,created_at,updated_at) VALUES (?,?,?,?,?,?,1,?,?)",
            (
                data.name,
                ptype,
                json.dumps(params),
                data.default_format_id,
                data.default_template_id,
                int(data.allow_raw),
                utcnow_iso(),
                utcnow_iso(),
            ),
        )
        self._invalidate()
        return self.get_printer(int(cur.lastrowid or 0))

    def update_printer(self, printer_id: int, data: PrinterUpdate) -> PrinterRead:
        current = self.get_printer(printer_id)
        self._check_version(current.version, data.version)
        params = data.params.model_dump()
        ptype = params.pop("type")
        self.db.execute(
            "UPDATE printers SET name=?,type=?,params_json=?,default_format_id=?,"
            "default_template_id=?,allow_raw=?,version=version+1,capabilities_json=NULL,"
            "updated_at=? WHERE id=?",
            (
                data.name,
                ptype,
                json.dumps(params),
                data.default_format_id,
                data.default_template_id,
                int(data.allow_raw),
                utcnow_iso(),
                printer_id,
            ),
        )
        self._invalidate()
        return self.get_printer(printer_id)

    def set_capabilities(self, printer_id: int, caps: dict[str, Any]) -> None:
        self.db.execute(
            "UPDATE printers SET capabilities_json=? WHERE id=?",
            (json.dumps(caps), printer_id),
        )
        self._invalidate()

    def delete_printer(self, printer_id: int) -> None:
        self.get_printer(printer_id)  # 404 if missing
        self.db.execute("DELETE FROM printers WHERE id=?", (printer_id,))
        self._invalidate()

    # ------------------------------------------------------------------ formats
    def list_formats(self) -> list[dict[str, Any]]:
        return [self._format_row(r) for r in self.db.query("SELECT * FROM formats ORDER BY id")]

    def get_format(self, fid: int) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM formats WHERE id=?", (fid,))
        if row is None:
            raise ApiError("not_found", f"No format with id {fid}")
        return self._format_row(row)

    def _format_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "elements": _loads(row["elements_json"], {"elements": []}),
            "sample_data": _loads(row["sample_data"], {}),
            "version": row["version"],
        }

    def create_format(self, data: FormatCreate) -> dict[str, Any]:
        cur = self.db.execute(
            "INSERT INTO formats(name,elements_json,sample_data,version,updated_at) "
            "VALUES (?,?,?,1,?)",
            (data.name, json.dumps(data.elements), json.dumps(data.sample_data), utcnow_iso()),
        )
        self._invalidate()
        return self.get_format(int(cur.lastrowid or 0))

    def update_format(self, fid: int, data: FormatUpdate) -> dict[str, Any]:
        current = self.get_format(fid)
        self._check_version(current["version"], data.version)
        self.db.execute(
            "UPDATE formats SET name=?,elements_json=?,sample_data=?,version=version+1,"
            "updated_at=? WHERE id=?",
            (data.name, json.dumps(data.elements), json.dumps(data.sample_data), utcnow_iso(), fid),
        )
        self._invalidate()
        return self.get_format(fid)

    def delete_format(self, fid: int) -> None:
        self.get_format(fid)
        self.db.execute("DELETE FROM formats WHERE id=?", (fid,))
        self._invalidate()

    # ---------------------------------------------------------------- templates
    def list_templates(self) -> list[dict[str, Any]]:
        return [
            self._template_row(r) for r in self.db.query("SELECT * FROM pdf_templates ORDER BY id")
        ]

    def get_template(self, tid: int) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM pdf_templates WHERE id=?", (tid,))
        if row is None:
            raise ApiError("not_found", f"No template with id {tid}")
        return self._template_row(row)

    def _template_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "html": row["html"],
            "css": row["css"],
            "page_setup": _loads(row["page_setup_json"], {}),
            "sample_data": _loads(row["sample_data"], {}),
            "version": row["version"],
        }

    def create_template(self, data: TemplateCreate) -> dict[str, Any]:
        cur = self.db.execute(
            "INSERT INTO pdf_templates"
            "(name,html,css,page_setup_json,sample_data,version,updated_at) "
            "VALUES (?,?,?,?,?,1,?)",
            (
                data.name,
                data.html,
                data.css,
                json.dumps(data.page_setup),
                json.dumps(data.sample_data),
                utcnow_iso(),
            ),
        )
        self._invalidate()
        return self.get_template(int(cur.lastrowid or 0))

    def update_template(self, tid: int, data: TemplateUpdate) -> dict[str, Any]:
        current = self.get_template(tid)
        self._check_version(current["version"], data.version)
        self.db.execute(
            "UPDATE pdf_templates SET name=?,html=?,css=?,page_setup_json=?,sample_data=?,"
            "version=version+1,updated_at=? WHERE id=?",
            (
                data.name,
                data.html,
                data.css,
                json.dumps(data.page_setup),
                json.dumps(data.sample_data),
                utcnow_iso(),
                tid,
            ),
        )
        self._invalidate()
        return self.get_template(tid)

    def delete_template(self, tid: int) -> None:
        self.get_template(tid)
        self.db.execute("DELETE FROM pdf_templates WHERE id=?", (tid,))
        self._invalidate()

    # -------------------------------------------------------------------- device
    def get_device(self) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM device_settings WHERE id=1")
        assert row is not None
        return {
            "name": row["name"],
            "timezone": row["timezone"],
            "config": _loads(row["config_json"], {}),
            "version": row["version"],
        }

    def update_device(self, data: DeviceUpdate) -> dict[str, Any]:
        current = self.get_device()
        self._check_version(current["version"], data.version)
        self.db.execute(
            "UPDATE device_settings SET name=?,timezone=?,config_json=?,version=version+1,"
            "updated_at=? WHERE id=1",
            (data.name, data.timezone, json.dumps(data.config), utcnow_iso()),
        )
        self._invalidate()
        return self.get_device()

    # --------------------------------------------------------------------- yaml
    def export_yaml(self) -> str:
        doc = {
            "printers": [
                {
                    "name": p.name,
                    "params": p.params,
                    "default_format": p.default_format_id,
                    "default_template": p.default_template_id,
                    "allow_raw": p.allow_raw,
                }
                for p in self.list_printers()
            ],
            "formats": [
                {"name": f["name"], "elements": f["elements"], "sample_data": f["sample_data"]}
                for f in self.list_formats()
            ],
            "templates": [
                {
                    "name": t["name"],
                    "html": t["html"],
                    "css": t["css"],
                    "page_setup": t["page_setup"],
                    "sample_data": t["sample_data"],
                }
                for t in self.list_templates()
            ],
        }
        return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)

    def _format_id_by_name(self, name: str) -> int | None:
        row = self.db.query_one("SELECT id FROM formats WHERE name=?", (name,))
        return row["id"] if row else None

    def _template_id_by_name(self, name: str) -> int | None:
        row = self.db.query_one("SELECT id FROM pdf_templates WHERE name=?", (name,))
        return row["id"] if row else None

    def _printer_id_by_name(self, name: str) -> int | None:
        row = self.db.query_one("SELECT id FROM printers WHERE name=?", (name,))
        return row["id"] if row else None

    def import_yaml(self, text: str, *, dry_run: bool = True) -> dict[str, Any]:
        from pydantic import TypeAdapter

        from .models import PrinterParams  # local import to avoid cycle at module load

        doc = yaml.safe_load(text) or {}

        from collections.abc import Callable

        def split(
            items: list[dict[str, Any]], finder: Callable[[str], int | None]
        ) -> tuple[int, int]:
            create = update = 0
            for it in items:
                if finder(it["name"]) is not None:
                    update += 1
                else:
                    create += 1
            return create, update

        fc, fu = split(doc.get("formats", []), self._format_id_by_name)
        tc, tu = split(doc.get("templates", []), self._template_id_by_name)
        pc, pu = split(doc.get("printers", []), self._printer_id_by_name)
        plan = {
            "formats": {"create": fc, "update": fu},
            "templates": {"create": tc, "update": tu},
            "printers": {"create": pc, "update": pu},
            "dry_run": dry_run,
        }
        if dry_run:
            return plan

        # Upsert by name (idempotent re-import).
        for f in doc.get("formats", []):
            existing = self._format_id_by_name(f["name"])
            if existing is not None:
                cur = self.get_format(existing)
                self.update_format(existing, FormatUpdate(version=cur["version"], **f))
            else:
                self.create_format(FormatCreate(**f))
        for t in doc.get("templates", []):
            existing = self._template_id_by_name(t["name"])
            if existing is not None:
                cur = self.get_template(existing)
                self.update_template(existing, TemplateUpdate(version=cur["version"], **t))
            else:
                self.create_template(TemplateCreate(**t))
        for p in doc.get("printers", []):
            params: Any = TypeAdapter(PrinterParams).validate_python(p["params"])
            existing = self._printer_id_by_name(p["name"])
            if existing is not None:
                cur_p = self.get_printer(existing)
                self.update_printer(
                    existing,
                    PrinterUpdate(
                        name=p["name"],
                        params=params,
                        default_format_id=p.get("default_format"),
                        default_template_id=p.get("default_template"),
                        allow_raw=p.get("allow_raw", False),
                        version=cur_p.version,
                    ),
                )
            else:
                self.create_printer(
                    PrinterCreate(
                        name=p["name"],
                        params=params,
                        default_format_id=p.get("default_format"),
                        default_template_id=p.get("default_template"),
                        allow_raw=p.get("allow_raw", False),
                    )
                )
        return plan

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _check_version(current: int, supplied: int) -> None:
        if current != supplied:
            raise ApiError(
                "conflict",
                f"Stale write: expected version {current}, got {supplied}. Reload and retry.",
                status=409,
                details={"current_version": current},
            )
