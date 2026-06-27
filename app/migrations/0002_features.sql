-- Hash-chained audit, job scheduling/priority. Forward-only.

ALTER TABLE config_audit ADD COLUMN prev_hash  TEXT;
ALTER TABLE config_audit ADD COLUMN entry_hash TEXT;
ALTER TABLE print_audit  ADD COLUMN prev_hash  TEXT;
ALTER TABLE print_audit  ADD COLUMN entry_hash TEXT;

ALTER TABLE jobs ADD COLUMN priority     INTEGER NOT NULL DEFAULT 0;  -- higher runs first
ALTER TABLE jobs ADD COLUMN scheduled_at TEXT;                        -- not-before timestamp

CREATE INDEX IF NOT EXISTS idx_jobs_ready ON jobs(status, priority);
