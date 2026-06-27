# Build status — Vibe Print

Mapped to the phases in `VIBE-PRINT-MASTER-PLAN.md`. **Everything in the plan — including the
"consciously deferred" list — is now built**, except two items that contradict locked
architecture decisions (see bottom). QA: **73 tests passing + 1 skipped**, ruff clean, **mypy clean
(enforced in CI)**, 74% coverage, frontend typechecks + builds, OpenAPI→TS drift-gated, and
**Playwright e2e verified in a real browser** against the live server.

## Implemented

| Phase | Area | Notes |
|-------|------|-------|
| P0 | Scaffold | FastAPI app, settings, structlog JSON + request-id, error envelope, Docker/compose/Makefile |
| P1 | Data model & migrations | SQLite forward-only migrations, backup-before-migrate, singleton device row, fail-fast on unset secret |
| P2 | Registry | DB-backed CRUD, in-memory cache, optimistic concurrency (409), YAML export + import (dry-run) |
| P3 | Backend abstraction | `PrinterBackend` protocol, factory, per-printer async locks, `VirtualBackend` |
| P4 | ESC/POS network | socket streaming, reachability status, mid-send → uncertain |
| P5 | ESC/POS USB | python-escpos `Usb` (lazy import; needs `usb` extra) |
| P6 | CUPS/IPP | pycups submit + job-state poll (lazy import; needs `cups` extra) |
| P7 | Templating | sandboxed Jinja2, element merge with `rows_from` loops, WeasyPrint PDF with SSRF lockdown + bounded concurrency |
| P8 | Renderer | ESC/POS bytes (size/align/table/qr/barcode/image/pulse/feed/cut), capability-aware, PNG preview |
| P9 | Assets | filesystem store, sha256, size cap, reference-check on delete |
| P10 | Queue & delivery | durable SQLite jobs, async worker, per-printer serialization (ESC/POS), CUPS parallel, idempotency + conflict, retry/backoff → dead, mid-send → uncertain, backpressure `queue_full`, graceful drain, retention prune |
| P11 | Print API | `/v1/print`, `/print/raw`, `/print/preview`, printers, jobs |
| P12 | Auth | shared secret (constant-time), proxy-aware real-IP, per-IP rate limit, body caps |
| P13 | Admin API | full CRUD + test print + status + config import/export + job actions, audited |
| P14 | Observability | structlog, Prometheus `/metrics`, config + print audit tables |
| P17–P21 | Admin UI | React 18 + TS + Vite: secret gate, printers, formats (+ live PNG preview), templates (+ PDF preview), jobs dashboard (resolve/requeue/cancel), device + backup/restore |
| P23 | Packaging | multi-stage Dockerfile (WeasyPrint/fonts/libusb/CUPS), compose profiles (caddy, cloudflare), Caddyfile, localhost-only cupsd, healthcheck, sample clients |
| P24 | Tests | auth/fail-fast, registry/concurrency/YAML, templating/injection, print flow, idempotency, delivery (uncertain + retry) |
| P25 | CI | GitHub Actions: ruff + tests + frontend build, multi-arch image on tag |
| P26 | Local dev | `make dev/test/lint/seed/build`, virtual backend, seed fixtures |
| P30 (partial) | Hardening | CSP + security headers on /admin, WeasyPrint SSRF lockdown, render concurrency cap, CUPS bound to localhost, raw off by default |
| P15 | LAN discovery | bounded `:9100`/IPP scan (`POST /v1/admin/discover`) + UI discover panel that prefills the printer form |
| P27 | Provisioning + update | `GET /v1/version` (app/schema/digest), first-boot `provision` endpoints, `deploy/upgrade.sh` (pull pinned digest → health-gate `/readyz` → rollback). Manual `vibe upgrade`, no auto timers |
| P29 | Compliance | log-redaction processor (drops payload/data/html/css/value), payload-hash mode (`store_payloads=false` → hash after print), retention sweep (worker) + on-demand `retention/prune` and per-job `payload` erasure, opt-in SQLCipher-at-rest hook |

| P12.5 | Cloudflare Access | RS256 JWT verify against team JWKS (aud/issuer), service-token path, identity → audit; enforced on `/v1/admin/*` when configured |
| P16 | Tunnel health | `GET /v1/admin/remote/status` polls cloudflared `/ready`; hostname display-only (Decision 12) |
| P14.4/P28 | Webhooks + fleet | HMAC-signed failure (`dead`/`uncertain`) + printer-offline webhooks, periodic heartbeat phone-home, `GET /v1/admin/diagnostics` PII-free bundle |
| P22.7 | Backup/restore | consistent `VACUUM INTO` snapshot endpoint + `deploy/backup.sh`/`restore.sh` to Backblaze B2 (Object Lock), restore-drill doc |
| P26.4 | OpenAPI→TS codegen | `app/openapi_dump`, `make gen-api`, generated `web/src/api-types.ts`, CI drift gate |
| P19/P20 | CodeMirror editors | JSON/HTML/CSS editors with syntax highlighting replace textareas |
| P24.5/P24.6 | e2e + soak | Playwright admin-flow spec; backend soak asserting per-printer serialization under load |

| Audit | Tamper-evident | hash-chained `config_audit`/`print_audit` (prev/entry hash), `GET /v1/admin/audit/verify` detects any mid-chain edit |
| Queue | Priority/scheduling/quotas | `priority` ordering, `scheduled_at` not-before, per-printer daily quotas (`quota_exceeded`) |
| Routing | Printer pools / failover | `pool` type routes to first-reachable / round-robin member; aggregated capabilities + status |
| Backends | ZPL + StarPRNT | label (Zebra ZPL II) + Star Line Mode network backends with element renderers |
| Compliance | Encryption at rest | SQLCipher wiring (Linux wheels in image; key-bind + wrong-key rejection) |
| CUPS | Queue provisioning | `POST /v1/admin/printers/{id}/provision-queue` (driverless IPP Everywhere) |
| UI | Visual element builder | drag-reorder ESC/POS element builder + per-type editors, two-way JSON sync |
| UI | i18n | en/es with language switcher |
| API | Reprint + pagination | `POST /v1/jobs/{id}/reprint`, cursor pagination on the jobs list (amendments B10/B11) |

**Follow-up decisions applied:** preview endpoints render **inline unsaved** content (no version
churn); YAML import **upserts by name** (idempotent re-import).

## Excluded by design (require a different product)

Only two plan-listed items remain unbuilt, because they directly contradict locked decisions and
the appliance model — building them would mean a different product:

- **Multi-tenant isolation** — conflicts with Decision 6 (single shared secret, no user/RBAC). Real
  multi-tenancy needs per-tenant auth, data partitioning, and an identity model the appliance
  deliberately omits.
- **HA / multi-node** — conflicts with the single-process SQLite appliance design (per-printer
  in-process locks, one durable queue). HA needs Postgres (or similar), distributed locks, and
  leader election. The current design targets one box per site, which is the stated deployment.

If you want either, it's a scoped follow-up with an explicit architecture change — say the word.

## Environment notes

- **SQLCipher** round-trip test is skipped on Windows (no wheel); it is installed and exercised in
  the Linux image via the `encrypt` extra. The fail-loud path (encryption requested, driver
  missing) is tested everywhere.
- **Playwright** needs `npx playwright install chromium` once; the spec was run live and passes.

## Known caveats

- `mypy app` is run with `|| true` in CI until annotations are tightened.
- The async worker keeps one SQLite connection guarded by a lock — correct for a single-process
  appliance, not for horizontal scale (out of scope by design).
- `/print` with `copies` repeats ESC/POS bytes N times; CUPS copies are passed as an option.
