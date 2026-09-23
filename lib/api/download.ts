"use client";

import { API_BASE } from "./client";

export class DownloadError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
    this.name = "DownloadError";
  }
}

/**
 * Fetch a file from the API and hand it to the browser.
 *
 * Deliberately not a plain `<a href>`: an anchor cannot send the session
 * cookie's `credentials` semantics predictably across environments, and a
 * failed navigation would replace the workspace with a raw error page. This
 * fetches first, so a failure is an ordinary rejected promise the caller can
 * show inline — a broken export must never take the workspace down with it.
 */
export async function downloadFile(path: string, filename: string): Promise<number> {
  const response = await fetch(`${API_BASE}/api${path}`, {
    credentials: "include",
    cache: "no-store",
  });

  if (!response.ok) {
    let message = `Export failed (${response.status}).`;
    try {
      const body = (await response.json().catch(() => null)) as { message?: string } | null;
      if (body?.message) message = body.message;
    } catch {
      /* non-JSON error body; the status message stands */
    }
    throw new DownloadError(response.status, message);
  }

  const blob = await response.blob();
  if (blob.size === 0) {
    throw new DownloadError(response.status, "The export came back empty.");
  }

  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    // Revoked on the next tick so the click has taken the URL first;
    // leaking object URLs is a slow memory leak across repeated exports.
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  }
  return blob.size;
}
