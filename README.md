# Vibe Print

LAN print routing gateway. Callers POST a payload over HTTP, pick a **printer by integer id**,
and the gateway routes the job to the right device. A React admin UI configures the device,
printers, document formats, and PDF templates. Self-hosted Docker appliance for a Raspberry Pi
or NucBox.

**Printer types:** `escpos_network` (TCP :9100), `escpos_usb`, `cups` (office/PDF),
`zpl_network` (Zebra labels), `star_network` (Star Line Mode), `virtual` (dev/test), and `pool`
(failover / round-robin across members).

**Highlights:** durable queue with per-printer serialization, idempotency keys, mid-send →
`uncertain` (no duplicate receipts), retry/backoff, job priority + not-before scheduling + daily
quotas, reprint, signed failure/offline webhooks, fleet heartbeat + diagnostics, tamper-evident
hash-chained audit, Cloudflare Access JWT enforcement, optional SQLCipher-at-rest, payload-hash
PII mode, B2 backup/restore, and a visual element builder + i18n admin UI.

See [`VIBE-PRINT-MASTER-PLAN.md`](VIBE-PRINT-MASTER-PLAN.md) for the full design and
[`STATUS.md`](STATUS.md) for what is implemented vs. deferred.

## Quick start (local dev, no hardware)

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

export VIBE_PRINT_SECRET=dev-secret              # the service refuses to boot without this
python -m app.seed                               # sample virtual printer + format + template
make dev                                         # http://localhost:8080  (UI dev: cd web && npm run dev)
```

Print to the seeded virtual printer:

```bash
curl -s localhost:8080/v1/print \
  -H "Authorization: Bearer dev-secret" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"printer":1,"data":{"company":"Acme","date":"2026-06-27","lines":[],"total":"0","url":"x"}}'
# -> {"job_id":"...","status":"queued"}
```

The virtual backend writes the ESC/POS bytes to `data/virtual/printer-1.bin`. Poll
`GET /v1/jobs/{id}` for the final outcome — **"sent" ≠ confirmed printed** for fire-and-forget
ESC/POS.

## Tests, lint, build

```bash
make test        # 19 backend tests (registry, templating, auth, print flow, delivery semantics)
make lint        # ruff
make web-build   # build the admin UI into app/static
make build       # docker image (Dockerfile bundles WeasyPrint, fonts, libusb, CUPS)
```

## Deploy (Ubuntu 24.04 / DigitalOcean droplet or Pi/NucBox)

```bash
cd deploy
cp .env.example .env        # set a UNIQUE VIBE_PRINT_SECRET per appliance
docker compose up -d --build
```

Profiles:
- `--profile caddy` — front with Caddy for LAN TLS (`deploy/Caddyfile`).
- `--profile cloudflare` — outbound Cloudflare Tunnel (set `TUNNEL_TOKEN`); no inbound ports.
  The public hostname is provisioned once in the Cloudflare dashboard; the appliance stores no
  Cloudflare API token and is display-only.

For USB printers, uncomment the `devices:` mapping in the compose file and add a udev rule on the
host. CUPS runs in-container, bound to localhost only.

## API surface

All `/v1/*` routes require `Authorization: Bearer <secret>`; `/healthz`, `/readyz`, `/metrics`,
and the `/admin` UI are open. Errors use a stable envelope: `{"error":{"code","message","details?}}`.

| Method | Path | Notes |
|--------|------|-------|
| POST | `/v1/print` | `document` inline OR `format`/`template` id + `data`; honors `Idempotency-Key` |
| POST | `/v1/print/raw` | ESC/POS only, disabled per-printer by default (`allow_raw`) |
| POST | `/v1/print/preview` | returns `image/png` (thermal) or `application/pdf` |
| GET | `/v1/printers` | list with cached capabilities |
| GET | `/v1/printers/{id}/status` | live reachability |
| GET | `/v1/jobs/{id}` | observe final outcome + delivery |
| * | `/v1/admin/*` | device, printers, formats, templates, assets, config import/export, jobs, audit |

OpenAPI is at `/openapi.json`. A sample client is in [`examples/`](examples/).

## Architecture

```
app/
  main.py        FastAPI app, lifespan, routers, /admin static, security headers, health
  settings.py    Pydantic settings (fail-fast on empty secret)
  db.py          SQLite + forward-only migration runner (backup-before-migrate)
  models.py      Pydantic models (printer params discriminated on `type`)
  registry.py    DB-backed config + optimistic concurrency + YAML import/export
  backends/      PrinterBackend protocol, factory, virtual/escpos_network/escpos_usb/cups, locks
  templating.py  sandboxed Jinja2 merge + WeasyPrint PDF (SSRF-locked to local assets)
  render.py      ESC/POS byte render + PNG preview
  queue.py       durable job store + async worker (per-printer serialization, idempotency, retry)
  auth.py        shared secret, real-IP, rate limiting
  api/, admin.py print + admin routers
  obs.py, audit.py  structlog, Prometheus, DB audit
web/             React 18 + TS + Vite admin UI (built into app/static)
deploy/          Dockerfile assets, compose profiles, Caddyfile, cupsd.conf
```

Key invariants: fail-closed auth; ESC/POS serialized per printer while CUPS runs parallel;
mid-send failures become `uncertain` (never auto-retried) to avoid duplicate receipts; idempotency
keys dedupe; WeasyPrint cannot fetch remote URLs; capability-aware rendering rejects unsupported
elements.
