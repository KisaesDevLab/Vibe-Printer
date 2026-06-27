import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api";

interface RemoteCfg {
  mode: string;
  hostname: string;
  access_team_domain: string;
  access_aud: string;
  cloudflared_metrics_url: string;
  access_enabled: boolean;
  tunnel: string;
}

const EMPTY: RemoteCfg = {
  mode: "lan", hostname: "", access_team_domain: "", access_aud: "",
  cloudflared_metrics_url: "", access_enabled: false, tunnel: "unknown",
};

export function RemoteAccessPage() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["remote"],
    queryFn: () => api.get<RemoteCfg>("/v1/admin/remote"),
    refetchInterval: 15000,
  });
  const [form, setForm] = useState<RemoteCfg>(EMPTY);
  const [msg, setMsg] = useState("");

  useEffect(() => { if (data) setForm(data); }, [data]);

  const save = useMutation({
    mutationFn: () => api.put("/v1/admin/remote", {
      mode: form.mode, hostname: form.hostname,
      access_team_domain: form.access_team_domain, access_aud: form.access_aud,
      cloudflared_metrics_url: form.cloudflared_metrics_url,
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["remote"] }); setMsg("Saved."); },
    onError: (e: Error) => setMsg(e.message),
  });

  const tunnelClass = data?.tunnel === "ready" ? "ok" : data?.tunnel === "unknown" ? "" : "err";

  return (
    <div>
      <h2>Remote Access</h2>

      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>Status</h3>
          <span className="row">
            <span className={`badge ${tunnelClass}`}>tunnel: {data?.tunnel ?? "…"}</span>
            <span className={`badge ${data?.access_enabled ? "ok" : ""}`}>
              Access: {data?.access_enabled ? "enforced" : "off"}
            </span>
          </span>
        </div>
        {form.hostname && (
          <p className="muted" style={{ marginTop: 10 }}>
            Public URL:{" "}
            <a href={`https://${form.hostname}`} target="_blank" rel="noreferrer"
               style={{ color: "var(--accent)" }}>
              https://{form.hostname}
            </a>
          </p>
        )}
      </div>

      <div className="card">
        <h3>Settings</h3>
        <label>Mode</label>
        <select value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}>
          <option value="lan">LAN-only</option>
          <option value="cloudflare">Cloudflare Tunnel</option>
          <option value="tailscale">Tailscale</option>
        </select>

        <label>Public hostname (display-only — provisioned in the Cloudflare dashboard)</label>
        <input value={form.hostname}
               onChange={(e) => setForm({ ...form, hostname: e.target.value })}
               placeholder="print.yourdomain.com" />

        <label>cloudflared metrics URL (for tunnel health)</label>
        <input value={form.cloudflared_metrics_url}
               onChange={(e) => setForm({ ...form, cloudflared_metrics_url: e.target.value })}
               placeholder="http://cloudflared:2000" />

        <h4 style={{ marginBottom: 4 }}>Cloudflare Access (Zero Trust)</h4>
        <p className="error" style={{ fontSize: 13 }}>
          ⚠ Only fill these in when this admin UI is actually fronted by Cloudflare Access —
          otherwise you will lock yourself out of <code>/v1/admin/*</code> (every request will
          require an Access token).
        </p>
        <label>Team domain</label>
        <input value={form.access_team_domain}
               onChange={(e) => setForm({ ...form, access_team_domain: e.target.value })}
               placeholder="yourteam.cloudflareaccess.com" />
        <label>Application AUD tag</label>
        <input value={form.access_aud}
               onChange={(e) => setForm({ ...form, access_aud: e.target.value })} />

        <div style={{ marginTop: 12 }}>
          <button onClick={() => save.mutate()} disabled={save.isPending}>Save</button>
        </div>
        {msg && <p className="muted">{msg}</p>}
      </div>

      <div className="card">
        <h3>How to enable inbound access (Cloudflare Tunnel)</h3>
        <ol className="muted" style={{ lineHeight: 1.7 }}>
          <li>Cloudflare dashboard → <b>Zero Trust → Networks → Tunnels → Create a tunnel</b> →
            Cloudflared. Copy the <b>token</b>.</li>
          <li>Add a <b>Public Hostname</b> → your subdomain → Service <code>HTTP</code> →
            <code>vibe-print:8080</code>.</li>
          <li>On the appliance host: put <code>TUNNEL_TOKEN=…</code> in <code>deploy/.env</code>,
            then <code>docker compose --profile cloudflare up -d</code>.</li>
          <li>Set the hostname above (and Access fields if you added an Access policy). The
            appliance stores no Cloudflare API token and never edits DNS — it only displays this.</li>
        </ol>
      </div>
    </div>
  );
}
