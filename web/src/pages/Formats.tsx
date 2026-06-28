import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, Format, Printer } from "../api";
import { CodeEditor } from "../components/CodeEditor";
import { ConfirmDelete } from "../components/ConfirmDelete";
import { El, ElementBuilder } from "../components/ElementBuilder";

// Element formats print on every printer except office (PDF) ones.
const THERMAL_TYPES = ["escpos_network", "escpos_usb", "zpl_network", "star_network", "virtual", "pool"];

export function FormatsPage() {
  const qc = useQueryClient();
  const { data: formats } = useQuery({
    queryKey: ["formats"],
    queryFn: () => api.get<Format[]>("/v1/admin/formats"),
  });
  const [selected, setSelected] = useState<Format | null>(null);
  const [confirm, setConfirm] = useState<Format | null>(null);

  const create = useMutation({
    mutationFn: () =>
      api.post<Format>("/v1/admin/formats", {
        name: "New format",
        elements: { elements: [{ type: "text", value: "Hello {{ data.name }}" }, { type: "cut" }] },
        sample_data: { name: "World" },
      }),
    onSuccess: (f) => {
      qc.invalidateQueries({ queryKey: ["formats"] });
      setSelected(f);
    },
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/v1/admin/formats/${id}`),
    onSuccess: (_d, id) => {
      qc.invalidateQueries({ queryKey: ["formats"] });
      setConfirm(null);
      setSelected((s) => (s && s.id === id ? null : s));
    },
  });

  return (
    <div>
      <h2>Document Formats (ESC/POS)</h2>
      <div className="row" style={{ marginBottom: 12 }}>
        <button onClick={() => create.mutate()}>New format</button>
      </div>
      <div className="split">
        <div className="card">
          <table>
            <tbody>
              {formats?.map((f) => (
                <tr key={f.id}>
                  <td>{f.name}</td>
                  <td className="muted">v{f.version}</td>
                  <td className="row">
                    <button className="ghost" onClick={() => setSelected(f)}>
                      Edit
                    </button>
                    <button className="danger" onClick={() => setConfirm(f)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
              {formats?.length === 0 && <tr><td className="muted">No formats yet.</td></tr>}
            </tbody>
          </table>
        </div>
        <div>{selected && <FormatEditor key={selected.id} format={selected} />}</div>
      </div>

      {confirm && (
        <ConfirmDelete
          what="format"
          name={confirm.name}
          busy={remove.isPending}
          onCancel={() => setConfirm(null)}
          onConfirm={() => remove.mutate(confirm.id)}
        />
      )}
    </div>
  );
}

function FormatEditor({ format }: { format: Format }) {
  const qc = useQueryClient();
  const [name, setName] = useState(format.name);
  const [elements, setElements] = useState(JSON.stringify(format.elements, null, 2));
  const [sample, setSample] = useState(JSON.stringify(format.sample_data, null, 2));
  const [preview, setPreview] = useState<string>("");
  const [err, setErr] = useState("");
  const [tab, setTab] = useState<"builder" | "json">("builder");
  const [printerId, setPrinterId] = useState<number | "">("");
  const [toast, setToast] = useState("");

  const { data: printers } = useQuery({
    queryKey: ["printers"],
    queryFn: () => api.get<Printer[]>("/v1/admin/printers"),
  });
  const targets = (printers ?? []).filter((p) => THERMAL_TYPES.includes(p.type));

  const testPrint = useMutation({
    mutationFn: () =>
      api.post<{ job_id: string }>("/v1/print", {
        printer: Number(printerId),
        format: format.id,
        data: JSON.parse(sample),
      }),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      setToast(`Test print queued — job ${d.job_id.slice(0, 8)} (see Jobs tab)`);
      setTimeout(() => setToast(""), 6000);
    },
    onError: (e: Error) => setToast(`Test print failed: ${e.message}`),
  });

  // Parse the elements JSON for the visual builder; null when JSON is invalid.
  let parsedEls: El[] | null = null;
  try {
    const obj = JSON.parse(elements);
    parsedEls = Array.isArray(obj.elements) ? (obj.elements as El[]) : null;
  } catch {
    parsedEls = null;
  }
  const setEls = (els: El[]) => setElements(JSON.stringify({ elements: els }, null, 2));

  const save = useMutation({
    mutationFn: () =>
      api.put(`/v1/admin/formats/${format.id}`, {
        name,
        elements: JSON.parse(elements),
        sample_data: JSON.parse(sample),
        version: format.version,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["formats"] });
      setErr("");
    },
    onError: (e: Error) => setErr(e.message),
  });

  // Debounced live preview
  useEffect(() => {
    const t = setTimeout(async () => {
      try {
        // Inline preview of unsaved edits — no save required.
        const blob = (await api.post(`/v1/admin/formats/${format.id}/preview`, {
          elements: JSON.parse(elements),
          data: JSON.parse(sample),
        })) as unknown as Blob;
        setPreview(URL.createObjectURL(blob));
        setErr("");
      } catch (e) {
        setErr((e as Error).message);
      }
    }, 500);
    return () => clearTimeout(t);
  }, [elements, sample, format.id]);

  return (
    <div className="card">
      <label>Name</label>
      <input value={name} onChange={(e) => setName(e.target.value)} />
      <div className="row" style={{ margin: "10px 0 4px" }}>
        <button className={tab === "builder" ? "" : "ghost"} onClick={() => setTab("builder")}>
          Builder
        </button>
        <button className={tab === "json" ? "" : "ghost"} onClick={() => setTab("json")}>
          JSON
        </button>
      </div>
      {tab === "builder" ? (
        parsedEls ? (
          <ElementBuilder elements={parsedEls} onChange={setEls} />
        ) : (
          <p className="error">Invalid JSON — switch to the JSON tab to fix it.</p>
        )
      ) : (
        <CodeEditor value={elements} onChange={setElements} lang="json" height="260px" />
      )}
      <label>Sample data (JSON)</label>
      <CodeEditor value={sample} onChange={setSample} lang="json" height="120px" />
      {err && <p className="error">{err}</p>}
      <div className="row" style={{ margin: "12px 0" }}>
        <button onClick={() => save.mutate()} disabled={save.isPending}>
          Save
        </button>
        <span className="muted">v{format.version} — saving bumps the version</span>
      </div>

      <label>Test print to a printer (uses the sample data above)</label>
      <div className="row">
        <select value={printerId} onChange={(e) => setPrinterId(e.target.value ? Number(e.target.value) : "")}
                style={{ maxWidth: 280 }}>
          <option value="">Select a printer…</option>
          {targets.map((p) => (
            <option key={p.id} value={p.id}>{p.name} ({p.type})</option>
          ))}
        </select>
        <button className="ghost" disabled={!printerId || testPrint.isPending}
                onClick={() => testPrint.mutate()}>
          Test print
        </button>
      </div>
      {targets.length === 0 && (
        <p className="muted" style={{ fontSize: 12 }}>No ESC/POS-family printers configured yet.</p>
      )}
      {toast && <p className="muted">{toast}</p>}

      <label style={{ marginTop: 12 }}>Live preview</label>
      {preview ? <img className="preview" src={preview} alt="preview" /> : <p className="muted">…</p>}
    </div>
  );
}
