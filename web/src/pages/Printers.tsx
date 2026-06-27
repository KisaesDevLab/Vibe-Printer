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
  return (
    <span className={`badge ${data.reachable ? "ok" : "err"}`}>
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
  vendor_id: "",
  product_id: "",
  columns: 48,
  allow_raw: false,
};

export function PrintersPage() {
  const qc = useQueryClient();
  const { data: printers, isLoading } = useQuery({
    queryKey: ["printers"],
    queryFn: () => api.get<Printer[]>("/v1/admin/printers"),
  });
  const [form, setForm] = useState({ ...EMPTY });
  const [err, setErr] = useState("");

  const create = useMutation({
    mutationFn: () => api.post("/v1/admin/printers", buildBody(form)),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["printers"] });
      setForm({ ...EMPTY });
      setErr("");
    },
    onError: (e: Error) => setErr(e.message),
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/v1/admin/printers/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["printers"] }),
  });

  const test = useMutation({
    mutationFn: (id: number) => api.post(`/v1/admin/printers/${id}/test`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });

  return (
    <div>
      <h2>Printers</h2>
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
                    <button className="danger" onClick={() => remove.mutate(p.id)}>
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
        <h3>Add printer</h3>
        <div className="split">
          <div>
            <label>Name</label>
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <label>Type</label>
            <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
              <option value="virtual">virtual</option>
              <option value="escpos_network">escpos_network</option>
              <option value="escpos_usb">escpos_usb</option>
              <option value="cups">cups</option>
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
            {form.type === "cups" && (
              <>
                <label>Queue</label>
                <input value={form.queue} onChange={(e) => setForm({ ...form, queue: e.target.value })} />
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
        <div style={{ marginTop: 12 }}>
          <button disabled={!form.name || create.isPending} onClick={() => create.mutate()}>
            Create
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

function buildBody(form: typeof EMPTY) {
  let params: Record<string, unknown> = { type: form.type };
  if (form.type === "escpos_network") params = { ...params, host: form.host, port: form.port, columns: form.columns };
  if (form.type === "escpos_usb")
    params = { ...params, vendor_id: parseInt(form.vendor_id, 16), product_id: parseInt(form.product_id, 16) };
  if (form.type === "cups") params = { ...params, queue: form.queue };
  if (form.type === "virtual") params = { ...params, columns: form.columns };
  return { name: form.name, params, allow_raw: form.allow_raw };
}
