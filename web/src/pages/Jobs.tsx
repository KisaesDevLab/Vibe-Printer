import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, Job } from "../api";

interface JobsResp {
  jobs: Job[];
  counts: Record<string, number>;
  depth: number;
}

export function JobsPage() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState("");
  const { data } = useQuery({
    queryKey: ["jobs", filter],
    queryFn: () => api.get<JobsResp>(`/v1/admin/jobs${filter ? `?status=${filter}` : ""}`),
    refetchInterval: 3000,
  });

  const act = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) =>
      api.post(`/v1/admin/jobs/${id}/${action}`, action === "resolve" ? { outcome: "done" } : undefined),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });

  return (
    <div>
      <h2>Jobs</h2>
      <div className="card">
        <div className="row" style={{ marginBottom: 12 }}>
          <span className="muted">Queue depth: {data?.depth ?? 0}</span>
          <select value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 200 }}>
            <option value="">all statuses</option>
            {["queued", "done", "failed", "dead", "uncertain", "canceled"].map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <table>
          <thead>
            <tr>
              <th>Job</th>
              <th>Printer</th>
              <th>Status</th>
              <th>Delivery</th>
              <th>Attempts</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {data?.jobs.map((j) => (
              <tr key={j.id}>
                <td title={j.last_error || ""}>{j.id.slice(0, 8)}</td>
                <td>{j.printer_id}</td>
                <td>
                  <span className={`badge ${j.status === "done" ? "ok" : j.status === "uncertain" || j.status === "dead" ? "err" : ""}`}>
                    {j.status}
                  </span>
                </td>
                <td>{j.delivery || "—"}</td>
                <td>{j.attempts}</td>
                <td className="row">
                  {j.status === "uncertain" && (
                    <button className="ghost" onClick={() => act.mutate({ id: j.id, action: "resolve" })}>
                      Resolve
                    </button>
                  )}
                  {["failed", "dead", "uncertain", "canceled"].includes(j.status) && (
                    <button className="ghost" onClick={() => act.mutate({ id: j.id, action: "requeue" })}>
                      Requeue
                    </button>
                  )}
                  {j.status === "queued" && (
                    <button className="danger" onClick={() => act.mutate({ id: j.id, action: "cancel" })}>
                      Cancel
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
