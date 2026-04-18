/**
 * SSE proxy for conversation turn streaming.
 *
 * Next.js's rewrites() proxy buffers responses and doesn't handle long-lived
 * SSE connections (the CrewAI pipeline can take 2-10 minutes for full runs).
 * This API route pipes the stream directly to the client, bypassing the
 * rewrite layer entirely.
 *
 * Pattern is identical to /api/v1/documents/analyze/stream/route.ts but
 * forwards a JSON body instead of FormData.
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

  let body: string;
  try {
    body = await req.text();
  } catch {
    return new Response(JSON.stringify({ detail: "Invalid request body" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  let backendResp: Response;
  try {
    backendResp = await fetch(
      `${backendUrl}/api/v1/conversation/turn/stream`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(authorization ? { Authorization: authorization } : {}),
          Accept: "text/event-stream",
        },
        body,
        // @ts-expect-error - required by Node.js fetch for streaming
        duplex: "half",
      },
    );
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return new Response(
      JSON.stringify({ detail: `Backend unreachable: ${msg}` }),
      {
        status: 502,
        headers: { "Content-Type": "application/json" },
      },
    );
  }

  if (!backendResp.ok) {
    const text = await backendResp
      .text()
      .catch(() => `HTTP ${backendResp.status}`);
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
