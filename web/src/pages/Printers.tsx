import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, Printer } from "../api";

interface StatusResp {
  reachable?: boolean;
  state?: string;
  errors?: string[];
}

function ReachBadge({ id }: { id: number }) {
  const { data } = useQuery({
    queryKey: ["pstatus", id],
    queryFn: () => api.get<StatusResp>(`/v1/printers/${id}/status`),
    refetchInterval: 15000,
  });
  if (!data) return <span className="badge">checking…</span>;
  const detail = (data.errors && data.errors.length ? data.errors.join(", ") : data.state) || "";
  return (
    <span className={`badge ${data.reachable ? "ok" : "err"}`} title={detail}>
      {data.reachable ? "reachable" : "offline"}
    </span>
  );
}

const EMPTY = {
  name: "",
  type: "virtual",
  host: "",
  port: 9100,
  queue: "",
  device_uri: "",
  vendor_id: "",
  product_id: "",
  columns: 48,
  members: "",
  strategy: "failover",
  raster: false,
  output_bin: "",
  input_tray: "",
  allow_raw: false,
};

const OUTPUT_BINS = ["face-down", "face-up", "top", "left", "center", "rear",
  "tray-1", "tray-2", "stacker-1", "mailbox-1"];
const INPUT_TRAYS = ["auto", "main", "manual", "bypass", "tray-1", "tray-2", "tray-3", "tray-4"];

export function PrintersPage() {
  const qc = useQueryClient();
  const { data: printers, isLoading } = useQuery({
    queryKey: ["printers"],
    queryFn: () => api.get<Printer[]>("/v1/admin/printers"),
  });
  const [form, setForm] = useState({ ...EMPTY });
  const [err, setErr] = useState("");
  const [editing, setEditing] = useState<Printer | null>(null);
  const [confirm, setConfirm] = useState<Printer | null>(null);
  const [toast, setToast] = useState("");

  const create = useMutation({
    mutationFn: () => api.post("/v1/admin/printers", buildBody(form)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["printers"] });
      setForm({ ...EMPTY });
      setErr("");
    },
    onError: (e: Error) => setErr(e.message),
  });

  const saveEdit = useMutation({
    mutationFn: () => api.put(`/v1/admin/printers/${editing!.id}`, buildEditBody(form, editing!)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["printers"] });
      setEditing(null);
      setForm({ ...EMPTY });
      setErr("");
    },
    onError: (e: Error) => setErr(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/v1/admin/printers/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["printers"] });
      setConfirm(null);
    },
    onError: (e: Error) => {
      setErr(e.message);
      setConfirm(null);
    },
  });

  const test = useMutation({
    mutationFn: (id: number) => api.post<{ job_id: string }>(`/v1/admin/printers/${id}/test`),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      setToast(`Test queued — job ${d.job_id.slice(0, 8)} (see Jobs tab)`);
      setTimeout(() => setToast(""), 5000);
    },
    onError: (e: Error) => setToast(`Test failed: ${e.message}`),
  });

  const drawer = useMutation({
    mutationFn: (id: number) => api.post(`/v1/admin/printers/${id}/open-drawer`, {}),
    onSuccess: () => {
      setToast("Cash drawer kick sent");
      setTimeout(() => setToast(""), 4000);
    },
    onError: (e: Error) => setToast(`Drawer failed: ${e.message}`),
  });

  const provision = useMutation({
    mutationFn: (p: Printer) => {
      const uri = p.params.device_uri as string | undefined;
      if (!uri) throw new Error("Set a Device URI first (Edit the printer)");
      return api.post(`/v1/admin/printers/${p.id}/provision-queue`, { device_uri: uri });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["printers"] });
      setToast("Queue provisioned — status will refresh shortly");
      setTimeout(() => setToast(""), 5000);
    },
    onError: (e: Error) => setToast(`Provision failed: ${e.message}`),
  });

  function startEdit(p: Printer) {
    setEditing(p);
    setErr("");
    setForm({
      ...EMPTY,
      name: p.name,
      type: p.type,
      host: String(p.params.host ?? ""),
      port: Number(p.params.port ?? 9100),
      queue: String(p.params.queue ?? ""),
      device_uri: String(p.params.device_uri ?? ""),
      vendor_id: p.params.vendor_id ? Number(p.params.vendor_id).toString(16) : "",
      product_id: p.params.product_id ? Number(p.params.product_id).toString(16) : "",
      columns: Number(p.params.columns ?? 48),
      members: Array.isArray(p.params.members) ? (p.params.members as number[]).join(", ") : "",
      strategy: String(p.params.strategy ?? "failover"),
      raster: Boolean(p.params.raster),
      output_bin: String(p.params.output_bin ?? ""),
      input_tray: String(p.params.input_tray ?? ""),
      allow_raw: p.allow_raw,
    });
    window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  }
  function cancelEdit() {
    setEditing(null);
    setForm({ ...EMPTY });
    setErr("");
  }

  return (
    <div>
      <h2>Printers</h2>
      {toast && (
        <div className="card" style={{ borderColor: "var(--accent)", padding: 10 }}>
          {toast}
        </div>
      )}
      <div className="card">
        {isLoading ? (
          <p className="muted">Loading…</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Type</th>
                <th>Status</th>
                <th>Raw</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {printers?.map((p) => (
                <tr key={p.id}>
                  <td>{p.id}</td>
                  <td>{p.name}</td>
                  <td>
                    <span className="badge">{p.type}</span>
                  </td>
                  <td>
                    <ReachBadge id={p.id} />
                  </td>
                  <td>{p.allow_raw ? "on" : "off"}</td>
                  <td className="row">
                    <button className="ghost" onClick={() => test.mutate(p.id)}>
                      Test
                    </button>
                    {pulseCapable(p) && (
                      <button className="ghost" onClick={() => drawer.mutate(p.id)}
                              title="Open the cash drawer wired to this printer">
                        Drawer
                      </button>
                    )}
                    {p.type === "cups" && (
                      <button className="ghost" onClick={() => provision.mutate(p)}
                              title="Create/refresh the CUPS queue from the device URI">
                        Provision
                      </button>
                    )}
                    <button className="ghost" onClick={() => startEdit(p)}>
                      Edit
                    </button>
                    <button className="danger" onClick={() => setConfirm(p)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
              {printers?.length === 0 && (
                <tr>
                  <td colSpan={6} className="muted">
                    No printers yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      <DiscoverPanel
        onUse={(c) =>
          setForm({
            ...EMPTY,
            name: `Printer ${c.host}`,
            type: c.type,
            host: c.host,
            port: c.port,
          })
        }
      />

      <div className="card">
        <h3>{editing ? `Edit printer #${editing.id}` : "Add printer"}</h3>
        <div className="split">
          <div>
            <label>Name</label>
            <input
              aria-label="Printer name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
            <label>Type {editing && <span className="muted">(changing rebuilds connection settings)</span>}</label>
            <select
              value={form.type}
              onChange={(e) => setForm({ ...form, type: e.target.value })}
            >
              {typeOptions(editing).map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <div>
            {form.type === "escpos_network" && (
              <>
                <label>Host</label>
                <input value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} />
                <label>Port</label>
                <input
                  type="number"
                  value={form.port}
                  onChange={(e) => setForm({ ...form, port: Number(e.target.value) })}
                />
              </>
            )}
            {form.type === "escpos_usb" && (
              <>
                <label>Vendor ID (hex, e.g. 0x04b8)</label>
                <input
                  value={form.vendor_id}
                  onChange={(e) => setForm({ ...form, vendor_id: e.target.value })}
                />
                <label>Product ID (hex)</label>
                <input
                  value={form.product_id}
                  onChange={(e) => setForm({ ...form, product_id: e.target.value })}
                />
              </>
            )}
            {(form.type === "ipp_network" || form.type === "zpl_network" ||
              form.type === "star_network") && (
              <>
                <label>Host / IP</label>
                <input value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} />
                <label>Port</label>
                <input
                  type="number"
                  value={form.port}
                  onChange={(e) => setForm({ ...form, port: Number(e.target.value) })}
                />
                {form.type === "ipp_network" && (
                  <>
                    <p className="muted" style={{ fontSize: 12 }}>
                      Direct IPP — sends PDF straight to the printer, no CUPS queue to provision.
                    </p>
                    <TrayFields form={form} setForm={setForm} />
                  </>
                )}
              </>
            )}
            {form.type === "zpl_network" && (
              <label className="row" style={{ marginTop: 12 }}>
                <input
                  type="checkbox"
                  style={{ width: "auto" }}
                  checked={form.raster}
                  onChange={(e) => setForm({ ...form, raster: e.target.checked })}
                />
                <span>Raster mode (^GFA bitmap — prints text/QR/images as graphics)</span>
              </label>
            )}
            {form.type === "pool" && (
              <>
                <label>Member printer IDs (comma-separated)</label>
                <input
                  value={form.members}
                  onChange={(e) => setForm({ ...form, members: e.target.value })}
                  placeholder="2, 3"
                />
                <label>Strategy</label>
                <select value={form.strategy} onChange={(e) => setForm({ ...form, strategy: e.target.value })}>
                  <option value="failover">failover</option>
                  <option value="round_robin">round_robin</option>
                </select>
              </>
            )}
            {form.type === "cups" && (
              <>
                <label>Queue name</label>
                <input value={form.queue} onChange={(e) => setForm({ ...form, queue: e.target.value })} />
                <label>Device URI (auto-provisions the queue; persists across rebuilds)</label>
                <input
                  value={form.device_uri}
                  onChange={(e) => setForm({ ...form, device_uri: e.target.value })}
                  placeholder="ipp://192.168.1.50/ipp/print"
                />
                <TrayFields form={form} setForm={setForm} />
              </>
            )}
            {form.type !== "cups" && (
              <label className="row" style={{ marginTop: 16 }}>
                <input
                  type="checkbox"
                  style={{ width: "auto" }}
                  checked={form.allow_raw}
                  onChange={(e) => setForm({ ...form, allow_raw: e.target.checked })}
                />
                <span>Allow /print/raw (off by default)</span>
              </label>
            )}
          </div>
        </div>
        {err && <p className="error">{err}</p>}
        <div className="row" style={{ marginTop: 12 }}>
          {editing ? (
            <>
              <button disabled={!form.name || saveEdit.isPending} onClick={() => saveEdit.mutate()}>
                Save changes
              </button>
              <button className="ghost" onClick={cancelEdit}>
                Cancel
              </button>
            </>
          ) : (
            <button disabled={!form.name || create.isPending} onClick={() => create.mutate()}>
              Create
            </button>
          )}
        </div>
      </div>

      {confirm && (
        <DeleteDialog
          printer={confirm}
          pools={(printers ?? []).filter(
            (p) =>
              p.type === "pool" &&
              Array.isArray(p.params.members) &&
              (p.params.members as number[]).includes(confirm.id),
          )}
          busy={remove.isPending}
          onCancel={() => setConfirm(null)}
          onConfirm={() => remove.mutate(confirm.id)}
        />
      )}
    </div>
  );
}

function pulseCapable(p: Printer): boolean {
  const caps = p.capabilities as { pulse?: boolean } | undefined;
  if (caps && typeof caps.pulse === "boolean") return caps.pulse;
  return ["escpos_network", "escpos_usb", "star_network", "virtual", "pool"].includes(p.type);
}

function TrayFields({ form, setForm }: { form: typeof EMPTY; setForm: (f: typeof EMPTY) => void }) {
  return (
    <>
      <label>Output tray <span className="muted">(optional)</span></label>
      <input
        list="vp-output-bins"
        value={form.output_bin}
        placeholder="e.g. face-down, tray-1, stacker-1"
        onChange={(e) => setForm({ ...form, output_bin: e.target.value })}
      />
      <label>Input tray <span className="muted">(optional)</span></label>
      <input
        list="vp-input-trays"
        value={form.input_tray}
        placeholder="e.g. auto, tray-2, manual"
        onChange={(e) => setForm({ ...form, input_tray: e.target.value })}
      />
      <datalist id="vp-output-bins">{OUTPUT_BINS.map((v) => <option key={v} value={v} />)}</datalist>
      <datalist id="vp-input-trays">{INPUT_TRAYS.map((v) => <option key={v} value={v} />)}</datalist>
    </>
  );
}

function typeOptions(editing: Printer | null): string[] {
  const base = [
    "virtual", "escpos_network", "escpos_usb", "cups", "ipp_network",
    "zpl_network", "star_network", "pool",
  ];
  if (editing && !base.includes(editing.type)) base.push(editing.type);
  return base;
}

function DeleteDialog({
  printer, pools, busy, onCancel, onConfirm,
}: {
  printer: Printer;
  pools: Printer[];
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div
      onClick={onCancel}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 50,
      }}
    >
      <div className="card" style={{ width: 420 }} onClick={(e) => e.stopPropagation()}>
        <h3>Delete printer?</h3>
        <p>
          Delete <strong>{printer.name}</strong> (#{printer.id}, {printer.type})? This cannot be undone.
        </p>
        {pools.length > 0 && (
          <p className="error">
            ⚠ This printer is a member of {pools.length} pool(s): {pools.map((p) => p.name).join(", ")}.
            Removing it may leave those pools with fewer fallbacks.
          </p>
        )}
        <div className="row" style={{ marginTop: 12 }}>
          <button className="danger" disabled={busy} onClick={onConfirm}>
            {busy ? "Deleting…" : "Delete"}
          </button>
          <button className="ghost" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

interface Candidate {
  host: string;
  port: number;
  type: string;
}

function DiscoverPanel({ onUse }: { onUse: (c: Candidate) => void }) {
  const [subnet, setSubnet] = useState("192.168.1.0/24");
  const scan = useMutation({
    mutationFn: () => api.post<{ candidates: Candidate[] }>("/v1/admin/discover", { subnet }),
  });
  return (
    <div className="card">
      <h3>Discover printers on the LAN</h3>
      <div className="row">
        <input value={subnet} onChange={(e) => setSubnet(e.target.value)} placeholder="192.168.1.0/24" />
        <button className="ghost" onClick={() => scan.mutate()} disabled={scan.isPending}>
          {scan.isPending ? "Scanning…" : "Scan"}
        </button>
      </div>
      {scan.error && <p className="error">{(scan.error as Error).message}</p>}
      {scan.data && (
        <table style={{ marginTop: 12 }}>
          <tbody>
            {scan.data.candidates.map((c, i) => (
              <tr key={i}>
                <td>{c.host}:{c.port}</td>
                <td>
                  <span className="badge">{c.type}</span>
                </td>
                <td>
                  <button className="ghost" onClick={() => onUse(c)}>
                    Use
                  </button>
                </td>
              </tr>
            ))}
            {scan.data.candidates.length === 0 && (
              <tr>
                <td className="muted">No printers found.</td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}

// Build the params object for the currently-selected type from the form fields.
function buildParams(form: typeof EMPTY): Record<string, unknown> {
  const params: Record<string, unknown> = { type: form.type };
  if (form.type === "escpos_network") Object.assign(params, { host: form.host, port: form.port, columns: form.columns });
  if (form.type === "escpos_usb")
    Object.assign(params, { vendor_id: parseInt(form.vendor_id, 16), product_id: parseInt(form.product_id, 16) });
  const trays = {
    ...(form.output_bin ? { output_bin: form.output_bin } : {}),
    ...(form.input_tray ? { input_tray: form.input_tray } : {}),
  };
  if (form.type === "cups")
    Object.assign(params, { queue: form.queue, ...(form.device_uri ? { device_uri: form.device_uri } : {}), ...trays });
  if (form.type === "ipp_network")
    Object.assign(params, { host: form.host, port: form.port, ...trays });
  if (form.type === "star_network")
    Object.assign(params, { host: form.host, port: form.port });
  if (form.type === "zpl_network")
    Object.assign(params, { host: form.host, port: form.port, raster: form.raster });
  if (form.type === "pool") Object.assign(params, { members: parseMembers(form.members), strategy: form.strategy });
  if (form.type === "virtual") Object.assign(params, { columns: form.columns });
  return params;
}

function buildBody(form: typeof EMPTY) {
  return { name: form.name, params: buildParams(form), allow_raw: form.allow_raw };
}

function parseMembers(s: string): number[] {
  return s.split(",").map((x) => parseInt(x.trim(), 10)).filter((n) => !isNaN(n));
}

// On edit: if the type is unchanged, preserve the original params (timeout/encoding/dpmm/etc) and
// override the form-exposed fields; if the type changed, build fresh params for the new type.
function buildEditBody(form: typeof EMPTY, original: Printer) {
  const fresh = buildParams(form);
  const params = form.type === original.type ? { ...original.params, ...fresh } : fresh;
  return {
    name: form.name,
    params,
    allow_raw: form.allow_raw,
    default_format_id: original.default_format_id ?? null,
    default_template_id: original.default_template_id ?? null,
    version: original.version,
  };
}
