import "server-only";

/**
 * Minimal fixed-window limiter for a single server instance.
 *
 * This is a guard rail for the prototype, not a production control: it is
 * per-process and resets on redeploy. Put a shared limiter (edge/WAF/Redis) in
 * front of any public deployment.
 */

type Bucket = { count: number; resetAt: number };

const buckets = new Map<string, Bucket>();
const MAX_KEYS = 5000;

export function rateLimit(key: string, limit: number, windowSeconds: number) {
  const now = Date.now();
  const windowMs = windowSeconds * 1000;
  const existing = buckets.get(key);

  if (!existing || existing.resetAt <= now) {
    if (buckets.size > MAX_KEYS) buckets.clear();
    buckets.set(key, { count: 1, resetAt: now + windowMs });
    return { allowed: true, retryAfter: 0 };
  }

  existing.count += 1;
  if (existing.count > limit) {
    return { allowed: false, retryAfter: Math.ceil((existing.resetAt - now) / 1000) };
  }
  return { allowed: true, retryAfter: 0 };
}

/**
 * Best-effort client key. Proxy headers are spoofable, so this only shapes
 * casual abuse; a real deployment should rate limit at the edge.
 */
export function clientKey(request: Request) {
  const forwarded = request.headers.get("x-forwarded-for");
  const ip = forwarded?.split(",")[0]?.trim() || request.headers.get("x-real-ip") || "unknown";
  return ip.slice(0, 64);
}
