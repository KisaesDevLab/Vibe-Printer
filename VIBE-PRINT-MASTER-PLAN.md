# Vibe Print — LAN Print Routing Gateway
### Consolidated Build Plan (Final, reviewed) — single source of truth

Self-hosted Docker appliance. Callers send a payload over HTTP, select a **printer by
integer id**, and the gateway routes the job to one of several printers — ESC/POS thermal
over TCP 9100, USB-attached ESC/POS, or CUPS/IPP office printers via PDF. A React admin UI
configures the device, printers, document formats, and PDF templates. Formats and templates
are stored, versioned, and merged with request `data` at print time. Remote access via
Cloudflare Tunnel (optional). Runs on a Raspberry Pi or NucBox.

> Name: `vibe-print`. This document supersedes the v1/v2/Final plans, the Admin UI
> addendum, and the Cloudflare Tunnel addendum, and folds in two aggressive gap-review passes
> (see **Appendices A & B**).

---

## Decisions (locked)

1. Stack: **Python 3.12 + FastAPI**
2. Office printers: **thermal + CUPS/IPP**
3. Config source of truth: **SQLite (UI-writable) + YAML import/export**
4. PDF templates: **Jinja2 HTML/CSS → WeasyPrint**
5. Queue: **SQLite-durable async (single worker, per-printer serialized)**
6. Auth: **single shared secret** (bearer on all `/v1/*`; no user login/sessions/CSRF)
7. USB printers: **included**
8. Admin UI: **served by gateway at `/admin`, same origin**
9. Audit: **job + config audit enabled**
10. Remote access: **LAN-only / Cloudflare Tunnel / Tailscale — selectable** (tunnel opt-in via compose profile)
11. Cloudflare Access in front of admin UI when tunnel is used: **yes (recommended)**
12. Cloudflare hostname/subdomain: **display-only in the UI** — provisioned once in the Cloudflare dashboard at setup. The appliance stores **no Cloudflare API token** and never edits DNS or tunnel ingress (smallest blast radius for client-shipped units).

### Decisions added by the gap review (defaulted — confirm if you disagree)

13. **CUPS topology:** CUPS runs **inside the appliance container** (self-contained image) rather than host CUPS via socket. *(Cleaner for client-shipped NucBox units.)*
14. **Asset storage:** **filesystem volume**, not SQLite blobs *(keeps the DB lean and B2-backup simple)*.
15. **LAN transport security:** front with **Caddy for TLS** *(you already run Caddy)*; plaintext acceptable only on a fully trusted LAN segment.
16. **Crash-during-send policy:** a job interrupted **mid-send is marked `uncertain` for operator review, not auto-retried** *(at-most-once for the in-flight job — prevents duplicate financial receipts)*. All other failures retry normally.

---

## Stack

**Backend**

| Concern           | Choice |
|-------------------|--------|
| Runtime           | Python 3.12, FastAPI, Uvicorn |
| Thermal (ESC/POS) | `python-escpos` (`Network`, `Usb`); `libusb` in image |
| Office (CUPS/IPP) | `pycups` + **CUPS in-container**; PDF via `Jinja2` + `WeasyPrint` |
| PDF fonts         | bundled font packages (DejaVu + a metric-compatible set) in the image |
| Schemas/config    | Pydantic v2 |
| Templating        | Jinja2 (sandboxed, HTML-autoescaped) over element-JSON and HTML |
| Queue/retry       | SQLite-durable async; per-printer serialization; graceful drain |
| Store             | SQLite + migrations; assets on a filesystem volume |
| Logging/metrics   | structlog (JSON), Prometheus `/metrics` |
| Packaging         | Docker (multi-arch arm64/amd64) |

**Frontend**

| Concern        | Choice |
|----------------|--------|
| Framework      | React 18 + TypeScript 5 + Vite |
| Server state   | TanStack Query |
| Forms / schema | React Hook Form + Zod |
| Editors        | CodeMirror 6 (HTML/CSS/Jinja, JSON) |
| Preview        | server-rendered PNG (`<img>`) / PDF (`<embed>` or pdf.js) |
| Styling        | your call (Tailwind assumed) |
| Served from    | FastAPI static mount at `/admin` |

---

## Auth & trust model

- One secret via env (`VIBE_PRINT_SECRET`), constant-time compared. **The service refuses to
  start if the secret is unset or empty** — never runs open.
- Sent as `Authorization: Bearer <secret>` on all `/v1/*` (print + admin). `/healthz` is open.
- UI prompts for the secret once, holds it in memory/sessionStorage, attaches it as a bearer
  header. No cookies ⇒ no CSRF machinery.
- **Real client IP** resolved from `CF-Connecting-IP`/`X-Forwarded-For` only when the peer is in
  `trusted_proxies`; otherwise socket IP. Used for audit + rate limiting.
- Rate limiting is **per real client IP** (not per shared secret, which would be global).
- Optional **Cloudflare Access** (Zero Trust) JWT enforcement on `/v1/admin/*` when exposed.
- Intended trust boundary: trusted LAN, or Cloudflare Tunnel (+ Access) / Tailscale.

---

## Delivery semantics (be honest about "printed")

- ESC/POS over TCP/USB is effectively fire-and-forget: a job is **"sent"** (bytes accepted by
  the printer/socket), which is **not** a guarantee paper emerged. CUPS jobs can be polled to a
  truer completion state via job-state.
- Job states: `queued → rendering → printing → done | failed | dead | canceled | uncertain`.
  `uncertain` = process/connection died after bytes began streaming (see Decision 16); requires
  operator action in the UI (mark done / re-queue), never silent auto-retry.
- The print API response reports the enqueue result + job id; final outcome is observed via
  `GET /v1/jobs/{id}`. This distinction is documented for client integrations.

---

## API Surface

```
# All routes require: Authorization: Bearer <shared secret>   (except /healthz)

# Print (machine-to-machine)
POST   /v1/print            {printer:int, format?:id, template?:id, document?:{}, data?:{}}
                            header: Idempotency-Key: <uuid>   (optional but recommended)
POST   /v1/print/raw        {printer:int, data:"<base64 ESC/POS>"}     # ESC/POS only
POST   /v1/print/preview    {printer:int, document|format|template, data?} -> png|pdf
GET    /v1/printers                              -> [{id,name,type,reachable,capabilities}]
GET    /v1/printers/{id}/status                  -> {state, errors}
GET    /v1/jobs/{job_id}                         -> {status, attempts, error?, delivery}
GET    /healthz                                  # liveness (open)
GET    /readyz                                   # readiness: db + worker + cups (open)

# Admin
GET/PUT  /v1/admin/device
GET/POST/PUT/DELETE /v1/admin/printers[/{id}]    # PUT carries version (optimistic concurrency)
POST   /v1/admin/printers/{id}/test | GET .../status | POST /v1/admin/discover
GET/POST/PUT/DELETE /v1/admin/formats[/{id}]     |  POST .../{id}/preview -> png
GET/POST/PUT/DELETE /v1/admin/templates[/{id}]   |  POST .../{id}/preview -> pdf
POST   /v1/admin/assets
GET    /v1/admin/jobs?status=     |  POST /v1/admin/jobs/{id}/{cancel|requeue|resolve}
POST   /v1/admin/config/export | import
POST   /v1/admin/secret/rotate                   # optional
```

**Error envelope (all routes):** `{error:{code, message, details?}}`, stable machine codes
(`unknown_printer`, `unsupported_for_printer`, `validation_error`, `unauthorized`,
`rate_limited`, `queue_full`, `render_error`, `printer_unreachable`, `idempotency_conflict`).

---

## Data Model (SQLite)

- `device_settings` (singleton): name, tz (timestamps stored UTC), queue cfg, retry/backoff,
  max_attempts, rate limits, body caps, **job/audit retention windows**, remote_access cfg.
- `printers`: id, name, type (`escpos_network|escpos_usb|cups`), typed params
  (host/port/profile/columns/paper_width_dots/encoding/codepage/cut | vid/pid/serial/columns | queue/media),
  **capabilities (cached)**, default_format_id, default_template_id, version, created/updated.
- `formats`: id, name, schema_version, elements(JSON w/ Jinja tokens), sample_data, version, updated.
- `pdf_templates`: id, name, html, css, page_setup(size,margins), sample_data, version, updated.
- `assets`: id, name, mime, path (filesystem), size, sha256, referenced_by.
- `jobs`: id, idempotency_key?, printer_id, format/template ref + **resolved version**,
  payload, status, delivery, attempts, last_error, created/updated.
- `idempotency`: key, request_hash, job_id, created (TTL-pruned).
- `config_audit`: actor (secret/Access identity), real_ip, entity, entity_id, action, diff, ts.
- `print_audit`: job_id, printer_id, actor, real_ip, bytes, outcome, ts.

Indexes on `jobs(status)`, `jobs(printer_id,status)`, `idempotency(key)`. Retention job prunes
`jobs`, `*_audit`, and `idempotency` past their windows.

---

## Document Schema (backend-agnostic, Jinja-templated)

```json
{
  "elements": [
    {"type":"text","value":"{{ data.company }}","align":"center","bold":true,"size":[2,2]},
    {"type":"text","value":"Report {{ data.date }}","align":"center"},
    {"type":"rule"},
    {"type":"table","cols":[24,12,12],"align":["left","right","right"],
     "rows_from":"data.lines","row":["{{ item.name }}","{{ item.qty }}","{{ item.amt }}"]},
    {"type":"qr","value":"{{ data.url }}","size":6},
    {"type":"barcode","format":"CODE128","value":"{{ data.ref }}"},
    {"type":"image","asset":"logo"},
    {"type":"pulse"},                       // optional cash-drawer kick
    {"type":"feed","lines":2},
    {"type":"cut"}
  ]
}
```

ESC/POS path → Jinja merge (autoescaped where rendered to HTML; raw text encoded to the
printer **codepage** with a transliteration fallback for unmapped glyphs) → `python-escpos`.
Images are scaled/dithered to the printer's `paper_width_dots`. CUPS path → Jinja HTML/CSS →
WeasyPrint PDF. **If a format uses a feature the target printer lacks** (per cached
capabilities), the API returns `unsupported_for_printer` (or degrades per a documented policy).

---

# PART A — Backend

### Phase 0 — Scaffold
- P0.1 Repo, `pyproject.toml`, ruff + mypy, pre-commit.
- P0.2 FastAPI skeleton, `/healthz` + `/readyz`, settings via Pydantic `BaseSettings`.
- P0.3 structlog JSON logging + request-id middleware.
- P0.4 Dockerfile + compose (config/SQLite/asset volumes).
- ✅ Container boots; `/healthz` 200; `/readyz` reflects deps.

### Phase 1 — Data model & migrations
- P1.1 Migration tooling; create all tables + indexes above.
- P1.2 Pydantic models (discriminated union on printer `type`).
- P1.3 First-run: empty `device_settings` singleton; refuse start if `VIBE_PRINT_SECRET` unset.
- ✅ Fresh DB migrates clean; missing secret aborts boot with a clear message.

### Phase 2 — Config/registry service
- P2.1 DB-backed registry: `get/list/CRUD`, cache + invalidate on write.
- P2.2 Optimistic concurrency on updates (version check → `409` on stale write).
- P2.3 YAML export (printers+formats+templates) and import (validate, dry-run diff).
- P2.4 Startup validation: load + validate all printers; surface config errors to UI/log.
- ✅ Registry from DB; YAML round-trips identically; concurrent edits don't clobber.

### Phase 3 — Backend abstraction
- P3.1 `PrinterBackend` protocol: `open/send/status/capabilities/close`.
- P3.2 Factory: registry row → concrete backend.
- P3.3 `VirtualBackend` (writes ESC/POS to file + renders preview PNG).
- P3.4 **Per-printer async lock / mutex** so only one job streams to a given printer at a time.
- ✅ Factory dispatches by type; concurrent jobs to one printer serialize; virtual round-trips.

### Phase 4 — ESC/POS network backend (primary)
- P4.1 `EscposNetworkBackend` over `escpos.printer.Network`; timeouts; raise on socket failure.
- P4.2 Real-time status (DLE EOT): paper/cover/error where supported.
- P4.3 Codepage/encoding handling + transliteration fallback for unmapped characters.
- P4.4 Capability descriptor (cut/barcode formats/QR/raster/columns/paper width).
- ✅ Prints to a 9100 printer/mock; offline + non-ASCII handled; capabilities reported.

### Phase 5 — ESC/POS USB backend
- P5.1 `EscposUsbBackend` via `escpos.printer.Usb(vid,pid[,serial])`.
- P5.2 Disconnect/hotplug handling; identify by vid/pid(/serial); Docker `--device` + udev docs.
- ✅ Prints to USB device; survives unplug/replug; stable identity.

### Phase 6 — CUPS/IPP backend
- P6.1 **CUPS in-container**: install/run cupsd in the image; provision queues from registry.
- P6.2 `CupsBackend` via `pycups`: submit to queue, map media; **poll job-state to true completion**.
- P6.3 Map `printer-state`/`reasons` to common status; surface printer errors.
- ✅ Prints a PDF to a CUPS queue; status + completion reflect real CUPS state.

### Phase 7 — Templating engine
- P7.1 Sandboxed Jinja2 env; HTML **autoescape on**; table/loop helpers (`rows_from`).
- P7.2 Element-JSON merge (formats) → render-ready structure.
- P7.3 HTML/CSS merge (pdf_templates) → WeasyPrint PDF.
- P7.4 **WeasyPrint locked down**: disable/allowlist remote URL fetching (assets only) — no SSRF;
  enforce a **render timeout + memory ceiling**.
- P7.5 Clear, safe errors for missing/invalid vars and render failures.
- ✅ Formats + templates merge correctly; remote-fetch blocked; runaway renders time out.

### Phase 8 — Renderer
- P8.1 ESC/POS renderer: elements → `python-escpos` (size/align, tables, qr/barcode/image,
  pulse, feed, cut), column-aware; images scaled/dithered to `paper_width_dots`.
- P8.2 Capability-aware behavior: reject or degrade unsupported elements per policy.
- P8.3 PDF renderer (WeasyPrint) parity; page setup + bundled fonts honored.
- P8.4 Preview renderers: format→PNG, template→PDF (no hardware).
- ✅ Same logical doc prints sensibly on thermal + CUPS; previews match output.

### Phase 9 — Asset management
- P9.1 Upload/store assets on the **filesystem volume**; record path/sha256/size; type+size limits.
- P9.2 Serve to renderers (WeasyPrint local base URL; ESC/POS raster conversion).
- P9.3 Reference tracking; block delete of in-use assets (or warn).
- ✅ One uploaded logo renders in both a PDF template and a thermal format.

### Phase 10 — Queue, concurrency & delivery
- P10.1 Durable job store (SQLite): states per the delivery model.
- P10.2 Async worker with **per-printer serialization**; slow printer can't block others.
- P10.3 **Idempotency**: `Idempotency-Key` → dedupe within TTL; identical key+payload returns the
  original job; same key + different payload → `idempotency_conflict`.
- P10.4 Retry with exponential backoff + max attempts → `dead`; **mid-send interruption →
  `uncertain`** (no auto-retry; Decision 16).
- P10.5 Backpressure: max queue depth + per-printer cap → `queue_full` (429).
- P10.6 Graceful shutdown: stop intake, drain/flush in-flight, persist state on SIGTERM.
- P10.7 Retention pruning of jobs/audit/idempotency per configured windows.
- ✅ Concurrency safe; no duplicate receipts on crash; queue bounded; clean shutdown.

### Phase 11 — Print API
- P11.1 `POST /v1/print`: `document` inline OR `format`/`template` id + `data`; resolve + record
  template **version** on the job; honor `Idempotency-Key`; enqueue.
- P11.2 `POST /v1/print/raw` (ESC/POS only; reject for CUPS with `unsupported_for_printer`).
- P11.3 `POST /v1/print/preview` → png|pdf.
- P11.4 `GET /v1/printers/{id}/status`; cached `reachable` + `capabilities` in `/v1/printers`.
- P11.5 `GET /v1/jobs/{job_id}` incl. `delivery`; admin job actions (cancel/requeue/resolve).
- ✅ document/format/template all print; idempotent retries don't duplicate; states observable.

### Phase 12 — Auth, real-IP & rate limiting
- P12.1 Load `VIBE_PRINT_SECRET`; constant-time compare; **fail-fast if unset**.
- P12.2 Bearer dependency on all `/v1/*`; `/healthz`+`/readyz` open.
- P12.3 Proxy-aware real-IP: trust `CF-Connecting-IP`/`X-Forwarded-For` only from `trusted_proxies`;
  uvicorn `--forwarded-allow-ips` scoped to the proxy peer.
- P12.4 Per-real-IP rate limit + body-size caps.
- P12.5 Optional Cloudflare Access JWT verify on `/v1/admin/*` (verify sig vs cached team certs,
  check `aud`/exp); expose identity to audit.
- P12.6 Optional `POST /v1/admin/secret/rotate` (warns it breaks existing clients).
- ✅ No secret → no boot; wrong secret 401; spoofed IP headers ignored; Access enforced when on.

### Phase 13 — Admin API
- P13.1 CRUD: device, printers, formats, templates, assets (+ optimistic concurrency).
- P13.2 Shared validation; consistent error envelope.
- P13.3 Actions: test-print, live status, LAN discover.
- P13.4 Preview endpoints (format→PNG, template→PDF) with sample data.
- P13.5 Write `config_audit` (actor + real_ip + diff) on every mutation.
- ✅ Full config manageable over API; previews need no hardware; every change audited.

### Phase 14 — Observability & audit
- P14.1 Structured logs across enqueue/render/send (job + request ids + real_ip).
- P14.2 `print_audit` + `config_audit` queryable; **dead-letter/`uncertain` surfaced** for action.
- P14.3 `/metrics`: jobs by status, per-printer counts, queue depth, render timings.
- P14.4 Optional **failure webhook** (POST on `dead`/`uncertain`) for ops alerting.
- ✅ Every job + config change traceable; failures are visible, not silent.

### Phase 15 — Discovery helper
- P15.1 Scan LAN for open `:9100` and IPP/Bonjour printers (bounded scope/rate).
- P15.2 Return candidates to the UI discover modal / YAML stub.
- ✅ Scanner suggests printers to add.

### Phase 16 — Remote Access: Cloudflare Tunnel (optional)
- P16.1 `cloudflare/cloudflared` sidecar under compose profile `cloudflare` (off by default);
  token-based run (`TUNNEL_TOKEN`) default, credentials-file documented; ingress
  `hostname → http://vibe-print:<port>`; outbound-only; waits on `/healthz`.
- P16.2 Proxy awareness wired to P12.3 (`trusted_proxies` includes the cloudflared peer).
- P16.3 Cloudflare Access: app-side JWT enforcement (P12.5) + service-token path for remote
  print clients (`CF-Access-Client-Id/Secret`).
- P16.4 Tunnel health for the UI: poll cloudflared `/ready`; surface the configured hostname
  **read-only** (display only — the appliance never edits ingress/DNS; Decision 12).
- P16.5 Docs: token quickstart, Access app/policy + `aud` capture, service tokens; Tailscale noted
  as the private-only alternative.
- ✅ Profile on + Access configured → admin UI at the public hostname behind SSO; print calls
  authenticate over the tunnel; audit shows real identity/IP. Profile off → identical to LAN-only.

---

# PART B — Admin UI (component-level)

Shared: TanStack Query hooks per resource; Zod schemas aligned to backend; bearer secret on
every request; toast/error layer; loading/empty/error states on every list and editor;
optimistic-concurrency conflict handling (`409` → reload prompt). Preview is server-rendered
and shown as-is.

### Phase 17 — Frontend scaffold
- P17.1 Vite + React 18 + TS under `web/`, built into FastAPI static mount `/admin`.
- P17.2 Router; `AppShell` nav: Device / Printers / Document Formats / PDF Templates.
- P17.3 `SecretGate`: prompt for secret once, hold in memory/sessionStorage, attach as bearer;
  any 401 → re-prompt. (No login/user concept.)
- P17.4 Query client, global error boundary, toast provider.
- P17.5 Shared Zod types; typed `apiClient` injecting the secret header + idempotency keys.
- ✅ Shell loads after secret entry; nav routes render; 401 → re-prompt.

### Phase 18 — Printers UI
- P18.1 `PrintersListPage` — id, name, `PrinterTypeBadge`, `ReachabilityIndicator`, capabilities
  glyphs, default format/template, actions; filter by type; search; empty/loading/error.
- P18.2 `ReachabilityIndicator` — polls `/status` (cached TTL): checking/reachable/unreachable/unknown.
- P18.3 `PrinterForm` (create/edit, type-discriminated)
  - Common: `name`, `type`.
  - `escpos_network`: `host`, `port` (9100), `profile` (select), `columns`, `paper_width`, `encoding`/`codepage`, `cut`.
  - `escpos_usb`: `vendor_id`, `product_id` (hex, validated), `serial?`, `columns`, `paper_width`.
  - `cups`: `queue` (select), `media` (select).
  - Defaults: `default_format_id`, `default_template_id`.
  - Zod validation, inline errors, dirty-guard, optimistic-concurrency conflict handling.
- P18.4 `TestPrintButton` → POST test, toast + job link.
- P18.5 `StatusDrawer` → live status (paper/cover/error or CUPS state) + capabilities.
- P18.6 `DiscoveryModal` → scan, list `:9100`/IPP candidates, select → prefill form.
- P18.7 `DeletePrinterDialog` → confirm; warn if referenced as a default.
- P18.8 Hooks: printers CRUD, test, status, discover.
- ✅ Create, edit, test, discover, delete printers fully from the UI.

### Phase 19 — Document Formats UI (ESC/POS)
- P19.1 `FormatsListPage` — list; create/duplicate/delete; version + updated.
- P19.2 `FormatEditor` (split)
  - Left `ElementBuilder`: `ElementList` (drag-reorder) + add menu; editors for
    text (value+token insert, align, bold, size), table (col widths, per-col align, static rows
    or `rows_from` loop + row template), qr, barcode, image (`AssetPicker`), pulse, feed, cut;
    `RawJsonToggle` (CodeMirror JSON, two-way sync, validate).
  - Right `SampleDataPanel` (CodeMirror JSON) + `LivePreview` (debounced `/preview` → PNG).
  - `VariableHelper` (tokens from sample data, click-insert); `SaveBar` (name, version, save/discard);
    Jinja/element error surface.
- P19.3 Hooks: formats CRUD + preview.
- ✅ Author a receipt format with variables + table loop; accurate thermal preview.

### Phase 20 — PDF Templates UI (office/CUPS)
- P20.1 `TemplatesListPage` — list; create/duplicate/delete; version.
- P20.2 `TemplateEditor` (split)
  - Left: CodeMirror `HTML`/`CSS` (Jinja-aware); `PageSetup` (size, margins); `AssetPicker`;
    `VariableHelper`.
  - Right: `SampleDataPanel` + `LivePdfPreview` (debounced `/preview` → PDF via `<embed>`/pdf.js).
  - `SaveBar` with version; WeasyPrint error surface (line-mapped where possible).
- P20.3 `AssetUpload` (logo/image) → asset id; reference in HTML.
- P20.4 Hooks: templates CRUD + preview + asset upload.
- ✅ Author a full-page report template, preview the PDF, print to a CUPS printer.

### Phase 21 — Device UI
- P21.1 `DeviceSettingsPage` — General (name, tz); Queue (retry/backoff, max attempts, depth caps);
  Limits (rate limit, body caps); **Retention** (job/audit/idempotency windows). Per-section save.
- P21.2 `AccessPage` — shared-secret status + `RotateSecretDialog` (warning); trusted-network guidance.
- P21.3 `RemoteAccessPage` — mode (LAN/Cloudflare/Tailscale); Cloudflare fields: **hostname
  (read-only, display only)**, Access enabled, team_domain, aud_tag; tunnel health indicator.
- P21.4 `JobsDashboard` — queue depth; jobs table (status filter incl. `dead`/`uncertain`, search);
  `JobDetailDrawer` (payload summary, attempts, error, delivery; cancel/requeue/**resolve** actions); auto-refresh.
- P21.5 `BackupRestorePage` — export YAML; import (dry-run diff → apply); `ConfigAuditLog` viewer.
- P21.6 Hooks: device, secret rotate, remote-access, jobs, export/import, audit.
- ✅ Operate the gateway end-to-end (settings, secret, remote access, queue, backup, audit) without host access.

---

# PART C — Hardening, Packaging, Tests

### Phase 22 — Security & correctness hardening (cross-cutting)
- P22.1 Confirm fail-closed auth everywhere; `/healthz`/`/readyz` the only open routes.
- P22.2 WeasyPrint SSRF lockdown verified (no remote fetch); render timeout/memory caps enforced.
- P22.3 Real-IP spoofing resistance; per-IP rate limits effective behind the tunnel.
- P22.4 Payload/body caps for `print/raw` base64 and asset uploads; reject oversized early.
- P22.5 Jinja sandbox + HTML autoescape verified against injection via `data`.
- P22.6 TLS: document/automate fronting with **Caddy** for LAN HTTPS (or rely on CF edge TLS).
- P22.7 DB + asset **backup** to Backblaze B2 (Object Lock) — scheduled dump + asset sync; restore doc.
- ✅ Hardening checklist passes; backups verified by a restore drill.

### Phase 23 — Packaging & deploy
- P23.1 Multi-arch image (arm64 Pi, amd64 NucBox): WeasyPrint libs (pango/cairo/gdk-pixbuf) **+ fonts**,
  `libusb`, **in-container CUPS**.
- P23.2 Compose: config + SQLite + assets volumes; network mode reaching LAN printers; `--device` for USB;
  `cloudflare` profile for the tunnel; optional Caddy front.
- P23.3 Build `web/` and serve at `/admin`; bearer-secret model (no cookie/CSRF).
- P23.4 Systemd/restart policy; healthcheck on `/readyz`; graceful-stop timeout for drain.
- P23.5 README: secret setup, CUPS queue provisioning, udev/USB, network notes, tunnel + Access, backup.
- P23.6 Sample client snippet (curl + tiny TS/Python helper) with idempotency key usage.
- ✅ One-command deploy on a fresh Pi prints via a registered printer; tunnel optional.

### Phase 24 — Tests
- P24.1 Unit: registry/CRUD + optimistic concurrency, YAML round-trip, factory, capabilities,
  templating merge (formats + PDF), codepage/transliteration, missing-var errors, renderers.
- P24.2 Integration: virtual backend round-trip; socket-mock `:9100`; USB mock; in-container CUPS;
  per-printer serialization; queue retry/backoff/dead-letter; **crash-mid-send → `uncertain`**;
  idempotency dedupe + conflict; backpressure `queue_full`; graceful drain.
- P24.3 API: print (document/format/template), raw, preview media types, error envelope codes,
  shared-secret accept/reject + fail-fast-on-unset, rotation, **real-IP spoof rejected**,
  per-IP rate limit, Access JWT (valid/missing/expired/wrong-aud), unknown-printer 404, audit writes.
- P24.4 Security: WeasyPrint SSRF blocked, render timeout, Jinja injection via `data`, oversized payloads.
- P24.5 UI e2e (Playwright): enter secret → add printer (incl. discovery) → create format → preview →
  test print; author PDF template → preview → print; rotate secret; remote-access config;
  job dashboard resolve an `uncertain` job; export/import dry-run.
- P24.6 **Soak**: sustained mixed load across multiple printers; assert no interleaved/corrupted
  output and no duplicate prints under induced failures.
- ✅ CI green across config, templating, queue/correctness, API, security, and UI flows.

---

# PART D — Production Readiness, DevOps & Compliance

## Amendments to earlier phases (refinements from the second review)
- **Concurrency is backend-specific:** the per-printer lock (P3.4/P10.2) applies to **ESC/POS
  network + USB** (single byte stream). **CUPS** has its own spooler — submit concurrently and
  track via job-state; do not serialize CUPS behind the lock.
- **Print API gains:** `copies` (server-side repeat, idempotent per copy-set);
  `POST /v1/jobs/{id}/reprint` (re-render from stored payload + recorded template version);
  **cursor pagination + status/date filters** on `GET /v1/jobs` and audit lists.
- **Frontend types are generated:** emit OpenAPI from FastAPI and **codegen the TS client + types**;
  keep Zod only for form-level UX. CI fails on schema drift.
- **Outbound webhooks are signed:** HMAC signature + timestamp header; documented verification.
- **Migrations are field-safe:** forward-only, **backup-before-migrate**, refuse downgrade,
  health-gate the app until migration completes (amends P1.1).
- **Per-appliance unique secret:** every deployed box gets a distinct `VIBE_PRINT_SECRET` — never a
  product-wide default; enforced at provisioning (Phase 27).

### Phase 25 — CI/CD & supply chain
- P25.1 GitHub Actions (KisaesDevLab): ruff, mypy + `tsc`, unit + integration on every PR.
- P25.2 Multi-arch image build/publish (arm64 + amd64) on tag; semver + changelog.
- P25.3 Pinned deps + lockfiles (pip + pnpm); Renovate/Dependabot.
- P25.4 Supply-chain scans: `pip-audit`, `pnpm audit`, Trivy image scan; **SBOM** (CycloneDX) per release.
- P25.5 Release artifact: pinned `docker-compose.yml` + image **digest**; cosign signing (optional).
- ✅ Green PR gates; a tag yields scanned, multi-arch images + SBOM.

### Phase 26 — Local dev & API contract
- P26.1 Devcontainer / compose-dev: VirtualBackend + mock `:9100` + dummy CUPS-PDF — **no hardware needed**.
- P26.2 Seed fixtures: sample printers (incl. virtual), formats, PDF templates, sample data.
- P26.3 OpenAPI at `/openapi.json`; `/docs` gated behind auth.
- P26.4 **TS client + types codegen** wired into `web/`; CI fails on drift.
- P26.5 Makefile/taskfile: `dev`, `test`, `lint`, `build`, `seed`, `e2e`.
- ✅ `make dev` runs the full stack + UI against virtual printers; client types track the API.

### Phase 27 — Appliance provisioning & updates
- P27.1 **First-boot provisioning**: generate/set a unique secret, device name, tz; guided printer add;
  optional tunnel/Access enrollment; enable **NTP** (audit-time integrity).
- P27.2 Per-client provisioning artifact (env + pinned compose) generation flow from your side.
- P27.3 **Update mechanism**: pull pinned image digest → `compose up`; **backup-before-migrate** →
  migrate → health-gate; **rollback** to prior digest on failed `/readyz`.
- P27.4 `/v1/version` (app + schema + image digest) surfaced in the Device UI.
- P27.5 Update runbook (planned-maintenance / printer-quiet window).
- ✅ A fresh box self-provisions to working state; updates apply safely and roll back on failure.

### Phase 28 — Fleet observability & remote diagnostics (recommended)
- P28.1 Opt-in **heartbeat/phone-home** per box: app version, uptime, printer-reachability summary,
  queue depth, error counts — to an endpoint you control. **Never print payloads.**
- P28.2 Diagnostics bundle export (PII-free logs, config snapshot, printer status) for support.
- P28.3 Printer-offline alerting (down > threshold) via the signed webhook.
- P28.4 `/metrics` documented as a scrape target for a central Prometheus if you run one.
- ✅ You can tell, for any client box, whether it and its printers are healthy — without shell access.

### Phase 29 — Compliance & data protection (§7216 / GLBA)
- P29.1 **PII minimization**: `jobs.payload` + audit hold the minimum; optional mode storing a
  **content hash + metadata** instead of full payload once printed.
- P29.2 **Encryption at rest** for DB + asset volume (SQLCipher or host/volume encryption).
- P29.3 **Log redaction**: never log payload bodies or merged `data`; logs carry ids + metadata only;
  enforced by a redaction filter + tested.
- P29.4 **Retention/erasure**: configurable payload retention (default short), longer audit retention;
  on-demand purge of a job's/client's data; documented.
- P29.5 **`print/raw` disabled by default** (per-printer opt-in) — it streams unvalidated bytes to hardware.
- P29.6 Data-flow + retention doc for the Vibe Shield / §7216 file.
- ✅ A printed job leaves no unnecessary PII at rest; logs are PII-free; retention enforced.

### Phase 30 — Web hardening & CUPS lockdown
- P30.1 **CSP + security headers** on `/admin`: strict CSP (blunts XSS→secret theft from
  sessionStorage), frame-ancestors/`X-Frame-Options` (clickjacking), `Referrer-Policy`, HSTS under TLS.
- P30.2 Document the httpOnly-cookie-for-secret option vs sessionStorage tradeoff.
- P30.3 **CUPS lockdown**: disable cupsd web admin / bind `:631` to localhost; no remote admin surface.
- P30.4 **Render pool**: bounded WeasyPrint concurrency + queue so preview/PDF can't exhaust a Pi.
- P30.5 Preview endpoints independently rate-limited + size-bounded.
- ✅ Admin UI passes a headers/CSP audit; CUPS exposes no admin surface; renders can't starve the box.

## Execution model & build order
- **Critical path:** P0 → P1 → P2/P3 → P4 (+P6) → P7/P8 → P10 → P11 → P12 → P13 → P17 → UI phases.
- **Parallelizable:** P5 (USB), P9 (assets), P15 (discovery), P25/P26 (CI/dev) alongside the backend;
  P28–P30 land after the core path but **before any client ship**.
- **Gating:** P16 (tunnel) and P27 (provisioning) gate any remote/field deployment.
- **Definition of Done (every phase):** lint + typecheck clean, phase tests green, README touched,
  no new high/critical scan findings.
- **Autonomous execution:** drive with a phase-gated `CLAUDE.md` (QUESTIONS.md for blockers, the ✅
  acceptance line as the gate) — generate it from this plan before starting.

---

## Suggested layout

```
vibe-print/
  app/
    main.py
    config/            settings, yaml import/export
    db/                models, migrations, retention
    registry/          db-backed registry, optimistic concurrency, startup validation
    backends/          base, escpos_network, escpos_usb, cups, virtual, locks
    templating/        jinja_env, format_merge, pdf_render(weasyprint, sandboxed)
    render/            escpos_render(codepage,raster), preview
    assets/            fs storage + serving + refcount
    queue/             store(sqlite), worker(per-printer), idempotency, retention, shutdown
    auth/              secret.py, realip.py, access_jwt.py, ratelimit.py
    api/               print, printers, jobs
    admin/             device, printers, formats, templates, assets, config, secret, remote_access
    obs/               logging, metrics, audit, webhook
  web/
    src/ app-shell.tsx
      routes/   device/ printers/ formats/ templates/
      components/ forms, editors(codemirror), previews, indicators, secret-gate
      api/  query hooks, zod schemas, apiClient(secret + idempotency)
  deploy/   docker-compose.yml (+ cloudflare, caddy profiles), Caddyfile, cloudflared/
  tests/
  config/printers.yaml
  Dockerfile  README.md
```

---

## Appendix A — Gap Review Findings

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | Durable retry queue is at-least-once → crash mid-print can **reprint a receipt** | High | Decision 16 + P10.4: mid-send → `uncertain`, no auto-retry; operator resolve (P21.4) |
| 2 | Concurrent jobs to one ESC/POS socket/USB **corrupt/interleave** output | High | P3.4 per-printer lock; P10.2 per-printer serialization; P24.6 soak asserts |
| 3 | Client retries on network blip → **duplicate prints** | High | P10.3 idempotency keys; P11.1 honor; P24.2 dedupe/conflict tests |
| 4 | **CUPS topology** (host vs in-container) unspecified — blocks deploy | High | Decision 13: in-container CUPS; P6.1, P23.1 |
| 5 | WeasyPrint renders user HTML → **SSRF / remote fetch / hang** | High | P7.4 remote-fetch lockdown + render timeout/memory cap; P22.2, P24.4 |
| 6 | Shared secret could default to empty → **service open** | High | P1.3 / P12.1 fail-fast on unset secret |
| 7 | "Printed" overstated — bytes-sent ≠ paper | Med | Delivery-semantics model; CUPS job-state polling (P6.2); documented |
| 8 | Real client IP lost behind tunnel → **useless audit / spoofable rate limit** | Med | P12.3 trusted-proxy real-IP; per-IP limits; P24.3 spoof test |
| 9 | **Non-ASCII / codepage** failures on thermal | Med | P4.3 codepage + transliteration; P24.1 |
| 10 | Image/logo not scaled/dithered to **paper width (dots)** | Med | `paper_width_dots`; P8.1 raster scaling/dither |
| 11 | Format uses a feature the printer **lacks** | Med | Capabilities (P4.4) + P8.2 reject/degrade; `unsupported_for_printer` |
| 12 | SQLite/audit/jobs **grow unbounded** | Med | Retention windows + pruning (P10.7, P21.1) |
| 13 | **Asset storage** location undefined | Med | Decision 14: filesystem volume; P9 |
| 14 | **Backpressure** — no queue cap | Med | P10.5 `queue_full` 429 |
| 15 | **Graceful shutdown** could drop/dupe in-flight | Med | P10.6 drain on SIGTERM; P23.4 stop timeout |
| 16 | LAN traffic (incl. secret) **plaintext** | Med | Decision 15: Caddy/TLS front; P22.6 |
| 17 | PDF **fonts** missing in container → boxes | Med | Bundled fonts; P23.1 |
| 18 | Concurrent admin edits **clobber** | Low | Optimistic concurrency (P2.2, P13.1, UI 409 handling) |
| 19 | USB **hotplug/disconnect** instability | Low | P5.2 identity + reconnect |
| 20 | No **readiness** vs liveness distinction | Low | `/readyz` (P0.2) for healthchecks |
| 21 | Dead-letter failures **silent** | Low | P14.2 surfacing + P14.4 optional webhook |
| 22 | **DB backup** path absent (config export ≠ full state) | Low | P22.7 B2 dump + asset sync + restore drill |
| 23 | No machine-readable **error contract** | Low | Stable error envelope + codes |

**Consciously deferred (not gaps for v1):** multi-tenant isolation, multi-node/HA, full RBAC
(single shared secret by design), print-job scheduling/quotas, non-ESC/POS protocols (StarPRNT)
— add per printer fleet if needed, ZPL/label-specific layout, i18n of the admin UI.

---

## Appendix B — Second-pass gap review findings

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| B1 | No CI/CD, lint/type gates, multi-arch release pipeline | High | Phase 25 |
| B2 | No supply-chain scanning / SBOM / pinned deps | High | Phase 25 |
| B3 | No safe **appliance update/upgrade** path for shipped boxes | High | Phase 27 (backup-before-migrate, rollback) |
| B4 | No first-boot **provisioning**; risk of shared/default secret | High | Phase 27 (unique secret, guided setup, NTP) |
| B5 | **PII at rest** in jobs/audit and **payloads in logs** (§7216/GLBA) | High | Phase 29 (minimization, redaction, retention) |
| B6 | No **encryption at rest** for DB/assets | High | Phase 29.2 |
| B7 | Admin UI lacks **CSP/security headers**; XSS could steal the secret | High | Phase 30.1–30.2 |
| B8 | `print/raw` streams unvalidated bytes by default | Med | Phase 29.5 (off by default, per-printer opt-in) |
| B9 | Concurrency model wrongly serialized **CUPS** too | Med | Amendment: lock ESC/POS only; CUPS parallel |
| B10 | No **reprint** / **copies** support | Med | Amendment: reprint endpoint + `copies` |
| B11 | List endpoints (jobs/audit) **unpaginated** | Med | Amendment: cursor pagination + filters |
| B12 | Hand-maintained Zod can **drift** from the API | Med | Phase 26 (OpenAPI → TS codegen) |
| B13 | No **fleet visibility** — can't tell if a client box/printer is down | Med | Phase 28 (heartbeat, alerts, diagnostics) |
| B14 | CUPS **:631 admin** surface exposed in-container | Med | Phase 30.3 |
| B15 | WeasyPrint renders can **exhaust CPU/RAM** on a Pi | Med | Phase 30.4 (render pool) |
| B16 | Outbound webhooks **unsigned** | Low | Amendment: HMAC signing |
| B17 | No hardware-free **local dev loop / fixtures** | Med | Phase 26 |
| B18 | Audit **time integrity** on offline boxes (drift) | Low | Phase 27.1 (NTP) |
| B19 | No machine-readable **version** (app/schema/digest) | Low | Phase 27.4 (`/v1/version`) |

**Still deferred (intentional):** printer failover/pools, job priority/scheduling, multi-tenant
isolation, HA/multi-node, StarPRNT/ZPL backends, UI i18n, tamper-evident (hash-chained) audit.

---

## Notes / gotchas
- Tunnel is **inbound**; printer connections are **outbound** on the LAN — independent.
- Keep `/healthz`+`/readyz` open and outside Access, or edge/health checks fail.
- `print/raw` is ESC/POS-only — reject for CUPS.
- Record the **format/template version** per job for reproducible reprints.
- Keep preview server-rendered; never re-render in the browser.
- `TUNNEL_TOKEN` and Access service-token secrets are credentials — env only, never committed.
- The public **subdomain is provisioned in the Cloudflare dashboard** (ingress route + proxied
  DNS CNAME) at setup; the UI only displays it. No Cloudflare API token lives on the appliance.
- If you later add **Star** printers, plan a StarPRNT backend (deferred above) — they aren't plain ESC/POS.
