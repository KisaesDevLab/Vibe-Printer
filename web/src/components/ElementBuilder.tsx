import { useState } from "react";

// Visual ESC/POS element builder (P19): add, reorder (drag), edit, remove elements,
// two-way synced with the raw JSON view in the parent.

export type El = Record<string, unknown> & { type: string };

const TYPES = ["text", "rule", "table", "qr", "barcode", "image", "feed", "pulse", "cut"];

const DEFAULTS: Record<string, El> = {
  text: { type: "text", value: "{{ data.x }}", align: "left", bold: false, size: [1, 1] },
  rule: { type: "rule" },
  table: {
    type: "table",
    cols: [24, 10, 12],
    align: ["left", "right", "right"],
    rows_from: "data.lines",
    row: ["{{ item.name }}", "{{ item.qty }}", "{{ item.amt }}"],
  },
  qr: { type: "qr", value: "{{ data.url }}", size: 6 },
  barcode: { type: "barcode", format: "CODE128", value: "{{ data.ref }}" },
  image: { type: "image", asset: "logo" },
  feed: { type: "feed", lines: 1 },
  pulse: { type: "pulse", pin: 2 },
  cut: { type: "cut" },
};

export function ElementBuilder({
  elements,
  onChange,
}: {
  elements: El[];
  onChange: (els: El[]) => void;
}) {
  const [dragIdx, setDragIdx] = useState<number | null>(null);

  const update = (i: number, patch: Partial<El>) =>
    onChange(elements.map((e, idx) => (idx === i ? { ...e, ...patch } : e)));
  const remove = (i: number) => onChange(elements.filter((_, idx) => idx !== i));
  const add = (type: string) => onChange([...elements, { ...DEFAULTS[type] }]);
  const move = (from: number, to: number) => {
    if (to < 0 || to >= elements.length) return;
    const next = [...elements];
    const [item] = next.splice(from, 1);
    next.splice(to, 0, item);
    onChange(next);
  };

  return (
    <div>
      {elements.map((el, i) => (
        <div
          key={i}
          className="card"
          draggable
          onDragStart={() => setDragIdx(i)}
          onDragOver={(e) => e.preventDefault()}
          onDrop={() => {
            if (dragIdx !== null && dragIdx !== i) move(dragIdx, i);
            setDragIdx(null);
          }}
          style={{ padding: 10, marginBottom: 8, cursor: "grab" }}
        >
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong>⠿ {el.type}</strong>
            <span className="row">
              <button className="ghost" onClick={() => move(i, i - 1)} title="up">↑</button>
              <button className="ghost" onClick={() => move(i, i + 1)} title="down">↓</button>
              <button className="danger" onClick={() => remove(i)}>✕</button>
            </span>
          </div>
          <ElementFields el={el} onChange={(patch) => update(i, patch)} />
        </div>
      ))}

      <div className="row" style={{ marginTop: 8 }}>
        <select
          onChange={(e) => {
            if (e.target.value) add(e.target.value);
            e.target.value = "";
          }}
          defaultValue=""
        >
          <option value="">+ add element…</option>
          {TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

function ElementFields({ el, onChange }: { el: El; onChange: (patch: Partial<El>) => void }) {
  switch (el.type) {
    case "text":
      return (
        <>
          <input
            value={String(el.value ?? "")}
            onChange={(e) => onChange({ value: e.target.value })}
            placeholder="text or {{ data.field }}"
          />
          <div className="row" style={{ marginTop: 6 }}>
            <select value={String(el.align ?? "left")} onChange={(e) => onChange({ align: e.target.value })}>
              <option value="left">left</option>
              <option value="center">center</option>
              <option value="right">right</option>
            </select>
            <label className="row" style={{ margin: 0 }}>
              <input
                type="checkbox"
                style={{ width: "auto" }}
                checked={Boolean(el.bold)}
                onChange={(e) => onChange({ bold: e.target.checked })}
              />
              <span>bold</span>
            </label>
          </div>
        </>
      );
    case "qr":
      return (
        <input value={String(el.value ?? "")} onChange={(e) => onChange({ value: e.target.value })} />
      );
    case "barcode":
      return (
        <div className="row">
          <select value={String(el.format ?? "CODE128")} onChange={(e) => onChange({ format: e.target.value })}>
            {["CODE128", "EAN13", "CODE39", "UPC-A"].map((f) => (
              <option key={f}>{f}</option>
            ))}
          </select>
          <input value={String(el.value ?? "")} onChange={(e) => onChange({ value: e.target.value })} />
        </div>
      );
    case "image":
      return (
        <input value={String(el.asset ?? "")} onChange={(e) => onChange({ asset: e.target.value })} placeholder="asset name" />
      );
    case "feed":
      return (
        <input
          type="number"
          value={Number(el.lines ?? 1)}
          onChange={(e) => onChange({ lines: Number(e.target.value) })}
        />
      );
    case "pulse":
      return (
        <>
          <label>Cash-drawer pin</label>
          <select value={Number(el.pin ?? 2)} onChange={(e) => onChange({ pin: Number(e.target.value) })}>
            <option value={2}>pin 2</option>
            <option value={5}>pin 5</option>
          </select>
        </>
      );
    case "table":
      return (
        <>
          <label>rows_from</label>
          <input value={String(el.rows_from ?? "")} onChange={(e) => onChange({ rows_from: e.target.value })} />
          <label>row templates (comma-separated)</label>
          <input
            value={(el.row as string[] | undefined)?.join(", ") ?? ""}
            onChange={(e) => onChange({ row: e.target.value.split(",").map((s) => s.trim()) })}
          />
          <label>column widths (comma-separated)</label>
          <input
            value={(el.cols as number[] | undefined)?.join(", ") ?? ""}
            onChange={(e) =>
              onChange({ cols: e.target.value.split(",").map((s) => Number(s.trim())) })
            }
          />
        </>
      );
    default:
      return <span className="muted">no options</span>;
  }
}
