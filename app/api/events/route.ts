import { NextResponse } from "next/server";
import { z } from "zod";
import {
  actionAllowlist,
  codeAllowlist,
  eventNames,
  providerAllowlist,
  routeAllowlist,
} from "@/lib/analytics";
import { clientKey, rateLimit } from "@/lib/rate-limit";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Server-side allowlist. Even a modified client cannot push free-form values
 * through this route: `.strict()` rejects unknown keys and every field is an
 * enum. Anything that fails is dropped without being logged.
 */
const schema = z
  .object({
    name: z.enum(eventNames),
    at: z.string().datetime(),
    properties: z
      .object({
        route: z.enum(routeAllowlist).optional(),
        theme: z.enum(["dark", "light"]).optional(),
        action: z.enum(actionAllowlist).optional(),
        provider: z.enum(providerAllowlist).optional(),
        code: z.enum(codeAllowlist).optional(),
      })
      .strict(),
  })
  .strict();

export async function POST(request: Request) {
  const origin = request.headers.get("origin");
  if (!origin || new URL(origin).origin !== new URL(request.url).origin) {
    return new NextResponse(null, { status: 403 });
  }

  // Collection is off unless both the public flag and a server URL are set.
  if (
    process.env.NEXT_PUBLIC_ANALYTICS_ENABLED !== "true" ||
    !process.env.ANALYTICS_INGEST_URL
  ) {
    return new NextResponse(null, { status: 204 });
  }

  if (!rateLimit(`events:${clientKey(request)}`, 120, 60).allowed) {
    return new NextResponse(null, { status: 429 });
  }

  if (Number(request.headers.get("content-length") ?? 0) > 2048) {
    return new NextResponse(null, { status: 413 });
  }
  const raw = await request.text();
  if (raw.length > 2048) return new NextResponse(null, { status: 413 });

  let input: unknown;
  try {
    input = JSON.parse(raw);
  } catch {
    return new NextResponse(null, { status: 400 });
  }

  const event = schema.safeParse(input);
  if (!event.success) return new NextResponse(null, { status: 400 });

  try {
    const url = new URL(process.env.ANALYTICS_INGEST_URL);
    if (url.protocol !== "https:") throw new Error("HTTPS_REQUIRED");

    const upstream = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(process.env.ANALYTICS_INGEST_TOKEN
          ? { Authorization: `Bearer ${process.env.ANALYTICS_INGEST_TOKEN}` }
          : {}),
      },
      body: JSON.stringify(event.data),
      signal: AbortSignal.timeout(4000),
      cache: "no-store",
      redirect: "error",
    });
    return new NextResponse(null, { status: upstream.ok ? 204 : 502 });
  } catch {
    return new NextResponse(null, { status: 502 });
  }
}
