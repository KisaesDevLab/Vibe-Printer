import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, Format } from "../api";
import { CodeEditor } from "../components/CodeEditor";
import { El, ElementBuilder } from "../components/ElementBuilder";

export function FormatsPage() {
  const qc = useQueryClient();
  const { data: formats } = useQuery({
    queryKey: ["formats"],
    queryFn: () => api.get<Format[]>("/v1/admin/formats"),
  });
  const [selected, setSelected] = useState<Format | null>(null);

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
                  <td>
                    <button className="ghost" onClick={() => setSelected(f)}>
                      Edit
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>{selected && <FormatEditor key={selected.id} format={selected} />}</div>
      </div>
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
      <label>Live preview</label>
      {preview ? <img className="preview" src={preview} alt="preview" /> : <p className="muted">…</p>}
    </div>
  );
}
