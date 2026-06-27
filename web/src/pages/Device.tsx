import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api";

interface Device {
  name: string;
  timezone: string;
  config: Record<string, unknown>;
  version: number;
}

export function DevicePage() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["device"], queryFn: () => api.get<Device>("/v1/admin/device") });
  const [name, setName] = useState("");
  const [tz, setTz] = useState("");
  const [yaml, setYaml] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (data) {
      setName(data.name);
      setTz(data.timezone);
    }
  }, [data]);

  const save = useMutation({
    mutationFn: () =>
      api.put("/v1/admin/device", {
        name,
        timezone: tz,
        config: data?.config ?? {},
        version: data!.version,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["device"] });
      setMsg("Saved.");
    },
    onError: (e: Error) => setMsg(e.message),
  });

  async function exportConfig() {
    const blob = (await api.post("/v1/admin/config/export")) as unknown as Blob;
    setYaml(await blob.text());
  }
  const importDry = useMutation({
    mutationFn: (dry: boolean) => api.post("/v1/admin/config/import", { yaml, dry_run: dry }),
    onSuccess: (r) => setMsg(`Import plan: ${JSON.stringify(r)}`),
    onError: (e: Error) => setMsg(e.message),
  });

  return (
    <div>
      <h2>Device</h2>
      <div className="card">
        <h3>General</h3>
        <label>Name</label>
        <input value={name} onChange={(e) => setName(e.target.value)} />
        <label>Timezone</label>
        <input value={tz} onChange={(e) => setTz(e.target.value)} />
        <div style={{ marginTop: 12 }}>
          <button disabled={!data || save.isPending} onClick={() => save.mutate()}>
            Save
          </button>
        </div>
      </div>

      <div className="card">
        <h3>Backup / Restore (YAML)</h3>
        <div className="row" style={{ marginBottom: 8 }}>
          <button className="ghost" onClick={exportConfig}>
            Export
          </button>
          <button className="ghost" onClick={() => importDry.mutate(true)} disabled={!yaml}>
            Dry-run import
          </button>
          <button onClick={() => importDry.mutate(false)} disabled={!yaml}>
            Apply import
          </button>
        </div>
        <textarea value={yaml} onChange={(e) => setYaml(e.target.value)} placeholder="config YAML" />
      </div>

      <div className="card">
        <h3>Access</h3>
        <p className="muted">
          Auth is a single shared bearer secret held in this browser's sessionStorage. Rotate it on
          the appliance via <code>VIBE_PRINT_SECRET</code> (rotating breaks existing clients).
        </p>
      </div>

      {msg && <p className="muted">{msg}</p>}
    </div>
  );
}
