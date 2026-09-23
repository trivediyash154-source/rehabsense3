import { NextResponse } from "next/server";
import { contactSchema } from "@/lib/validations";
import { audit } from "@/lib/audit-log";
import { clientKey, rateLimit } from "@/lib/rate-limit";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_BODY = 16_000;

function sameOrigin(request: Request) {
  const origin = request.headers.get("origin");
  if (!origin) return false;
  try {
    return new URL(origin).origin === new URL(request.url).origin;
  } catch {
    return false;
  }
}

export async function POST(request: Request) {
  if (!sameOrigin(request)) {
    return NextResponse.json({ message: "Request origin not accepted." }, { status: 403 });
  }
  if (!request.headers.get("content-type")?.includes("application/json")) {
    return NextResponse.json({ message: "Expected a JSON request." }, { status: 415 });
  }
  if (Number(request.headers.get("content-length") ?? 0) > MAX_BODY) {
    return NextResponse.json({ message: "Your message is too large." }, { status: 413 });
  }

  const limit = Number(process.env.CONTACT_RATE_LIMIT ?? 5);
  const windowSeconds = Number(process.env.CONTACT_RATE_WINDOW_SECONDS ?? 600);
  const gate = rateLimit(`contact:${clientKey(request)}`, limit, windowSeconds);
  if (!gate.allowed) {
    await audit("rate_limit", "rejected", "CONTACT_RATE_LIMITED");
    return NextResponse.json(
      {
        code: "CONTACT_RATE_LIMITED",
        message: "Too many messages from this connection. Please try again shortly.",
      },
      { status: 429, headers: { "Retry-After": String(gate.retryAfter) } },
    );
  }

  const text = await request.text();
  if (text.length > MAX_BODY) {
    return NextResponse.json({ message: "Your message is too large." }, { status: 413 });
  }

  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    return NextResponse.json({ message: "Invalid request." }, { status: 400 });
  }

  // Server-side validation. The client schema is a convenience, not the gate.
  const result = contactSchema.safeParse(body);
  if (!result.success) {
    // Field contents are never logged — only that validation failed.
    return NextResponse.json(
      { message: "Please review the form fields and try again." },
      { status: 400 },
    );
  }

  const endpoint = process.env.CONTACT_DELIVERY_URL;
  if (!endpoint) {
    await audit("contact_delivery", "unavailable", "CONTACT_NOT_CONFIGURED");
    return NextResponse.json(
      {
        code: "CONTACT_NOT_CONFIGURED",
        message:
          "Contact delivery is not connected in this prototype. Your message has not been sent or stored.",
      },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }

  try {
    const destination = new URL(endpoint);
    if (destination.protocol !== "https:") throw new Error("HTTPS_REQUIRED");

    // The honeypot never leaves this process.
    const { website: _honeypot, ...contact } = result.data;
    void _honeypot;

    const response = await fetch(destination, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(process.env.CONTACT_DELIVERY_TOKEN
          ? { Authorization: `Bearer ${process.env.CONTACT_DELIVERY_TOKEN}` }
          : {}),
      },
      body: JSON.stringify({
        ...contact,
        source: "rehabsense",
        receivedAt: new Date().toISOString(),
      }),
      signal: AbortSignal.timeout(15_000),
      cache: "no-store",
      redirect: "error",
    });

    if (!response.ok) throw new Error("UPSTREAM_REJECTED");

    await audit("contact_delivery", "accepted", "DELIVERED");
    return NextResponse.json({ received: true }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    // Delivery could not be confirmed, so the user is never told it was sent.
    await audit("integration_failure", "rejected", "CONTACT_DELIVERY_FAILED");
    return NextResponse.json(
      {
        code: "CONTACT_DELIVERY_FAILED",
        message:
          "We couldn't confirm delivery, so your message has not been marked as received. Please try again.",
      },
      { status: 502 },
    );
  }
}
