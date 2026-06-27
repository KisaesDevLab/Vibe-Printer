-- PDF overlay templates: stamp variables onto an uploaded base PDF. Forward-only.

CREATE TABLE IF NOT EXISTS overlay_templates (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    base_asset    TEXT NOT NULL,                 -- stored asset filename of the base PDF
    fields_json   TEXT NOT NULL DEFAULT '[]',    -- [{type,page,x,y,value/asset,size,font,align,color,...}]
    sample_data   TEXT NOT NULL DEFAULT '{}',
    version       INTEGER NOT NULL DEFAULT 1,
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
