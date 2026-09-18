import { NextRequest, NextResponse } from "next/server";

/**
 * Server-side proxy for browser-originated API calls.
 *
 * The browser cannot hold the API key: anything shipped to it is readable in
 * devtools and in the JS bundle. Client components therefore call this route, which
 * runs in the Next process, attaches the key from a server-only env var, and
 * forwards to Django. The credential never crosses the network to the user.
 */
const BACKEND = process.env.BACKEND_ORIGIN ?? "http://127.0.0.1:8000";

async function forward(request: NextRequest, path: string[]) {
  const target = `${BACKEND}/api/${path.join("/")}${request.nextUrl.search}`;

  const headers = new Headers();
  const key = process.env.MARSLICK_API_KEY || "marslick-demo-key-2026";
  if (key) headers.set("X-API-Key", key);

  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);

  const init: RequestInit = { method: request.method, headers };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }

  const upstream = await fetch(target, init);
  const body = await upstream.arrayBuffer();

  return new NextResponse(body, {
    status: upstream.status,
    headers: {
      "content-type":
        upstream.headers.get("content-type") ?? "application/json",
    },
  });
}

export async function GET(
  request: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
) {
  return forward(request, (await ctx.params).path);
}

export async function POST(
  request: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
) {
  return forward(request, (await ctx.params).path);
}
