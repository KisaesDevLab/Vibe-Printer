import { useEffect, useState } from "react";
import { api, getSecret, setSecret } from "./api";
import { useI18n } from "./i18n";
import { DevicePage } from "./pages/Device";
import { FormatsPage } from "./pages/Formats";
import { JobsPage } from "./pages/Jobs";
import { OverlaysPage } from "./pages/Overlays";
import { PrintersPage } from "./pages/Printers";
import { RemoteAccessPage } from "./pages/RemoteAccess";
import { TemplatesPage } from "./pages/Templates";

type Tab = "printers" | "formats" | "templates" | "overlays" | "jobs" | "remote" | "device";

const TABS: { id: Tab; key: string }[] = [
  { id: "printers", key: "printers" },
  { id: "formats", key: "formats" },
  { id: "templates", key: "templates" },
  { id: "overlays", key: "overlays" },
  { id: "jobs", key: "jobs" },
  { id: "remote", key: "remote" },
  { id: "device", key: "device" },
];

function SecretGate({ onAuthed }: { onAuthed: () => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError("");
    setSecret(value);
    try {
      await api.get("/v1/printers"); // probe
      onAuthed();
    } catch {
      setError("Invalid secret.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="center">
      <div className="card gate">
        <h1>Vibe Print</h1>
        <p className="muted">Enter the shared secret to manage this appliance.</p>
        <input
          type="password"
          value={value}
          autoFocus
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder="VIBE_PRINT_SECRET"
        />
        {error && <p className="error">{error}</p>}
        <div style={{ marginTop: 12 }}>
          <button onClick={submit} disabled={busy || !value}>
            {busy ? "Checking…" : "Unlock"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function App() {
  const [authed, setAuthed] = useState(!!getSecret());
  const [tab, setTab] = useState<Tab>("printers");
  const { t, lang, setLang } = useI18n();

  useEffect(() => {
    const onUnauth = () => setAuthed(false);
    window.addEventListener("vibe-unauthorized", onUnauth);
    return () => window.removeEventListener("vibe-unauthorized", onUnauth);
  }, []);

  if (!authed) return <SecretGate onAuthed={() => setAuthed(true)} />;

  return (
    <div className="shell">
      <nav className="nav">
        <h1>Vibe Print</h1>
        {TABS.map((item) => (
          <a
            key={item.id}
            className={tab === item.id ? "active" : ""}
            onClick={() => setTab(item.id)}
          >
            {t(item.key)}
          </a>
        ))}
        <a style={{ marginTop: 24 }} onClick={() => setAuthed(false)}>
          {t("lock")}
        </a>
        <select
          value={lang}
          onChange={(e) => setLang(e.target.value as "en" | "es")}
          style={{ marginTop: 16 }}
        >
          <option value="en">English</option>
          <option value="es">Español</option>
        </select>
      </nav>
      <main className="main">
        {tab === "printers" && <PrintersPage />}
        {tab === "formats" && <FormatsPage />}
        {tab === "templates" && <TemplatesPage />}
        {tab === "overlays" && <OverlaysPage />}
        {tab === "jobs" && <JobsPage />}
        {tab === "remote" && <RemoteAccessPage />}
        {tab === "device" && <DevicePage />}
      </main>
    </div>
  );
}
