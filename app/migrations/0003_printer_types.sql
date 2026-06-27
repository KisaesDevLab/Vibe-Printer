-- Expand the printers.type CHECK to allow zpl_network, star_network, pool.
-- SQLite can't ALTER a CHECK, so rebuild the table (nothing references printers via FK).

CREATE TABLE printers_new (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    type                TEXT NOT NULL CHECK (type IN
                          ('escpos_network','escpos_usb','cups','virtual',
                           'zpl_network','star_network','pool')),
    params_json         TEXT NOT NULL DEFAULT '{}',
    capabilities_json   TEXT,
    default_format_id   INTEGER REFERENCES formats(id) ON DELETE SET NULL,
    default_template_id INTEGER REFERENCES pdf_templates(id) ON DELETE SET NULL,
    allow_raw           INTEGER NOT NULL DEFAULT 0,
    version             INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

INSERT INTO printers_new
    SELECT id,name,type,params_json,capabilities_json,default_format_id,
           default_template_id,allow_raw,version,created_at,updated_at
    FROM printers;

DROP TABLE printers;
ALTER TABLE printers_new RENAME TO printers;

CREATE INDEX IF NOT EXISTS idx_printers_type ON printers(type);
