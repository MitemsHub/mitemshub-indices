/** GET /api/system/ping — minimal heartbeat endpoint.
 *  Zero imports, zero subprocesses, zero file I/O.
 *  Returns `{ ok: true, ts: "<ISO string>" }`.
 *  Suitable for load-balancer health checks and monitoring automation. */
export function GET(): Response {
  return new Response(
    JSON.stringify({ ok: true, ts: new Date().toISOString() }),
    {
      status: 200,
      headers: { "Content-Type": "application/json" },
    },
  );
}
