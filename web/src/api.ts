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

async function upload<T>(path: string, form: FormData): Promise<T> {
  const headers: Record<string, string> = {};
  const secret = getSecret();
  if (secret) headers["Authorization"] = `Bearer ${secret}`;
  const res = await fetch(path, { method: "POST", headers, body: form });
  if (res.status === 401) {
    clearSecret();
    window.dispatchEvent(new Event("vibe-unauthorized"));
    throw new ApiError("unauthorized", "Re-enter the secret", 401);
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new ApiError(data?.error?.code || "error", data?.error?.message || res.statusText, res.status);
  }
  return res.json();
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, b?: unknown) => request<T>("POST", p, b),
  put: <T>(p: string, b?: unknown) => request<T>("PUT", p, b),
  del: <T>(p: string) => request<T>("DELETE", p),
  upload,
};

export interface Overlay {
  id: number;
  name: string;
  base_asset: string;
  fields: OverlayField[];
  sample_data: Record<string, unknown>;
  version: number;
}

export interface OverlayField {
  type: "text" | "qr" | "image";
  page: number;
  x: number;
  y: number;
  value?: string;
  asset?: string | null;
  size?: number;
  width?: number | null;
  height?: number | null;
  font?: string;
  align?: "left" | "center" | "right";
  color?: string;
}

// --- Domain types (kept aligned with app/models.py; codegen is the Phase 26 upgrade) ---
export interface Printer {
  id: number;
  name: string;
  type: string;
  params: Record<string, unknown>;
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
