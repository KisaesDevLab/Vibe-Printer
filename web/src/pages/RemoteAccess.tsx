import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api";

interface RemoteCfg {
  mode: string;
  hostname: string;
  access_team_domain: string;
  access_aud: string;
  cloudflared_metrics_url: string;
  access_lan_bypass: boolean;
  access_enabled: boolean;
  tunnel: string;
  tunnel_mode: string;
  tunnel_enabled: boolean;
  tunnel_token_set: boolean;
  tunnel_status?: { running: boolean; mode: string | null; url: string | null };
}

const EMPTY: RemoteCfg = {
  mode: "lan", hostname: "", access_team_domain: "", access_aud: "",
  cloudflared_metrics_url: "", access_lan_bypass: true, access_enabled: false, tunnel: "unknown",
  tunnel_mode: "named", tunnel_enabled: false, tunnel_token_set: false,
};

export function RemoteAccessPage() {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["remote"],
    queryFn: () => api.get<RemoteCfg>("/v1/admin/remote"),
    refetchInterval: 15000,
  });
  const [form, setForm] = useState<RemoteCfg>(EMPTY);
  const [token, setToken] = useState("");
  const [msg, setMsg] = useState("");

  useEffect(() => { if (data) setForm(data); }, [data]);

  const tunnelStart = useMutation({
    mutationFn: () => api.post("/v1/admin/remote/tunnel/start", { mode: form.tunnel_mode }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["remote"] }); setMsg("Tunnel starting…"); },
    onError: (e: Error) => setMsg(e.message),
  });
  const tunnelStop = useMutation({
    mutationFn: () => api.post("/v1/admin/remote/tunnel/stop", {}),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["remote"] }); setMsg("Tunnel stopped"); },
    onError: (e: Error) => setMsg(e.message),
  });

  const save = useMutation({
    mutationFn: () => api.put("/v1/admin/remote", {
      mode: form.mode, hostname: form.hostname,
      access_team_domain: form.access_team_domain, access_aud: form.access_aud,
      cloudflared_metrics_url: form.cloudflared_metrics_url,
      access_lan_bypass: form.access_lan_bypass,
      tunnel_mode: form.tunnel_mode,
      ...(token ? { tunnel_token: token } : {}),
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["remote"] });
      setToken("");
      setMsg("Saved.");
    },
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
        <label className="row" style={{ marginTop: 10 }}>
          <input
            type="checkbox"
            style={{ width: "auto" }}
            checked={form.access_lan_bypass}
            onChange={(e) => setForm({ ...form, access_lan_bypass: e.target.checked })}
          />
          <span>Allow direct-LAN access without Access (enforce the JWT only via the tunnel) —
            lets LAN and Cloudflare work at the same time</span>
        </label>

        <div style={{ marginTop: 12 }}>
          <button onClick={() => save.mutate()} disabled={save.isPending}>Save</button>
        </div>
        {msg && <p className="muted">{msg}</p>}
      </div>

      <div className="card">
        <h3>Cloudflare Tunnel (managed)</h3>
        <p className="muted" style={{ fontSize: 13 }}>
          Run a tunnel from this appliance — no host shell needed. <b>Quick</b> gives an instant
          public URL with no Cloudflare account; <b>Named</b> uses a tunnel token for a stable
          hostname (create the tunnel + public hostname → <code>http://localhost:8080</code> in the
          Cloudflare dashboard, then paste the token here).
        </p>
        <div className="row">
          <span className={`badge ${data?.tunnel_status?.running ? "ok" : ""}`}>
            {data?.tunnel_status?.running ? `running (${data.tunnel_status.mode})` : "stopped"}
          </span>
          {data?.tunnel_status?.url && (
            <a href={data.tunnel_status.url} target="_blank" rel="noreferrer"
               style={{ color: "var(--accent)" }}>{data.tunnel_status.url}</a>
          )}
        </div>

        <label>Tunnel mode</label>
        <select value={form.tunnel_mode}
                onChange={(e) => setForm({ ...form, tunnel_mode: e.target.value })}>
          <option value="named">named (token, stable hostname)</option>
          <option value="quick">quick (no token, ephemeral URL)</option>
        </select>

        {form.tunnel_mode === "named" && (
          <>
            <label>
              Tunnel token {form.tunnel_token_set && <span className="badge ok">configured</span>}
            </label>
            <input type="password" value={token} placeholder={form.tunnel_token_set ? "•••••• (leave blank to keep)" : "eyJ..."}
                   onChange={(e) => setToken(e.target.value)} />
          </>
        )}

        <div className="row" style={{ marginTop: 12 }}>
          <button onClick={() => save.mutate()} disabled={save.isPending}>Save token/mode</button>
          <button onClick={() => tunnelStart.mutate()} disabled={tunnelStart.isPending}>Start</button>
          <button className="ghost" onClick={() => tunnelStop.mutate()} disabled={tunnelStop.isPending}>
            Stop
          </button>
        </div>
        <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
          The token is stored on the appliance (write-only here). Enable encryption-at-rest for the
          DB if this box is shipped to a client. The tunnel auto-restarts on reboot once started.
        </p>
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
