-- Vibe Print initial schema (P1.1). Forward-only.

CREATE TABLE IF NOT EXISTS device_settings (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    name            TEXT NOT NULL DEFAULT 'vibe-print',
    timezone        TEXT NOT NULL DEFAULT 'UTC',
    config_json     TEXT NOT NULL DEFAULT '{}',   -- queue/retry/limits/retention/remote_access
    version         INTEGER NOT NULL DEFAULT 1,
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS printers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    type                TEXT NOT NULL CHECK (type IN ('escpos_network','escpos_usb','cups','virtual')),
    params_json         TEXT NOT NULL DEFAULT '{}',
    capabilities_json   TEXT,                     -- cached capability descriptor
    default_format_id   INTEGER REFERENCES formats(id) ON DELETE SET NULL,
    default_template_id INTEGER REFERENCES pdf_templates(id) ON DELETE SET NULL,
    allow_raw           INTEGER NOT NULL DEFAULT 0,  -- print/raw off by default (Phase 29.5)
    version             INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS formats (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    schema_version  INTEGER NOT NULL DEFAULT 1,
    elements_json   TEXT NOT NULL DEFAULT '{"elements":[]}',
    sample_data     TEXT NOT NULL DEFAULT '{}',
    version         INTEGER NOT NULL DEFAULT 1,
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS pdf_templates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    html            TEXT NOT NULL DEFAULT '',
    css             TEXT NOT NULL DEFAULT '',
    page_setup_json TEXT NOT NULL DEFAULT '{}',
    sample_data     TEXT NOT NULL DEFAULT '{}',
    version         INTEGER NOT NULL DEFAULT 1,
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS assets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    mime          TEXT NOT NULL,
    path          TEXT NOT NULL,
    size          INTEGER NOT NULL,
    sha256        TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS jobs (
    id                  TEXT PRIMARY KEY,                  -- uuid
    idempotency_key     TEXT,
    printer_id          INTEGER NOT NULL,
    format_id           INTEGER,
    template_id         INTEGER,
    resolved_version    INTEGER,                           -- format/template version at enqueue
    payload_json        TEXT NOT NULL,                     -- {document|format|template, data, copies}
    status              TEXT NOT NULL DEFAULT 'queued',
    delivery            TEXT,                              -- 'sent' | 'completed' | null
    attempts            INTEGER NOT NULL DEFAULT 0,
    last_error          TEXT,
    next_attempt_at     TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS idempotency (
    key           TEXT PRIMARY KEY,
    request_hash  TEXT NOT NULL,
    job_id        TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS config_audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    actor       TEXT,
    real_ip     TEXT,
    entity      TEXT NOT NULL,
    entity_id   TEXT,
    action      TEXT NOT NULL,
    diff_json   TEXT,
    ts          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS print_audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT NOT NULL,
    printer_id  INTEGER,
    actor       TEXT,
    real_ip     TEXT,
    bytes       INTEGER,
    outcome     TEXT,
    ts          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_printer_status ON jobs(printer_id, status);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);
CREATE INDEX IF NOT EXISTS idx_idem_key ON idempotency(key);
CREATE INDEX IF NOT EXISTS idx_config_audit_ts ON config_audit(ts);
CREATE INDEX IF NOT EXISTS idx_print_audit_ts ON print_audit(ts);
