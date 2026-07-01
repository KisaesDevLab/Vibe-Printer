[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/I3D3227TTP)

# Vibe Print

[![CI](https://github.com/KisaesDevLab/Vibe-Printer/actions/workflows/ci.yml/badge.svg)](https://github.com/KisaesDevLab/Vibe-Printer/actions/workflows/ci.yml)

**LAN print routing gateway.** Callers send a payload over HTTP, pick a **printer by integer id**,
and the gateway routes the job to the right device — thermal receipt printers, label printers, or
office printers — rendering receipts, labels, and PDFs from reusable templates. A React admin UI
configures everything. It ships as a self-hosted Docker appliance for a Raspberry Pi or NucBox.

```
   POST /v1/print  {printer: 1, format: 2, data:{…}}
        │
        ▼
┌──────────────────────────────────────────────────────────┐
│  Vibe Print (FastAPI)                                      │
│  auth → templating (Jinja) → render → durable queue       │
│                                   │                        │
│        ┌──────────────┬──────────┼───────────┬─────────┐  │
│        ▼              ▼           ▼           ▼         ▼  │
│   ESC/POS TCP    ESC/POS USB    CUPS/PDF    ZPL label  Star│
└──────────────────────────────────────────────────────────┘
```

---

## Table of contents

- [Features](#features)
- [Quick start (local, no hardware)](#quick-start-local-no-hardware)
- [Production deployment](#production-deployment)
- [Printer setup](#printer-setup)
  - [ESC/POS network (TCP :9100)](#escpos-network-tcp-9100)
  - [ESC/POS USB](#escpos-usb)
  - [CUPS / office printers (PDF)](#cups--office-printers-pdf)
  - [ZPL label printers](#zpl-label-printers)
  - [Star printers](#star-printers)
  - [Printer pools / failover](#printer-pools--failover)
- [Authentication](#authentication)
- [API reference](#api-reference)
- [Template variables](#template-variables)
- [Document format schema (thermal)](#document-format-schema-thermal)
- [PDF templates (office)](#pdf-templates-office)
- [Configuration](#configuration-environment-variables)
- [Remote access](#remote-access)
- [Backup & restore](#backup--restore)
- [Observability & compliance](#observability--compliance)
- [Development](#development)
- [Project status](#project-status)
- [License](#license)

---

## Features

- **Printer types:** `escpos_network` (TCP :9100), `escpos_usb`, `cups` (office via in-container
  CUPS), `ipp_network` (**direct IPP** — no CUPS queue; "reachable" is a real IPP query),
  `zpl_network` (Zebra labels), `star_network` (Star Line Mode), `virtual` (dev/test), plus
  `pool` (failover / round-robin). CUPS device URIs **auto-(re)provision on startup** (durable
  across rebuilds); a **Provision** button is in the Printers tab.
- **Office documents:** render from HTML/CSS templates, **overlay variables onto an uploaded base
  PDF** (visual drag-and-drop editor; text/QR/image fields), **or** print finished **PDF /
  PostScript / PCL** files directly (`/v1/print/file`).
- **Cash drawer:** `pulse` element (configurable pin 2/5 + on/off timing) or a one-click
  **Open drawer** action (`/v1/admin/printers/{id}/open-drawer`) on ESC/POS & Star printers.
- **Reliable delivery:** durable SQLite queue, **per-printer serialization** (no interleaved
  receipts), **idempotency keys**, retry with backoff, and **mid-send → `uncertain`** (never
  auto-reprints a financial receipt).
- **Templating:** sandboxed Jinja2 over a JSON element schema (thermal) and HTML/CSS → PDF via
  WeasyPrint (office). Server-rendered previews (PNG/PDF). QR / barcode / image / tables.
- **Scheduling:** job `priority`, not-before `scheduled_at`, per-printer **daily quotas**.
- **Admin UI:** secret-gated SPA at `/admin` — Printers, Document Formats (drag-reorder **visual
  element builder**), PDF Templates, **PDF Overlays** (pdf.js WYSIWYG), Jobs, **Remote Access**,
  Device. Each content type supports **edit / delete / test-print to a chosen printer** with live
  previews. English + Spanish.
- **Ships with defaults:** bundled formats/templates (Stripe receipt, File Routing Sheet, Invoice,
  #10 Envelope, 4×3 mailing label) loaded **create-if-missing** on startup so a fresh appliance is
  usable immediately.
- **Remote access from the UI:** run a **Cloudflare Tunnel** as a managed process — **quick** mode
  (instant `*.trycloudflare.com` URL, no account) or **named** (token for a stable hostname);
  LAN + Cloudflare work **at the same time**; optional **Cloudflare Access** JWT enforced only on
  tunnelled requests. Also Caddy LAN-TLS and Tailscale.
- **Security & compliance:** shared-secret bearer auth, optional **Cloudflare Access** JWT, strict
  CSP, WeasyPrint SSRF lockdown, **tamper-evident hash-chained audit**, optional **SQLCipher at
  rest**, payload-hash PII mode, log redaction, configurable retention.
- **Operations:** signed failure/offline **webhooks**, fleet **heartbeat** + diagnostics bundle,
  Prometheus `/metrics`, LAN **discovery**, first-boot **provisioning**, safe **self-update** with
  rollback, and **B2 backup/restore**.
- **Packaged image:** multi-arch (amd64 + arm64) published to **GHCR** — `ghcr.io/kisaesdevlab/vibe-printer`.

---

## Quick start (local, no hardware)

Requires Python 3.12 and Node 24.

```bash
git clone https://github.com/KisaesDevLab/Vibe-Printer.git
cd Vibe-Printer

python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

export VIBE_PRINT_SECRET=dev-secret              # the service refuses to boot without this
python -m app.seed                               # sample virtual printer + receipt format + PDF template
uvicorn app.main:app --reload --port 8080        # or: make dev
```

Print to the seeded **virtual** printer (id 1) and watch the job complete:

```bash
SECRET=dev-secret
JOB=$(curl -s localhost:8080/v1/print \
  -H "Authorization: Bearer $SECRET" \
  -H "Idempotency-Key: $(python -c 'import uuid;print(uuid.uuid4())')" \
  -d '{"printer":1,"data":{"company":"Acme","date":"2026-06-27",
       "lines":[{"name":"Widget","qty":"2","amt":"9.98"}],"total":"9.98",
       "url":"https://example.com/r/1"}}' | python -c 'import sys,json;print(json.load(sys.stdin)["job_id"])')

curl -s localhost:8080/v1/jobs/$JOB -H "Authorization: Bearer $SECRET"
```

The virtual backend writes the rendered ESC/POS bytes to `data/virtual/printer-1.bin`. The admin UI
dev server is `cd web && npm install && npm run dev` (proxies the API); in production the UI is built
into the app and served at `/admin`.

> **"Sent" ≠ "printed".** ESC/POS over TCP/USB is fire-and-forget — a job reaching `done` with
> `delivery: "sent"` means bytes were accepted by the printer, not that paper emerged. CUPS jobs are
> polled to true completion (`delivery: "completed"`). Always observe the final state via
> `GET /v1/jobs/{id}`, not the enqueue response.

---

## Production deployment

Target: a Raspberry Pi (arm64) or NucBox/mini-PC (amd64) on the same LAN as the printers, running
Docker on stock Ubuntu 24.04.

```bash
cd deploy
cp .env.example .env          # set a UNIQUE VIBE_PRINT_SECRET per appliance
docker compose up -d --build  # build locally; or pull the published image (below)
```

**Or pull the prebuilt multi-arch image from GHCR** (no local build) — set
`VIBE_PRINT_IMAGE` and skip `--build`:

```bash
VIBE_PRINT_IMAGE=ghcr.io/kisaesdevlab/vibe-printer:v0.1.0 docker compose up -d
# tags: :latest (amd64, every main push) · :vX.Y.Z (amd64+arm64, on release tags) · :<sha>
```

The image bundles WeasyPrint (pango/cairo), fonts, libusb, an in-container CUPS (localhost), and
`cloudflared` (for the UI-managed tunnel). Data lives in the `vibe-data` volume (`/data`: SQLite DB
+ assets + backups), so it persists across upgrades.

Compose **profiles**:

| Profile | Command | What it adds |
|---|---|---|
| _(default)_ | `docker compose up -d` | LAN-only gateway on `:8080` |
| `caddy` | `docker compose --profile caddy up -d` | Caddy TLS front (`deploy/Caddyfile`) |
| `cloudflare` | `docker compose --profile cloudflare up -d` | Outbound Cloudflare Tunnel (set `TUNNEL_TOKEN`); no inbound ports |

**Updates** are operator-run (no auto-update timers):

```bash
cd deploy
./upgrade.sh ghcr.io/you/vibe-print@sha256:<digest>   # pull → health-gate /readyz → rollback on failure
```

The app takes a DB backup before applying any migration, and migrations are forward-only.

### Native install (no Docker, e.g. Raspberry Pi)

Docker is the primary/tested path, but the app runs natively too — and the easiest way needs **no
downloading and no git**. On the Pi, open **Terminal** and paste this **one line** (don't add `sudo`):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/KisaesDevLab/Vibe-Printer/main/deploy/install-native.sh)
```

It downloads itself, installs everything, and prints the **URL + secret** at the end. It'll ask for
your password when it needs admin rights. To update later, paste:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/KisaesDevLab/Vibe-Printer/main/deploy/update-native.sh)
```

The installer adds the system libs (WeasyPrint, libusb, CUPS, build deps), provisions a **Python 3.12
venv via [uv](https://docs.astral.sh/uv/)**, builds the admin UI into `app/static`, generates a secret
in `/etc/vibe-print.env`, and installs+starts a `vibe-print` **systemd** service. Differences from Docker:

- **Office printers use the host's system CUPS** (`http://localhost:631` / `lpadmin`) instead of an
  in-container cupsd — register those queues in Vibe Print as type `cups`.
- **The UI-managed Cloudflare tunnel works natively** — the installer drops `cloudflared` into
  `/usr/local/bin`, so quick/named tunnels start from the Remote Access tab just like in Docker.
- **SQLCipher-at-rest** isn't installed on arm64 (no wheel); use disk/volume encryption instead.
- Manage it with `systemctl {status,restart} vibe-print` and `journalctl -u vibe-print -f`.

---

## Printer setup

Add printers in the admin UI (**Printers → Add printer**) or via the Admin API. Every type below
includes a `curl` example. Replace `$SECRET` and host/ids as needed.

### ESC/POS network (TCP :9100)

The most common thermal receipt setup. Find the printer's IP (its self-test slip, your router's DHCP
table, or the built-in scanner below), then:

```bash
curl -s localhost:8080/v1/admin/printers -H "Authorization: Bearer $SECRET" -d '{
  "name":"Front Counter",
  "params":{"type":"escpos_network","host":"192.168.1.50","port":9100,
            "columns":48,"paper_width_dots":576,"encoding":"cp437","cut":true},
  "default_format_id":1
}'
```

**Discover** open `:9100` / IPP printers on a subnet:

```bash
curl -s localhost:8080/v1/admin/discover -H "Authorization: Bearer $SECRET" \
  -d '{"subnet":"192.168.1.0/24"}'
```

Key params: `columns` (text width, usually 48 for 80 mm / 32 for 58 mm), `paper_width_dots`
(576 for 80 mm @ 203 dpi, 384 for 58 mm), `encoding`/`codepage`, `cut`.

### ESC/POS USB

For a USB-attached receipt printer. You need the device's USB **vendor/product id** and must pass the
device into the container.

1. Find the ids on the host: `lsusb` → e.g. `ID 04b8:0e28 Seiko Epson Corp.` → vendor `0x04b8`,
   product `0x0e28`.
2. Pass the USB bus into the container — uncomment in `deploy/docker-compose.yml`:
   ```yaml
   devices:
     - "/dev/bus/usb:/dev/bus/usb"
   ```
   (or scope to the specific device). A udev rule granting access is recommended:
   ```
   # /etc/udev/rules.d/99-vibe-print.rules
   SUBSYSTEM=="usb", ATTRS{idVendor}=="04b8", ATTRS{idProduct}=="0e28", MODE="0666"
   ```
3. Register it (ids are integers — `0x04b8` = 1208, `0x0e28` = 3624; or send hex via the UI):
   ```bash
   curl -s localhost:8080/v1/admin/printers -H "Authorization: Bearer $SECRET" -d '{
     "name":"USB Receipt",
     "params":{"type":"escpos_usb","vendor_id":1208,"product_id":3624,"columns":48}
   }'
   ```

The backend identifies the device by vendor/product (and optional `serial`) and survives unplug/replug.

### CUPS / office printers (PDF)

For full-page documents on laser/inkjet printers. CUPS runs **inside the container**. Point a queue at
the physical printer (driverless IPP Everywhere is easiest), then register it.

```bash
# 1) register the printer (queue name + media)
PID=$(curl -s localhost:8080/v1/admin/printers -H "Authorization: Bearer $SECRET" -d '{
  "name":"Office Laser","params":{"type":"cups","queue":"HP_LaserJet","media":"A4"},
  "default_template_id":1}' | python -c 'import sys,json;print(json.load(sys.stdin)["id"])')

# 2) provision the CUPS queue (driverless)
curl -s localhost:8080/v1/admin/printers/$PID/provision-queue -H "Authorization: Bearer $SECRET" \
  -d '{"device_uri":"ipp://printer.local:631/ipp/print","make_model":"everywhere"}'
```

CUPS jobs are submitted concurrently (its own spooler) and polled to true completion. The CUPS web
admin is disabled and `:631` is bound to localhost — no remote admin surface.

**Output / input trays.** For CUPS and direct-IPP printers you can pick an **output tray**
(`output_bin`, e.g. `face-down`, `tray-1`, `stacker-1`, `mailbox-1`) and an **input tray**
(`input_tray`, e.g. `auto`, `tray-2`, `manual`) in the Printers tab (or via params). CUPS sends them
as `output-bin` / `media-source`; direct IPP sends `output-bin` and `media-col{media-source}`. Use
the printer's own tray names — the UI offers common values as suggestions.

You can print office output two ways: render an [HTML/CSS template](#pdf-templates-office) with
`/v1/print`, or send a **finished PDF / PostScript / PCL** with
[`/v1/print/file`](#post-v1printfile). Example printing an existing PDF:

```bash
curl -s localhost:8080/v1/print/file -H "Authorization: Bearer $SECRET" -d "{
  \"printer\": $PID, \"content_type\": \"pdf\", \"media\": \"Letter\",
  \"content\": \"$(base64 -w0 invoice.pdf)\"
}"
```

### ZPL label printers

For Zebra-style label printers over TCP :9100. Elements render to ZPL II.

```bash
curl -s localhost:8080/v1/admin/printers -H "Authorization: Bearer $SECRET" -d '{
  "name":"Shipping Labels",
  "params":{"type":"zpl_network","host":"192.168.1.70","port":9100,
            "dpmm":8,"label_width_dots":812}
}'
```

`dpmm` = dots per mm (8 ≈ 203 dpi, 12 ≈ 300 dpi). QR/CODE128 render natively (`^BQN` / `^BC`).

**Raster mode** (`"raster": true`, or the toggle in the Printers tab) renders the whole label to a
1-bit bitmap sent as a ZPL `^GFA` graphic field — so text, QR, images, rules and tables print as
graphics regardless of the printer's resident fonts. Set `label_width_dots` (and optionally
`label_height_dots`, the max canvas, auto-cropped to content). Linear barcodes use native ZPL, so
turn raster off for those.

A **raster ZPL printer also accepts PDF templates and overlays**: the HTML/CSS template is rendered
to PDF (WeasyPrint), each page is rasterized (pypdfium2) to the label width, and sent as `^GFA`. So
you can design a label as a PDF template and print it on a Zebra. (Without raster mode, ZPL printers
reject templates with `unsupported_for_printer`.)

### Star printers

Star printers (Star Line Mode) over TCP :9100. Text/alignment/cut are modeled.

```bash
curl -s localhost:8080/v1/admin/printers -H "Authorization: Bearer $SECRET" -d '{
  "name":"Star TSP","params":{"type":"star_network","host":"192.168.1.71","port":9100,"columns":48}
}'
```

### Printer pools / failover

Route to a group of ESC/POS-family members. `failover` picks the first reachable member;
`round_robin` rotates. Capabilities are the safe intersection of members.

```bash
curl -s localhost:8080/v1/admin/printers -H "Authorization: Bearer $SECRET" -d '{
  "name":"Counter Pool",
  "params":{"type":"pool","members":[2,3],"strategy":"failover"}
}'
```

Print to the pool's id like any printer; the gateway resolves a live member at send time.

---

## Authentication

- All `/v1/*` routes require `Authorization: Bearer <secret>`. `/healthz`, `/readyz`, `/metrics`,
  and the `/admin` UI are open.
- The secret is set via `VIBE_PRINT_SECRET` and compared in constant time. **The service refuses to
  start if it is unset/empty** — it never runs open. Use a unique secret per appliance.
- The admin UI prompts for the secret once and holds it in `sessionStorage` (no cookies → no CSRF).
- Optional **Cloudflare Access** JWT enforcement on `/v1/admin/*` (see [Remote access](#remote-access)).
- Real client IP is trusted from `CF-Connecting-IP` / `X-Forwarded-For` **only** when the peer is in
  `VIBE_PRINT_TRUSTED_PROXIES`; rate limiting and audit use the real IP.

---

## API reference

Base URL: `http://<host>:8080`. All examples assume `-H "Authorization: Bearer $SECRET"`.
Interactive docs: `GET /openapi.json` (and `/docs`). A typed TS client is generated into
`web/src/api-types.ts`.

### Printing

#### `POST /v1/print`

Enqueue a print job. Provide **one of** `document` (inline), `format` (id), or `template` (id, CUPS);
omit all to use the printer's default. Returns the enqueue result — observe the outcome via the job.

| Field | Type | Notes |
|---|---|---|
| `printer` | int | **required** — printer id |
| `document` | object | inline element doc `{ "elements": [...] }` (thermal/label) |
| `format` | int | saved format id (thermal/label) |
| `template` | int | saved PDF template id (CUPS) |
| `overlay` | int | saved PDF-overlay id — stamps `data` onto an uploaded base PDF |
| `data` | object | merged into the template via Jinja |
| `copies` | int | 1–50 (default 1) |
| `priority` | int | −100…100, higher runs first (default 0) |
| `scheduled_at` | string | ISO-8601 not-before time |

Header `Idempotency-Key: <uuid>` (recommended): an identical key+payload returns the original job;
the same key with a different payload → `idempotency_conflict`.

```bash
curl -s localhost:8080/v1/print -H "Authorization: Bearer $SECRET" \
  -H "Idempotency-Key: 9d8f…" \
  -d '{"printer":1,"format":2,"data":{"company":"Acme","total":"24.48"},"copies":1,"priority":10}'
# → {"job_id":"<uuid>","status":"queued"}
```

#### `POST /v1/print/raw`

Stream base64 bytes straight to an ESC/POS/ZPL/Star printer. **Disabled per-printer by default** —
enable with `allow_raw: true`. Rejected for CUPS.

```bash
curl -s localhost:8080/v1/print/raw -H "Authorization: Bearer $SECRET" \
  -d '{"printer":1,"data":"G0BoZWxsbwo="}'
```

#### `POST /v1/print/file`

Print a **finished document** (PDF / PostScript / PCL) to an office (CUPS) printer — no template
rendering. PDF and PostScript are auto-filtered (and converted for IPP-Everywhere printers); PCL is
passed through unfiltered to a PCL-capable device. Honors `Idempotency-Key`.

| Field | Type | Notes |
|---|---|---|
| `printer` | int | **required** — a CUPS printer |
| `content` | string | **required** — base64-encoded document bytes |
| `content_type` | enum | `pdf` (default) · `postscript` · `pcl` |
| `copies` | int | 1–50 |
| `media` | string | e.g. `A4`, `Letter` |
| `priority` / `scheduled_at` | int / string | as for `/v1/print` |

```bash
curl -s localhost:8080/v1/print/file -H "Authorization: Bearer $SECRET" -d "{
  \"printer\": 3, \"content_type\": \"pdf\", \"media\": \"Letter\",
  \"content\": \"$(base64 -w0 invoice.pdf)\"
}"
```

A printer advertises what it accepts in `GET /v1/printers` → `capabilities.document_formats`
(non-office printers return an empty list and reject the call with `unsupported_for_printer`). The
default `MAX_BODY_BYTES` is 5 MiB — raise it for larger documents.

#### `POST /v1/print/preview`

Server-render a preview without printing. Returns `image/png` (thermal) or `application/pdf`.
Accepts inline `document` / `html`+`css` or a saved `format`/`template`, plus `data`.

```bash
curl -s localhost:8080/v1/print/preview -H "Authorization: Bearer $SECRET" \
  -d '{"format":2,"data":{"company":"Acme"}}' -o preview.png
```

### Jobs

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/jobs/{id}` | status, `delivery`, attempts, error |
| `POST` | `/v1/jobs/{id}/reprint` | re-render & re-enqueue from the stored payload + recorded version |

Job lifecycle: `queued → rendering → printing → done | failed | dead | canceled | uncertain`.
`uncertain` = the link died after bytes began streaming; it is **never auto-retried** and requires an
operator action (resolve / requeue) in the UI or via the admin API.

### Printers & version

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/printers` | list with cached capabilities |
| `GET` | `/v1/printers/{id}/status` | live reachability (pool → per-member) |
| `GET` | `/v1/version` | app version, schema migration, image digest |

### Admin API (`/v1/admin/*`)

| Area | Endpoints |
|---|---|
| Device | `GET/PUT /device` |
| Printers | `GET/POST /printers`, `GET/PUT/DELETE /printers/{id}`, `POST /printers/{id}/test`, `POST /printers/{id}/open-drawer`, `GET /printers/{id}/status`, `POST /printers/{id}/provision-queue`, `POST /discover` |
| Formats | `GET/POST /formats`, `GET/PUT/DELETE /formats/{id}`, `POST /formats/{id}/preview` |
| Templates | `GET/POST /templates`, `GET/PUT/DELETE /templates/{id}`, `POST /templates/{id}/preview` |
| Overlays | `GET/POST /overlays`, `GET/PUT/DELETE /overlays/{id}`, `POST /overlays/{id}/preview`, `GET /overlays/{id}/base`, `GET /overlays/{id}/pages` |
| Assets | `GET/POST /assets`, `DELETE /assets/{id}` |
| Jobs | `GET /jobs` (filter `status`, `cursor`, `limit`), `POST /jobs/{id}/{cancel\|requeue\|resolve}`, `DELETE /jobs/{id}/payload` |
| Config | `POST /config/export`, `POST /config/import` (`dry_run`) |
| Audit | `GET /audit/config`, `GET /audit/print`, `GET /audit/verify` (hash chain) |
| Retention/backup | `POST /retention/prune`, `POST /backup/snapshot` |
| Fleet/remote | `GET /diagnostics`, `POST /heartbeat/test`, `GET/PUT /remote`, `GET /remote/status`, `POST /remote/tunnel/{start\|stop}` |
| Provisioning | `GET /provision/status`, `POST /provision` |

Writes use **optimistic concurrency** — include the resource's `version`; a stale write returns `409`.
List endpoints support cursor pagination (`cursor` = last seen id).

### Error envelope

Every error: `{"error":{"code","message","details?}}`. Stable machine codes:

`unauthorized` · `forbidden` · `validation_error` · `unknown_printer` · `not_found` ·
`unsupported_for_printer` · `idempotency_conflict` · `conflict` · `rate_limited` · `queue_full` ·
`quota_exceeded` · `render_error` · `printer_unreachable` · `internal_error`.

---

## Template variables

Every renderable string — thermal element values, PDF template HTML/CSS, and PDF-overlay fields —
is a **Jinja2** template merged at print time with the request body's **`data`** object (or the
saved `sample_data` for previews). The engine is **sandboxed** (no `__dunder__`/attribute escapes)
and **HTML-autoescaped** for PDF output, so values from `data` can't inject markup or break out.

### Where to reference variables, and how

| Surface | Syntax | Notes |
|---|---|---|
| **Thermal format** (`elements[].value`, table `row` cells, `qr`/`barcode` value, `image` asset) | `{{ data.field }}`, nested `{{ data.client.name }}` | merged from `data` |
| **PDF template** (HTML + CSS) | `{{ data.field }}` **or** top-level `{{ field }}` | full Jinja: `{% for %}`, `{% if %}`, filters |
| **PDF overlay** (field `value`) | `{{ data.field }}` | text/QR field values |

In **PDF templates** the request fields are exposed both under `data.*` and at the top level, so a
designer-authored template can use `{{ client.name }}` or `{{ data.client.name }}` interchangeably.

### `data` is what you send

```jsonc
POST /v1/print
{ "printer": 1, "format": 2,
  "data": { "company": "Acme", "total": "24.48",
            "lines": [ {"name": "Widget", "qty": "2", "amt": "9.98"} ] } }
```
…then `{{ data.company }}`, `{{ data.total }}`, and a row loop over `data.lines` resolve. For a
preview with no `data`, the format/template's saved `sample_data` is used.

### Jinja you can use

- **Interpolation:** `{{ data.x }}`, nested `{{ data.a.b }}`.
- **Loops** (PDF/HTML): `{% for li in data.lines %}{{ li.name }} {{ li.amt }}{% endfor %}`.
  Thermal tables loop declaratively instead — `"rows_from": "data.lines"` + `"row": ["{{ item.name }}", "{{ item.amt }}"]`.
- **Conditionals:** `{% if data.url %}…{% endif %}`.
- **Defaults / filters:** `{{ data.note | default('—') }}`, `{{ data.name | upper }}`.
- **QR images in PDF templates:** `<img src="{{ data.url | qr_data_uri(box_size=4, ec='H') }}">`
  (the `qr_data_uri` filter returns an embedded PNG data-URI). Thermal/overlay output uses the
  dedicated `qr` element/field instead.

### Missing variables

- **Thermal formats & overlays** are **strict** — an undefined variable raises `render_error`, so a
  typo in the controlled element schema fails loudly. Keep `data` complete or use the `default` filter.
- **PDF/HTML templates** are **lenient** (optional-friendly) — a missing variable renders empty, is
  falsy in `{% if %}`, and iterates to nothing in `{% for %}`. So `{% if logo_url %}` and
  `{% for s in surcharges %}` work even when those optional fields aren't supplied.

Capability-aware rendering also rejects elements a printer can't do (e.g. `qr` on a non-QR printer)
with `unsupported_for_printer`.

---

## Document format schema (thermal)

A document is `{ "elements": [ … ] }`. String fields are Jinja templates merged with the request
`data` (sandboxed, autoescaped for HTML).

```jsonc
{
  "elements": [
    {"type":"text","value":"{{ data.company }}","align":"center","bold":true,"size":[2,2]},
    {"type":"text","value":"Receipt {{ data.date }}","align":"center"},
    {"type":"rule"},
    {"type":"table","cols":[24,10,12],"align":["left","right","right"],
     "rows_from":"data.lines","row":["{{ item.name }}","{{ item.qty }}","{{ item.amt }}"]},
    {"type":"text","value":"TOTAL {{ data.total }}","align":"right","bold":true},
    {"type":"qr","value":"{{ data.url }}","size":6,"ec":"M","native":false},
    {"type":"barcode","format":"CODE128","value":"{{ data.ref }}"},
    {"type":"image","asset":"logo.png"},
    {"type":"pulse"},
    {"type":"feed","lines":2},
    {"type":"cut"}
  ]
}
```

| Element | Fields |
|---|---|
| `text` | `value`, `align` (left/center/right), `bold`, `size` `[w,h]` (1–8) |
| `rule` | — (full-width separator) |
| `table` | `cols` (widths), `align`, static `rows` **or** `rows_from` (data path) + `row` (cell templates) |
| `qr` | `value`, `size` (1–16), `native` (printer QR command vs raster image), `ec` (L/M/Q/H), `model` (1/2), `center` |
| `barcode` | `format` (CODE128/EAN13/CODE39/UPC-A), `value` |
| `image` | `asset` (uploaded asset name; scaled/dithered to paper width) |
| `feed` | `lines` |
| `pulse` | `pin` (2 or 5), `on_ms`, `off_ms` — cash-drawer kick |
| `cut` | — |

Capability-aware: an element a printer can't do (e.g. QR on a printer without QR) returns
`unsupported_for_printer`. Formats are **versioned**, and the version is recorded on each job for
reproducible reprints.

---

## PDF templates (office)

CUPS printers render an HTML/CSS template to PDF via WeasyPrint. `data` is merged with Jinja
(autoescaped). A built-in **`qr_data_uri`** filter embeds a scannable QR:

```html
<h1>{{ data.title }}</h1>
<table>
  {% for line in data.lines %}<tr><td>{{ line.name }}</td><td>{{ line.amt }}</td></tr>{% endfor %}
</table>
<img src="{{ data.url | qr_data_uri(box_size=4, ec='H') }}" alt="QR">
```

`page_setup` controls `size` (e.g. `A4`) and `margins`. WeasyPrint is **locked to local assets** —
remote URL fetches are blocked (SSRF), and renders are time/memory-bounded.

---

## PDF overlay templates

When you have a fixed **base PDF** — a pre-printed form, letterhead, or government form — you can
overlay dynamic values onto it instead of recreating it in HTML.

**In the admin UI (Overlays tab):**
1. Upload the base PDF.
2. It renders in the browser (pdf.js). Click **+ Text / + QR / + Image**, then **drag** each field
   onto the page to position it. Pick the page with the page navigator.
3. Bind each field to a variable (`{{ data.name }}`), set font/size/align/color, and enter sample
   data. **Preview PDF** stamps the values live; **Save** versions the overlay.

**Field types:** `text` (Jinja value), `qr` (Jinja value → scannable QR), `image` (an uploaded
asset). Coordinates are stored in PDF points (top-left origin), so they're resolution-independent
and multi-page aware.

**Print it** to any PDF-capable printer (CUPS, or `virtual` in dev):

```bash
curl -s localhost:8080/v1/print -H "Authorization: Bearer $SECRET" \
  -d '{"printer":3,"overlay":1,"data":{"name":"Acme LLC","url":"https://example.com/r/1"}}'
```

At print time the values are stamped onto the original PDF with reportlab + pypdf (PDF/PS auto-filter
through CUPS). PDF/PostScript text is selectable in the output; the base content is preserved.

---

## Recipe: Stripe payment receipts

A ready-made **thermal format** and **PDF template** for Stripe payments live in
[`config/stripe-receipts.yaml`](config/stripe-receipts.yaml). Import them onto any appliance:

```bash
curl -s localhost:8080/v1/admin/config/import -H "Authorization: Bearer $SECRET" \
  -d "{\"dry_run\":false,\"yaml\":$(python -c 'import json,sys;print(json.dumps(open("config/stripe-receipts.yaml").read()))')}"
```

Then map a Stripe `charge.succeeded` object to the print `data` and enqueue with
[`examples/stripe_to_vibe.py`](examples/stripe_to_vibe.py):

```bash
# thermal printer with the format; or use --template N for an office/laser printer
stripe charges retrieve ch_123 | \
  python examples/stripe_to_vibe.py http://localhost:8080 "$SECRET" --printer 1 --format 2
```

Stripe amounts are in **cents** (the helper formats them); line items aren't on a Charge, so pass
them from your order system via `--line-items`. The receipt's QR encodes the Stripe `receipt_url`.

---

## Configuration (environment variables)

All variables are prefixed `VIBE_PRINT_`.

| Variable | Default | Purpose |
|---|---|---|
| `SECRET` | _(required)_ | shared bearer secret; empty → refuse to boot |
| `DATA_DIR` | `./data` | DB + assets + backups |
| `TRUSTED_PROXIES` | `[]` | JSON list of proxy IPs/CIDRs to trust for real-IP headers |
| `MAX_ATTEMPTS` | `5` | retry attempts before `dead` |
| `RETRY_BASE_SECONDS` / `RETRY_MAX_SECONDS` | `2` / `300` | backoff bounds |
| `QUEUE_MAX_DEPTH` / `PER_PRINTER_MAX_DEPTH` | `1000` / `100` | backpressure caps |
| `RATE_LIMIT_PER_MINUTE` | `120` | per-real-IP request limit |
| `MAX_BODY_BYTES` / `MAX_ASSET_BYTES` | `5 MiB` / `10 MiB` | size caps |
| `JOB_RETENTION_DAYS` / `AUDIT_RETENTION_DAYS` / `IDEMPOTENCY_TTL_HOURS` | `30` / `365` / `24` | retention windows |
| `RENDER_TIMEOUT_SECONDS` | `15` | render budget |
| `STORE_PAYLOADS` | `true` | `false` → keep only a content hash after printing (PII minimization) |
| `ENCRYPT_AT_REST` / `DB_ENCRYPTION_KEY` | `false` / — | SQLCipher at rest (Linux image) |
| `WEBHOOK_URL` / `WEBHOOK_SECRET` | — | signed `dead`/`uncertain`/offline alerts |
| `HEARTBEAT_URL` / `HEARTBEAT_SECRET` / `HEARTBEAT_MINUTES` | — / — / `15` | fleet phone-home |
| `ACCESS_TEAM_DOMAIN` / `ACCESS_AUD` | — | enable Cloudflare Access JWT on admin routes |
| `CLOUDFLARED_METRICS_URL` | — | tunnel health for `remote/status` |
| `REMOTE_ACCESS_MODE` / `REMOTE_HOSTNAME` | `lan` / — | display-only remote-access info |
| `IMAGE_DIGEST` | `dev` | surfaced in `/v1/version` (set by the update flow) |

---

## Remote access

**Everything from the UI (no host shell):** the **Remote Access** tab runs a `cloudflared` tunnel
as a managed process inside the appliance. Pick **Quick** (instant `*.trycloudflare.com` URL, no
Cloudflare account) or **Named** (paste a tunnel token for a stable dashboard hostname), then
Start/Stop — it auto-restarts on reboot. LAN access stays on at the same time. (The compose
`cloudflare` profile / sidecar remains as an alternative.)

Three selectable modes, all optional:

- **LAN-only** (default). Front with **Caddy** for TLS on a trusted segment (`--profile caddy`).
- **Cloudflare Tunnel** (`--profile cloudflare`): outbound-only, no inbound ports. Provision the
  hostname once in the Cloudflare dashboard — the appliance stores **no Cloudflare API token** and
  never edits DNS/ingress; it only displays the hostname. Add **Cloudflare Access** (Zero Trust) in
  front of the admin UI, then set `ACCESS_TEAM_DOMAIN` + `ACCESS_AUD` to enforce the JWT app-side
  (service tokens work for machine clients). `GET /v1/admin/remote/status` reports tunnel health.
- **Tailscale**: the private-network alternative — join the appliance to your tailnet.

`/healthz` and `/readyz` stay open and outside Access so health checks don't break.

---

## Backup & restore

- `POST /v1/admin/backup/snapshot` writes a consistent SQLite snapshot (online `VACUUM INTO`).
- `deploy/backup.sh` ships the snapshot + assets to **Backblaze B2** (S3-compatible, Object Lock for
  immutability) — run it from cron.
- `deploy/restore.sh <STAMP>` restores into the data volume; migrations are idempotent on restart.

Run a periodic **restore drill** to verify backups.

---

## Observability & compliance

- **Metrics:** Prometheus at `/metrics` (jobs by status, per-printer counts, queue depth, render timings).
- **Audit:** `config_audit` + `print_audit` are **hash-chained**; `GET /v1/admin/audit/verify`
  detects any tampering. Logs are JSON (structlog) and **redact** payloads/data.
- **Webhooks:** HMAC-signed POSTs on `dead`/`uncertain`/printer-offline (`X-Vibe-Signature`).
- **Fleet:** opt-in heartbeat + `GET /v1/admin/diagnostics` (PII-free) for support.
- **PII:** `STORE_PAYLOADS=false` replaces a job's payload with a content hash after printing;
  `DELETE /v1/admin/jobs/{id}/payload` erases on demand; retention prunes jobs/audit/idempotency.

---

## Development

```bash
make dev         # run the stack against virtual printers (no hardware)
make seed        # load sample fixtures
make test        # pytest (79 tests; virtual + socket-mock + soak)
make lint        # ruff
make typecheck   # mypy (enforced in CI)
make gen-api     # regenerate the TS client from OpenAPI (CI fails on drift)
make web-build   # build the admin UI into app/static
make build       # multi-arch Docker image
cd web && npm run e2e   # Playwright (needs: npx playwright install chromium)
```

Architecture lives in `app/` (FastAPI), `web/` (React+TS), and `deploy/` (Docker/compose/Caddy/CUPS).
See [`VIBE-PRINT-MASTER-PLAN.md`](VIBE-PRINT-MASTER-PLAN.md) for the full design and
[`STATUS.md`](STATUS.md) for what's implemented vs. excluded.

Contributions: open a PR — CI runs ruff, mypy, the full test suite, the OpenAPI drift gate, the
frontend build, and Playwright e2e.

---

## Project status

The full master plan is implemented and tested (120+ tests, ruff + mypy clean, Playwright e2e
verified, CI green). First multi-arch release **`v0.1.0`** is published to GHCR. Two items from the
plan's "consciously deferred" list are intentionally **out of scope** because they contradict the
appliance's locked design (single shared secret; single-process SQLite): **multi-tenant isolation**
and **HA / multi-node** — both would need a different architecture (per-tenant auth / Postgres +
distributed coordination). See `STATUS.md`.

---

## License

No license file is included yet, so default copyright applies (all rights reserved). If you intend
others to use, modify, or distribute this, add a `LICENSE` (e.g. MIT or Apache-2.0).
