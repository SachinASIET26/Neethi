import { NextRequest } from "next/server";
import OpenAI from "openai";
import { fromOpenAICompletion } from "@crayonai/stream";

const MODEL = "c1/anthropic/claude-sonnet-4/v-20251230";

export async function POST(req: NextRequest) {
  const apiKey = process.env.THESYS_API_KEY;
  if (!apiKey) {
    return new Response(
      JSON.stringify({ error: "THESYS_API_KEY is not configured." }),
      { status: 503, headers: { "Content-Type": "application/json" } }
    );
  }

  let body: { messages?: unknown[] };
  try {
    body = await req.json();
  } catch {
    return new Response(
      JSON.stringify({ error: "Invalid JSON body" }),
      { status: 400, headers: { "Content-Type": "application/json" } }
    );
  }

  const client = new OpenAI({
    baseURL: "https://api.thesys.dev/v1/embed",
    apiKey,
  });

  try {
    const llmStream = await client.chat.completions.create({
      model: MODEL,
      messages: (body.messages ?? []) as OpenAI.ChatCompletionMessageParam[],
      stream: true,
    });

    const responseStream = fromOpenAICompletion(llmStream);

    return new Response(responseStream as unknown as BodyInit, {
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
      },
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return new Response(
      JSON.stringify({ error: msg }),
      { status: 502, headers: { "Content-Type": "application/json" } }
    );
  }
}
