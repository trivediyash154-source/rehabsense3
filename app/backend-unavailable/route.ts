import { NextResponse } from "next/server";
import { backendConnected } from "@/lib/config.server";

/**
 * Where next.config.ts rewrites /api/* when the deployment declares
 * BACKEND_ORIGIN=none (frontend live, API not hosted yet).
 *
 * Every backend call gets an explicit, machine-readable answer rather than an
 * HTML 404: the sign-in form shows this message, and the backend probe sees a
 * non-OK status, so the workspace labels its figures "DEMO DATA · NO BACKEND
 * CONNECTED". This app's own routes (/api/contact, /api/events) are files and
 * are matched before the rewrite, so they are unaffected.
 */
export const dynamic = "force-dynamic";

function unavailable(): NextResponse {
  if (backendConnected()) {
    // With an API configured, /api/* is proxied and never lands here.
    return NextResponse.json({ code: "NOT_FOUND", message: "Not found." }, { status: 404 });
  }
  return NextResponse.json(
    {
      code: "BACKEND_NOT_CONNECTED",
      message:
        "This deployment is not connected to the RehabSense API yet, so sign-in, patient " +
        "records and live sessions are unavailable. The public pages and the illustrative " +
        "demo still work.",
    },
    { status: 503, headers: { "Cache-Control": "no-store" } },
  );
}

export const GET = unavailable;
export const POST = unavailable;
export const PUT = unavailable;
export const PATCH = unavailable;
export const DELETE = unavailable;
