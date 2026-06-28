export function ConfirmDelete({
  what,
  name,
  busy,
  onCancel,
  onConfirm,
  warning,
}: {
  what: string;
  name: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  warning?: string;
}) {
  return (
    <div
      onClick={onCancel}
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
        display: "flex", alignItems: "center", justifyContent: "center", zIndex: 50,
      }}
    >
      <div className="card" style={{ width: 400 }} onClick={(e) => e.stopPropagation()}>
        <h3>Delete {what}?</h3>
        <p>Delete <strong>{name}</strong>? This cannot be undone.</p>
        {warning && <p className="error">{warning}</p>}
        <div className="row" style={{ marginTop: 12 }}>
          <button className="danger" disabled={busy} onClick={onConfirm}>
            {busy ? "Deleting…" : "Delete"}
          </button>
          <button className="ghost" onClick={onCancel}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
