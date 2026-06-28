import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, Printer, Template } from "../api";
import { CodeEditor } from "../components/CodeEditor";

export function TemplatesPage() {
  const qc = useQueryClient();
  const { data: templates } = useQuery({
    queryKey: ["templates"],
    queryFn: () => api.get<Template[]>("/v1/admin/templates"),
  });
  const [selected, setSelected] = useState<Template | null>(null);
  const [confirm, setConfirm] = useState<Template | null>(null);

  const create = useMutation({
    mutationFn: () =>
      api.post<Template>("/v1/admin/templates", {
        name: "New template",
        html: "<h1>{{ data.title }}</h1>",
        css: "h1{font-family:sans-serif}",
        page_setup: { size: "A4", margins: "1.5cm" },
        sample_data: { title: "Hello" },
      }),
    onSuccess: (t) => {
      qc.invalidateQueries({ queryKey: ["templates"] });
      setSelected(t);
    },
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/v1/admin/templates/${id}`),
    onSuccess: (_d, id) => {
      qc.invalidateQueries({ queryKey: ["templates"] });
      setConfirm(null);
      setSelected((s) => (s && s.id === id ? null : s));
    },
  });

  return (
    <div>
      <h2>PDF Templates (office / CUPS)</h2>
      <div className="row" style={{ marginBottom: 12 }}>
        <button onClick={() => create.mutate()}>New template</button>
      </div>
      <div className="split">
        <div className="card">
          <table>
            <tbody>
              {templates?.map((t) => (
                <tr key={t.id}>
                  <td>{t.name}</td>
                  <td className="muted">v{t.version}</td>
                  <td className="row">
                    <button className="ghost" onClick={() => setSelected(t)}>
                      Edit
                    </button>
                    <button className="danger" onClick={() => setConfirm(t)}>
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
              {templates?.length === 0 && (
                <tr><td className="muted">No templates yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div>{selected && <TemplateEditor key={selected.id} template={selected} />}</div>
      </div>

      {confirm && (
        <div
          onClick={() => setConfirm(null)}
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", display: "flex",
                   alignItems: "center", justifyContent: "center", zIndex: 50 }}
        >
          <div className="card" style={{ width: 400 }} onClick={(e) => e.stopPropagation()}>
            <h3>Delete template?</h3>
            <p>Delete <strong>{confirm.name}</strong>? This cannot be undone.</p>
            <div className="row" style={{ marginTop: 12 }}>
              <button className="danger" disabled={remove.isPending} onClick={() => remove.mutate(confirm.id)}>
                {remove.isPending ? "Deleting…" : "Delete"}
              </button>
              <button className="ghost" onClick={() => setConfirm(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const PDF_TYPES = ["cups", "ipp_network", "virtual"];

function TemplateEditor({ template }: { template: Template }) {
  const qc = useQueryClient();
  const [name, setName] = useState(template.name);
  const [html, setHtml] = useState(template.html);
  const [css, setCss] = useState(template.css);
  const [sample, setSample] = useState(JSON.stringify(template.sample_data, null, 2));
  const [preview, setPreview] = useState("");
  const [err, setErr] = useState("");
  const [printerId, setPrinterId] = useState<number | "">("");
  const [toast, setToast] = useState("");

  const { data: printers } = useQuery({
    queryKey: ["printers"],
    queryFn: () => api.get<Printer[]>("/v1/admin/printers"),
  });
  const pdfPrinters = (printers ?? []).filter((p) => PDF_TYPES.includes(p.type));

  const testPrint = useMutation({
    mutationFn: () =>
      api.post<{ job_id: string }>("/v1/print", {
        printer: Number(printerId),
        template: template.id,
        data: JSON.parse(sample),
      }),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      setToast(`Test print queued — job ${d.job_id.slice(0, 8)} (see Jobs tab)`);
      setTimeout(() => setToast(""), 6000);
    },
    onError: (e: Error) => setToast(`Test print failed: ${e.message}`),
  });

  const save = useMutation({
    mutationFn: () =>
      api.put(`/v1/admin/templates/${template.id}`, {
        name,
        html,
        css,
        page_setup: template.page_setup,
        sample_data: JSON.parse(sample),
        version: template.version,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["templates"] });
      setErr("");
    },
    onError: (e: Error) => setErr(e.message),
  });

  useEffect(() => {
    const t = setTimeout(async () => {
      try {
        // Inline preview of unsaved edits — render html/css/data directly, no save.
        const blob = (await api.post(`/v1/admin/templates/${template.id}/preview`, {
          html,
          css,
          page_setup: template.page_setup,
          data: JSON.parse(sample),
        })) as unknown as Blob;
        setPreview(URL.createObjectURL(blob));
        setErr("");
      } catch (e) {
        setErr((e as Error).message);
      }
    }, 800);
    return () => clearTimeout(t);
  }, [html, css, sample, template.id, template.page_setup]);

  return (
    <div className="card">
      <label>Name</label>
      <input value={name} onChange={(e) => setName(e.target.value)} />
      <label>HTML (Jinja)</label>
      <CodeEditor value={html} onChange={setHtml} lang="html" height="200px" />
      <label>CSS</label>
      <CodeEditor value={css} onChange={setCss} lang="css" height="120px" />
      <label>Sample data (JSON)</label>
      <CodeEditor value={sample} onChange={setSample} lang="json" height="100px" />
      {err && <p className="error">{err}</p>}
      <div className="row" style={{ margin: "12px 0" }}>
        <button onClick={() => save.mutate()} disabled={save.isPending}>
          Save
        </button>
      </div>

      <label>Test print to a printer (uses the sample data above)</label>
      <div className="row">
        <select value={printerId} onChange={(e) => setPrinterId(e.target.value ? Number(e.target.value) : "")}
                style={{ maxWidth: 280 }}>
          <option value="">Select a printer…</option>
          {pdfPrinters.map((p) => (
            <option key={p.id} value={p.id}>{p.name} ({p.type})</option>
          ))}
        </select>
        <button className="ghost" disabled={!printerId || testPrint.isPending}
                onClick={() => testPrint.mutate()}>
          Test print
        </button>
      </div>
      {pdfPrinters.length === 0 && (
        <p className="muted" style={{ fontSize: 12 }}>
          No PDF-capable printers (CUPS / IPP / virtual) configured yet.
        </p>
      )}
      {toast && <p className="muted">{toast}</p>}

      <label style={{ marginTop: 12 }}>Live PDF preview</label>
      {preview ? (
        <iframe src={preview} title="PDF preview" width="100%" height="400"
                style={{ border: "1px solid var(--border)" }} />
      ) : (
        <p className="muted">…</p>
      )}
    </div>
  );
}
