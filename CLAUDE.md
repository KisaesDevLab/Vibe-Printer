# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

**Critical path built and green** (19 tests passing, ruff clean, UI builds). The backend
implements P0–P14, the admin UI P17–P21, and packaging P23/P25/P26. `VIBE-PRINT-MASTER-PLAN.md`
remains the single source of truth; **`STATUS.md` tracks implemented vs. deferred phases** — read
it before starting new work. Deferred items (provisioning P27, fleet P28, encryption-at-rest/redaction
P29, discovery P15, OpenAPI→TS codegen, full CodeMirror editors, Playwright e2e) are listed there.
Follow the plan's phases and acceptance gates; do not invent architecture that contradicts it.

`vibe-print` is a self-hosted Docker appliance: callers POST a payload over HTTP, pick a **printer
by integer id**, and the gateway routes the job to ESC/POS thermal (TCP 9100 or USB) or CUPS/IPP
office printers (via PDF). A React admin UI configures everything. Target hardware: Raspberry Pi
(arm64) or NucBox (amd64), often shipped to clients.

## Build order & execution model (from the plan)

- **Critical path:** P0 → P1 → P2/P3 → P4 (+P6) → P7/P8 → P10 → P11 → P12 → P13 → P17 → UI phases.
- **Parallelizable:** P5 (USB), P9 (assets), P15 (discovery), P25/P26 (CI/dev).
- **Gating before any client ship:** P28–P30; **before any remote/field deploy:** P16 (tunnel), P27 (provisioning).
- **Definition of Done per phase:** lint + typecheck clean, phase tests green, README touched, no new
  high/critical scan findings. Each phase has a `✅` acceptance line in the plan — treat it as the gate.
- Record blockers in a `QUESTIONS.md` rather than guessing on locked decisions.

## Commands (Phase 26 — implemented in the Makefile)

```
make dev      # full stack + UI against VIRTUAL printers (no hardware) — mock :9100 + dummy CUPS-PDF
make test     # unit + integration
make lint     # ruff + mypy (backend), tsc (frontend)
make build    # multi-arch image (arm64 + amd64)
make seed     # sample printers/formats/templates/data fixtures
make e2e      # Playwright UI flows
```

Backend: Python 3.12 + FastAPI/Uvicorn, ruff + mypy, pytest. Frontend: React 18 + TS 5 + Vite,
pnpm. Run a single backend test with `pytest tests/path::test_name`. The dev loop must work with
**no physical printer** via the `VirtualBackend` (P3.3) — never require hardware for tests or `make dev`.

## Architecture (the parts that span multiple files)

- **Backend abstraction (`app/backends/`)** — a `PrinterBackend` protocol (`open/send/status/
  capabilities/close`) with a factory dispatching on the registry row's `type`
  (`escpos_network | escpos_usb | cups | virtual`). All printer-specific logic lives behind this seam.
- **Config registry (`app/registry/`)** — DB-backed CRUD over SQLite with an in-memory cache
  invalidated on write, **optimistic concurrency** (version field; stale write → `409`), and YAML
  import/export that round-trips. SQLite is the source of truth; YAML is import/export only.
- **Templating → render (`app/templating/`, `app/render/`)** — request `data` is merged via
  **sandboxed Jinja2** into either element-JSON (ESC/POS) or HTML/CSS (PDF). Two render targets:
  `python-escpos` (codepage-encoded, images dithered to `paper_width_dots`) and WeasyPrint → PDF.
  Templates/formats are **versioned**, and the resolved version is recorded on each job for
  reproducible reprints.
- **Queue/worker (`app/queue/`)** — SQLite-durable async queue, **single worker**. Job states:
  `queued → rendering → printing → done | failed | dead | canceled | uncertain`. Idempotency keys
  dedupe within a TTL. Retry with backoff → `dead`; retention pruning of jobs/audit/idempotency.
- **Auth (`app/auth/`)** — single shared secret (`VIBE_PRINT_SECRET`), bearer on all `/v1/*`
  (`/healthz` + `/readyz` open). Real client IP and per-IP rate limiting depend on `trusted_proxies`.
- **Admin UI (`web/`)** — Vite build served by FastAPI at `/admin`, same origin. Secret held in
  memory/sessionStorage (no cookies, no CSRF). Previews are **server-rendered** (PNG/PDF) — never
  re-render in the browser. TS client + types are **codegen'd from FastAPI's OpenAPI** (P26.4);
  Zod is for form UX only. CI fails on schema drift.

See "Suggested layout" in the plan for the full directory map.

## Non-negotiable invariants (these encode High-severity gap-review findings)

- **Fail-closed auth:** service refuses to start if `VIBE_PRINT_SECRET` is unset/empty. Never runs open.
- **Per-printer serialization for ESC/POS only** (network + USB share one byte stream → lock it).
  **CUPS submits concurrently** and is tracked via job-state polling — do *not* serialize CUPS.
- **At-most-once for the in-flight job:** a job interrupted mid-send is marked `uncertain` for
  operator review — **never auto-retried** (prevents duplicate financial receipts). All other
  failures retry normally.
- **Idempotency:** identical `Idempotency-Key` + payload returns the original job; same key +
  different payload → `idempotency_conflict`.
- **WeasyPrint SSRF lockdown:** no remote URL fetching (assets only); enforce render timeout + memory cap.
- **"Sent" ≠ "printed":** ESC/POS is fire-and-forget (bytes accepted). Final outcome observed via
  `GET /v1/jobs/{id}`, not the enqueue response. CUPS can be polled to truer completion.
- **Stable error envelope** on all routes: `{error:{code, message, details?}}` with machine codes
  (`unknown_printer`, `unsupported_for_printer`, `validation_error`, `unauthorized`, `rate_limited`,
  `queue_full`, `render_error`, `printer_unreachable`, `idempotency_conflict`).
- **Capability-aware rendering:** if a format needs a feature the target printer lacks (cached
  capabilities), return `unsupported_for_printer` (or degrade per documented policy).
- **`print/raw` is ESC/POS-only and disabled by default** (per-printer opt-in) — it streams unvalidated bytes.
- **PII/compliance (§7216/GLBA):** never log payload bodies or merged `data`; minimize PII at rest;
  honor configurable retention. CUPS web admin / `:631` bound to localhost — no remote admin surface.

## Locked decisions (don't relitigate without the user)

Python 3.12 + FastAPI; thermal + CUPS; SQLite (UI-writable) + YAML import/export; Jinja2 → WeasyPrint
for PDF; SQLite-durable async queue; single shared-secret bearer auth (no login/sessions/CSRF); USB
included; UI at `/admin` same-origin; CUPS runs **in-container**; assets on a **filesystem volume**
(not SQLite blobs); Caddy fronts TLS on LAN; remote access selectable (LAN / Cloudflare Tunnel /
Tailscale), tunnel opt-in via compose profile. The appliance stores **no Cloudflare API token** and
never edits DNS/ingress — the public hostname is display-only in the UI.
