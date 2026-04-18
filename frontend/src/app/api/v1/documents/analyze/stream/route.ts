/**
 * SSE proxy for document analysis.
 *
 * Next.js's rewrites() proxy buffers responses and doesn't handle long-lived
 * SSE connections (PageIndex tree generation can take ~2 minutes). This API
 * route pipes the stream directly, bypassing the rewrite layer.
 */
import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
// Allow up to 60 seconds (Vercel Hobby plan limit)
export const maxDuration = 60;

export async function POST(req: NextRequest) {
  const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

  // Forward auth header sent by the browser fetch in api.ts
  const authorization = req.headers.get("authorization") ?? "";

  let formData: FormData;
  try {
    formData = await req.formData();
  } catch {
    return new Response(JSON.stringify({ detail: "Invalid form data" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  let backendResp: Response;
  try {
    backendResp = await fetch(
      `${backendUrl}/api/v1/documents/analyze/stream`,
      {
        method: "POST",
        headers: {
          ...(authorization ? { Authorization: authorization } : {}),
          Accept: "text/event-stream",
        },
        body: formData,
        // @ts-expect-error - required by Node.js fetch for streaming request bodies
        duplex: "half",
      },
    );
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return new Response(JSON.stringify({ detail: `Backend unreachable: ${msg}` }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }

  if (!backendResp.ok) {
    const text = await backendResp.text().catch(() => `HTTP ${backendResp.status}`);
    return new Response(text, {
      status: backendResp.status,
      headers: { "Content-Type": "application/json" },
    });
  }

  // Pipe the backend SSE body directly to the client with no buffering.
  return new Response(backendResp.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      "X-Accel-Buffering": "no",
      Connection: "keep-alive",
    },
  });
}
