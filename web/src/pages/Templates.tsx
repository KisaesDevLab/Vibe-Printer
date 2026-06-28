import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, Template } from "../api";
import { CodeEditor } from "../components/CodeEditor";

export function TemplatesPage() {
  const qc = useQueryClient();
  const { data: templates } = useQuery({
    queryKey: ["templates"],
    queryFn: () => api.get<Template[]>("/v1/admin/templates"),
  });
  const [selected, setSelected] = useState<Template | null>(null);

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
                  <td>
                    <button className="ghost" onClick={() => setSelected(t)}>
                      Edit
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>{selected && <TemplateEditor key={selected.id} template={selected} />}</div>
      </div>
    </div>
  );
}

function TemplateEditor({ template }: { template: Template }) {
  const qc = useQueryClient();
  const [name, setName] = useState(template.name);
  const [html, setHtml] = useState(template.html);
  const [css, setCss] = useState(template.css);
  const [sample, setSample] = useState(JSON.stringify(template.sample_data, null, 2));
  const [preview, setPreview] = useState("");
  const [err, setErr] = useState("");

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
        <span className="muted">PDF preview requires the 'pdf' extra (WeasyPrint)</span>
      </div>
      <label>Live PDF preview</label>
      {preview ? (
        <iframe src={preview} title="PDF preview" width="100%" height="400"
                style={{ border: "1px solid var(--border)" }} />
      ) : (
        <p className="muted">…</p>
      )}
    </div>
  );
}
