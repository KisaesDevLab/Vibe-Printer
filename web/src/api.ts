// Typed API client. The shared secret lives in sessionStorage and is attached as a bearer
// header on every request (P17.3/P17.5). Any 401 clears it so the SecretGate re-prompts.
//
// Request-body shapes are generated from the backend OpenAPI (P26.4) — run `make gen-api`;
// CI fails on drift. See ./api-types.ts (do not edit by hand).

import type { components } from "./api-types";

export type Schemas = components["schemas"];
export type PrinterCreateBody = Schemas["PrinterCreate"];
export type FormatCreateBody = Schemas["FormatCreate"];
export type TemplateCreateBody = Schemas["TemplateCreate"];

const SECRET_KEY = "vibe_print_secret";

export function getSecret(): string | null {
  return sessionStorage.getItem(SECRET_KEY);
}
export function setSecret(s: string) {
  sessionStorage.setItem(SECRET_KEY, s);
}
export function clearSecret() {
  sessionStorage.removeItem(SECRET_KEY);
}

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(code: string, message: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const secret = getSecret();
  if (secret) headers["Authorization"] = `Bearer ${secret}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const res = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401) {
    clearSecret();
    window.dispatchEvent(new Event("vibe-unauthorized"));
    throw new ApiError("unauthorized", "Re-enter the secret", 401);
  }
  if (res.status === 204) return undefined as T;

  const ct = res.headers.get("content-type") || "";
  if (!res.ok) {
    if (ct.includes("application/json")) {
      const data = await res.json();
      const err = data.error || {};
      throw new ApiError(err.code || "error", err.message || res.statusText, res.status);
    }
    throw new ApiError("error", res.statusText, res.status);
  }
  if (ct.includes("application/json")) return res.json();
  return (await res.blob()) as unknown as T;
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, b?: unknown) => request<T>("POST", p, b),
  put: <T>(p: string, b?: unknown) => request<T>("PUT", p, b),
  del: <T>(p: string) => request<T>("DELETE", p),
};

// --- Domain types (kept aligned with app/models.py; codegen is the Phase 26 upgrade) ---
export interface Printer {
  id: number;
  name: string;
  type: string;
  capabilities?: Record<string, unknown>;
  default_format_id?: number | null;
  default_template_id?: number | null;
  allow_raw: boolean;
  version: number;
}
export interface Format {
  id: number;
  name: string;
  elements: { elements: unknown[] };
  sample_data: Record<string, unknown>;
  version: number;
}
export interface Template {
  id: number;
  name: string;
  html: string;
  css: string;
  page_setup: Record<string, unknown>;
  sample_data: Record<string, unknown>;
  version: number;
}
export interface Job {
  id: string;
  printer_id: number;
  status: string;
  delivery: string | null;
  attempts: number;
  last_error: string | null;
  created_at: string;
}
