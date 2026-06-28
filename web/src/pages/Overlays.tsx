import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as pdfjs from "pdfjs-dist";
// @ts-expect-error Vite worker import
import PdfWorker from "pdfjs-dist/build/pdf.worker.min.mjs?worker";
import QRCode from "qrcode";
import { useEffect, useRef, useState } from "react";
import { api, Overlay, OverlayField, Printer } from "../api";
import { CodeEditor } from "../components/CodeEditor";
import { ConfirmDelete } from "../components/ConfirmDelete";

const PDF_TYPES = ["cups", "ipp_network", "virtual"];

pdfjs.GlobalWorkerOptions.workerPort = new PdfWorker();

const FONT_CSS: Record<string, string> = {
  Helvetica: "Helvetica, Arial, sans-serif",
  "Helvetica-Bold": "Helvetica, Arial, sans-serif",
  "Times-Roman": "'Times New Roman', Times, serif",
  Courier: "'Courier New', Courier, monospace",
};

// Lightweight {{ data.x.y }} substitution for the on-canvas preview (the server does the real
// Jinja render for the actual PDF).
function resolveValue(value: string, sample: Record<string, unknown>): string {
  return (value || "").replace(/\{\{\s*data\.([\w.]+)\s*\}\}/g, (_m, path: string) => {
    let cur: unknown = sample;
    for (const part of path.split(".")) {
      if (cur && typeof cur === "object" && part in (cur as Record<string, unknown>)) {
        cur = (cur as Record<string, unknown>)[part];
      } else {
        return `‹${path}›`;
      }
    }
    return cur == null ? "" : String(cur);
  });
}

function QrImg({ value, px }: { value: string; px: number }) {
  const [src, setSrc] = useState("");
  useEffect(() => {
    let alive = true;
    QRCode.toDataURL(value || " ", { margin: 0 }).then((d) => alive && setSrc(d)).catch(() => {});
    return () => { alive = false; };
  }, [value]);
  return src ? <img src={src} width={px} height={px} alt="qr" style={{ display: "block" }} /> :
    <div style={{ width: px, height: px, background: "#ccc" }} />;
}

const TARGET_W = 560; // canvas render width in CSS px

const FIELD_DEFAULTS: Record<string, OverlayField> = {
  text: { type: "text", page: 0, x: 72, y: 72, value: "{{ data.name }}", size: 12,
          font: "Helvetica", align: "left", color: "#000000" },
  qr: { type: "qr", page: 0, x: 72, y: 72, value: "{{ data.url }}", size: 72 },
  image: { type: "image", page: 0, x: 72, y: 72, asset: "logo.png", width: 72, height: 72 },
};

export function OverlaysPage() {
  const qc = useQueryClient();
  const { data: overlays } = useQuery({
    queryKey: ["overlays"],
    queryFn: () => api.get<Overlay[]>("/v1/admin/overlays"),
  });
  const [selected, setSelected] = useState<Overlay | null>(null);
  const [confirm, setConfirm] = useState<Overlay | null>(null);
  const [err, setErr] = useState("");

  const remove = useMutation({
    mutationFn: (id: number) => api.del(`/v1/admin/overlays/${id}`),
    onSuccess: (_d, id) => {
      qc.invalidateQueries({ queryKey: ["overlays"] });
      setConfirm(null);
      setSelected((s) => (s && s.id === id ? null : s));
    },
  });

  const create = useMutation({
    mutationFn: async (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      const asset = await api.upload<{ name: string }>("/v1/admin/assets", fd);
      return api.post<Overlay>("/v1/admin/overlays", {
        name: file.name.replace(/\.pdf$/i, ""),
        base_asset: asset.name,
        fields: [],
        sample_data: {},
      });
    },
    onSuccess: (o) => {
      qc.invalidateQueries({ queryKey: ["overlays"] });
      setSelected(o);
      setErr("");
    },
    onError: (e: Error) => setErr(e.message),
  });

  return (
    <div>
      <h2>PDF Overlays</h2>
      <div className="card">
        <label>Upload a base PDF to overlay variables onto</label>
        <input
          type="file"
          accept="application/pdf"
          onChange={(e) => e.target.files?.[0] && create.mutate(e.target.files[0])}
        />
        {err && <p className="error">{err}</p>}
        <table style={{ marginTop: 12 }}>
          <tbody>
            {overlays?.map((o) => (
              <tr key={o.id}>
                <td>{o.name}</td>
                <td className="muted">v{o.version}</td>
                <td className="row">
                  <button className="ghost" onClick={() => setSelected(o)}>Edit</button>
                  <button className="danger" onClick={() => setConfirm(o)}>Delete</button>
                </td>
              </tr>
            ))}
            {overlays?.length === 0 && (
              <tr><td className="muted">No overlays yet — upload a PDF above.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {selected && <OverlayEditor key={selected.id} overlay={selected} />}

      {confirm && (
        <ConfirmDelete
          what="overlay"
          name={confirm.name}
          busy={remove.isPending}
          onCancel={() => setConfirm(null)}
          onConfirm={() => remove.mutate(confirm.id)}
        />
      )}
    </div>
  );
}

function OverlayEditor({ overlay }: { overlay: Overlay }) {
  const qc = useQueryClient();
  const [name, setName] = useState(overlay.name);
  const [fields, setFields] = useState<OverlayField[]>(overlay.fields);
  const [sample, setSample] = useState(JSON.stringify(overlay.sample_data, null, 2));
  const [page, setPage] = useState(0);
  const [numPages, setNumPages] = useState(1);
  const [scale, setScale] = useState(1);
  const [dims, setDims] = useState({ w: TARGET_W, h: 720 });
  const [sel, setSel] = useState<number | null>(null);
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
        overlay: overlay.id,
        data: JSON.parse(sample),
      }),
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      setToast(`Test print queued — job ${d.job_id.slice(0, 8)} (see Jobs tab)`);
      setTimeout(() => setToast(""), 6000);
    },
    onError: (e: Error) => setToast(`Test print failed: ${e.message}`),
  });

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const docRef = useRef<pdfjs.PDFDocumentProxy | null>(null);
  const dragRef = useRef<
    { i: number; startXpx: number; startYpx: number; cx: number; cy: number } | null
  >(null);

  let sampleObj: Record<string, unknown> = {};
  try {
    sampleObj = JSON.parse(sample);
  } catch {
    sampleObj = {};
  }

  // Load the base PDF once.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const blob = (await api.get(`/v1/admin/overlays/${overlay.id}/base`)) as unknown as Blob;
        const buf = await blob.arrayBuffer();
        const doc = await pdfjs.getDocument({ data: buf }).promise;
        if (cancelled) return;
        docRef.current = doc;
        setNumPages(doc.numPages);
        renderPage(0);
      } catch (e) {
        setErr((e as Error).message);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overlay.id]);

  async function renderPage(p: number) {
    const doc = docRef.current;
    const canvas = canvasRef.current;
    if (!doc || !canvas) return;
    const pg = await doc.getPage(p + 1);
    const base = pg.getViewport({ scale: 1 });
    const s = TARGET_W / base.width;
    const vp = pg.getViewport({ scale: s });
    canvas.width = vp.width;
    canvas.height = vp.height;
    setScale(s);
    setDims({ w: vp.width, h: vp.height });
    const ctx = canvas.getContext("2d")!;
    await pg.render({ canvasContext: ctx, viewport: vp }).promise;
  }

  useEffect(() => { renderPage(page); /* eslint-disable-next-line */ }, [page]);

  const update = (i: number, patch: Partial<OverlayField>) =>
    setFields(fields.map((f, idx) => (idx === i ? { ...f, ...patch } : f)));
  const addField = (type: string) => {
    setFields([...fields, { ...FIELD_DEFAULTS[type], page }]);
    setSel(fields.length);
  };
  const removeField = (i: number) => {
    setFields(fields.filter((_, idx) => idx !== i));
    setSel(null);
  };

  // Delta-based pointer drag (robust to alignment transforms). Updates x/y in PDF points.
  function onChipDown(e: React.PointerEvent, i: number) {
    e.preventDefault();
    setSel(i);
    const f = fields[i];
    dragRef.current = {
      i, startXpx: (f.x ?? 0) * scale, startYpx: (f.y ?? 0) * scale, cx: e.clientX, cy: e.clientY,
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }
  function onMove(e: PointerEvent) {
    const d = dragRef.current;
    if (!d) return;
    const leftPx = Math.max(0, Math.min(dims.w, d.startXpx + (e.clientX - d.cx)));
    const topPx = Math.max(0, Math.min(dims.h, d.startYpx + (e.clientY - d.cy)));
    update(d.i, { x: Math.round(leftPx / scale), y: Math.round(topPx / scale) });
  }
  function onUp() {
    dragRef.current = null;
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
  }

  const save = useMutation({
    mutationFn: () =>
      api.put(`/v1/admin/overlays/${overlay.id}`, {
        name, base_asset: overlay.base_asset, fields,
        sample_data: JSON.parse(sample), version: overlay.version,
      }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["overlays"] }); setErr(""); },
    onError: (e: Error) => setErr(e.message),
  });

  async function doPreview() {
    try {
      const blob = (await api.post(`/v1/admin/overlays/${overlay.id}/preview`, {
        base_asset: overlay.base_asset, fields, data: JSON.parse(sample),
      })) as unknown as Blob;
      setPreview(URL.createObjectURL(blob));
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  const pageFields = fields.map((f, i) => ({ f, i })).filter((x) => (x.f.page ?? 0) === page);

  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <input value={name} onChange={(e) => setName(e.target.value)} style={{ maxWidth: 280 }} />
        <span className="row">
          <button className="ghost" onClick={() => addField("text")}>+ Text</button>
          <button className="ghost" onClick={() => addField("qr")}>+ QR</button>
          <button className="ghost" onClick={() => addField("image")}>+ Image</button>
        </span>
      </div>

      <div className="row" style={{ margin: "10px 0" }}>
        <button className="ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>‹</button>
        <span className="muted">page {page + 1} / {numPages}</span>
        <button className="ghost" disabled={page >= numPages - 1} onClick={() => setPage(page + 1)}>›</button>
        <span className="muted">drag fields onto the page</span>
      </div>

      <div className="split">
        {/* Canvas + draggable chips */}
        <div style={{ position: "relative", width: dims.w }}>
          <canvas ref={canvasRef} style={{ border: "1px solid var(--border)", width: dims.w }} />
          <div style={{ position: "absolute", top: 0, left: 0, width: dims.w, height: dims.h }}>
            {pageFields.map(({ f, i }) => {
              const box = (f.size ?? 72) * scale;
              const align = f.align ?? "left";
              const transform =
                align === "right" ? "translateX(-100%)" : align === "center" ? "translateX(-50%)" : "";
              const selected = sel === i;
              const common: React.CSSProperties = {
                position: "absolute",
                left: (f.x ?? 0) * scale,
                top: (f.y ?? 0) * scale,
                transform,
                cursor: "grab",
                userSelect: "none",
                outline: selected ? "2px solid var(--accent)" : "1px dashed rgba(79,140,255,0.6)",
                outlineOffset: 1,
              };
              return (
                <div key={i} onPointerDown={(e) => onChipDown(e, i)} style={common}
                     title="drag to position">
                  {f.type === "text" && (
                    <span style={{
                      fontSize: (f.size ?? 12) * scale,
                      fontFamily: FONT_CSS[f.font ?? "Helvetica"] ?? "sans-serif",
                      color: f.color ?? "#000",
                      lineHeight: 1,
                      whiteSpace: "nowrap",
                      display: "inline-block",
                    }}>
                      {resolveValue(f.value ?? "", sampleObj) || "text"}
                    </span>
                  )}
                  {f.type === "qr" && <QrImg value={resolveValue(f.value ?? "", sampleObj)} px={box} />}
                  {f.type === "image" && (
                    <div style={{
                      width: (f.width ?? f.size ?? 72) * scale,
                      height: (f.height ?? f.width ?? f.size ?? 72) * scale,
                      background: "rgba(0,0,0,0.06)",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: 10, color: "var(--muted)", textAlign: "center", overflow: "hidden",
                    }}>
                      🖼 {f.asset}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Field inspector + data + actions */}
        <div>
          {sel !== null && fields[sel] ? (
            <FieldInspector
              field={fields[sel]}
              onChange={(patch) => update(sel, patch)}
              onDelete={() => removeField(sel)}
              numPages={numPages}
            />
          ) : (
            <p className="muted">Select a field to edit, or add one above.</p>
          )}

          <label>Sample data (JSON)</label>
          <CodeEditor value={sample} onChange={setSample} lang="json" height="120px" />

          {err && <p className="error">{err}</p>}
          <div className="row" style={{ marginTop: 10 }}>
            <button onClick={() => save.mutate()} disabled={save.isPending}>Save</button>
            <button className="ghost" onClick={doPreview}>Preview PDF</button>
          </div>

          <label style={{ marginTop: 10 }}>Test print to a printer (uses the sample data)</label>
          <div className="row">
            <select value={printerId}
                    onChange={(e) => setPrinterId(e.target.value ? Number(e.target.value) : "")}
                    style={{ maxWidth: 240 }}>
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
          {toast && <p className="muted">{toast}</p>}

          {preview && (
            <iframe src={preview} title="PDF preview" width="100%" height="320"
                    style={{ marginTop: 10, border: "1px solid var(--border)" }} />
          )}
        </div>
      </div>
    </div>
  );
}

function FieldInspector({
  field, onChange, onDelete, numPages,
}: {
  field: OverlayField;
  onChange: (p: Partial<OverlayField>) => void;
  onDelete: () => void;
  numPages: number;
}) {
  return (
    <div className="card" style={{ background: "var(--bg)" }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>{field.type} field</strong>
        <button className="danger" onClick={onDelete}>Remove</button>
      </div>
      {field.type !== "image" ? (
        <>
          <label>Value (Jinja, e.g. {"{{ data.name }}"})</label>
          <input value={field.value ?? ""} onChange={(e) => onChange({ value: e.target.value })} />
        </>
      ) : (
        <>
          <label>Asset name</label>
          <input value={field.asset ?? ""} onChange={(e) => onChange({ asset: e.target.value })} />
        </>
      )}
      <div className="row">
        <div style={{ flex: 1 }}>
          <label>Size (pt)</label>
          <input type="number" value={field.size ?? 12} onChange={(e) => onChange({ size: Number(e.target.value) })} />
        </div>
        <div style={{ flex: 1 }}>
          <label>Page</label>
          <input type="number" min={1} max={numPages} value={(field.page ?? 0) + 1}
                 onChange={(e) => onChange({ page: Math.max(0, Number(e.target.value) - 1) })} />
        </div>
      </div>
      {field.type === "text" && (
        <div className="row">
          <div style={{ flex: 1 }}>
            <label>Align</label>
            <select value={field.align ?? "left"} onChange={(e) => onChange({ align: e.target.value as OverlayField["align"] })}>
              <option value="left">left</option>
              <option value="center">center</option>
              <option value="right">right</option>
            </select>
          </div>
          <div style={{ flex: 1 }}>
            <label>Color</label>
            <input type="color" value={field.color ?? "#000000"} onChange={(e) => onChange({ color: e.target.value })} />
          </div>
        </div>
      )}
      <p className="muted" style={{ fontSize: 12 }}>x {Math.round(field.x)}, y {Math.round(field.y)} pt</p>
    </div>
  );
}
