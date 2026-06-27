// Minimal TypeScript client for Vibe Print with an idempotency key (P23.6).
//   deno run -A examples/client.ts http://localhost:8080 <secret> <printerId>

const [base, secret, printerId] = Deno.args;
const headers = {
  Authorization: `Bearer ${secret}`,
  "Content-Type": "application/json",
  "Idempotency-Key": crypto.randomUUID(),
};

const body = {
  printer: Number(printerId),
  document: {
    elements: [
      { type: "text", value: "{{ data.company }}", align: "center", bold: true },
      { type: "rule" },
      { type: "cut" },
    ],
  },
  data: { company: "Acme" },
};

const res = await fetch(`${base}/v1/print`, { method: "POST", headers, body: JSON.stringify(body) });
const { job_id } = await res.json();
console.log("enqueued", job_id);

for (let i = 0; i < 20; i++) {
  const s = await (await fetch(`${base}/v1/jobs/${job_id}`, { headers })).json();
  console.log("status:", s.status, "delivery:", s.delivery);
  if (["done", "failed", "dead", "uncertain", "canceled"].includes(s.status)) break;
  await new Promise((r) => setTimeout(r, 500));
}
