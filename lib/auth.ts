/**
 * Browser authentication.
 *
 * These call this app's own `/api/auth/*`, which Next proxies to the backend.
 * Because the request is same-origin, the session lives in an HttpOnly cookie
 * the browser attaches automatically: no token is ever held in JavaScript, so
 * there is nothing here for an injected script to read or for this module to
 * accidentally persist.
 *
 * Nothing in this file is a secret, which matters because everything a client
 * component imports ships to the browser.
 */

export type UserRole = "PATIENT" | "PHYSIOTHERAPIST" | "TECHNICIAN" | "ADMIN";

export interface SessionUser {
  id: number;
  email: string;
  name: string;
  preferred_name: string | null;
  phone: string | null;
  role: UserRole;
  timezone: string;
  avatar_url: string | null;
  preferences: Record<string, unknown>;
  created_at: string;
}

export interface AuthSession {
  user: SessionUser;
  expires_in: number;
}

/** A field-level message from the backend's validation contract. */
export interface FieldError {
  field: string;
  message: string;
}

export class AuthError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status = 0,
    readonly fields: FieldError[] = [],
  ) {
    super(message);
    this.name = "AuthError";
  }
}

const UNREACHABLE =
  "We could not reach the authentication service. Nothing was submitted — please check that the backend is running and try again.";

async function authFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/auth${path}`, {
      ...init,
      // Same-origin already sends the cookie; stated explicitly so the
      // intent survives any future move to a different origin.
      credentials: "include",
      headers: { "Content-Type": "application/json", ...init.headers },
      cache: "no-store",
    });
  } catch {
    throw new AuthError("NETWORK_ERROR", UNREACHABLE);
  }

  if (response.status === 204) return undefined as T;

  const body = (await response.json().catch(() => null)) as
    | { code?: string; message?: string; fields?: FieldError[] }
    | null;

  if (!response.ok) {
    throw new AuthError(
      body?.code ?? "ERROR",
      body?.message ?? "Something went wrong. Please try again.",
      response.status,
      body?.fields ?? [],
    );
  }
  return body as T;
}

export interface SignUpInput {
  name: string;
  email: string;
  password: string;
  phone?: string;
  role?: UserRole;
}

export function signUp(input: SignUpInput): Promise<AuthSession> {
  return authFetch<AuthSession>("/signup", {
    method: "POST",
    body: JSON.stringify({
      name: input.name.trim(),
      email: input.email.trim().toLowerCase(),
      password: input.password,
      phone: input.phone?.trim() || null,
      role: input.role ?? "PATIENT",
    }),
  });
}

export function signIn(email: string, password: string): Promise<AuthSession> {
  return authFetch<AuthSession>("/login", {
    method: "POST",
    body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
  });
}

export function signOut(): Promise<void> {
  return authFetch<void>("/logout", { method: "POST" });
}

/**
 * The current session, or null when signed out.
 *
 * A 401 is the normal signed-out answer, not an error worth surfacing; any
 * other failure is rethrown so a broken backend is not mistaken for a logged
 * out user.
 */
export async function fetchSession(): Promise<AuthSession | null> {
  try {
    return await authFetch<AuthSession>("/me", { method: "GET" });
  } catch (error) {
    if (error instanceof AuthError && error.status === 401) return null;
    throw error;
  }
}

/** A short-lived ticket authorising one live-session WebSocket. */
export async function requestLiveTicket(sessionId: number): Promise<string> {
  const body = await authFetch<{ ticket: string }>("/ws-ticket", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId }),
  });
  return body.ticket;
}

/** Where a role should land after signing in. */
export function homeForRole(role: UserRole): string {
  return role === "PHYSIOTHERAPIST" || role === "ADMIN" ? "/workspace/patients" : "/workspace";
}
