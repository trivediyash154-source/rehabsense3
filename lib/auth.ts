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
  "Unable to connect to the RehabSense API. Nothing was submitted — please try again.";

/** A gateway answered instead of the API (it is down, restarting or unreachable). */
const API_UNREACHABLE = "Unable to connect to the RehabSense API. Please try again in a moment.";

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
    // No JSON body and a gateway status: the request never reached the API.
    if (!body && [502, 503, 504].includes(response.status)) {
      throw new AuthError("API_UNREACHABLE", API_UNREACHABLE, response.status);
    }
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

export type SocialProvider = "google" | "facebook";

export const providerLabel: Record<SocialProvider, string> = {
  google: "Google",
  facebook: "Facebook",
};

/** Which sign-in methods the backend has configured. Never contains a secret. */
export type ProviderStatus = Record<"password" | SocialProvider | "phone", { enabled: boolean }>;

export type ApiAvailability =
  | { state: "available"; providers: ProviderStatus }
  | { state: "not-connected" | "unreachable"; message: string };

/**
 * Can this deployment reach the RehabSense API, and which sign-in methods does
 * it offer? Asked before the user types a password, so the form can say
 * "unavailable" up front instead of failing after submit. `not-connected` is a
 * deployment without an API (BACKEND_ORIGIN=none); `unreachable` is an API
 * that is down or restarting. One request: the providers endpoint needs no
 * database, so it answers quickly even while the database is waking up.
 */
export async function checkApiAvailability(timeoutMs = 8000): Promise<ApiAvailability> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch("/api/auth/providers", { cache: "no-store", signal: controller.signal });
    const body = (await response.json().catch(() => null)) as
      | { code?: string; message?: string; providers?: ProviderStatus }
      | null;
    if (response.ok && body?.providers) return { state: "available", providers: body.providers };
    if (body?.code === "BACKEND_NOT_CONNECTED") {
      return { state: "not-connected", message: body.message ?? API_UNREACHABLE };
    }
    return { state: "unreachable", message: API_UNREACHABLE };
  } catch {
    return { state: "unreachable", message: API_UNREACHABLE };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Where "Continue with Google/Facebook" sends the browser: a top-level
 * navigation to the backend, which redirects to the provider's own page. No
 * provider secret or token ever exists in this code.
 */
export function oauthStartUrl(
  provider: SocialProvider,
  options: { intent?: "login" | "link"; next?: string | null; role?: UserRole | null; rerequest?: boolean } = {},
): string {
  const params = new URLSearchParams();
  if (options.intent === "link") params.set("intent", "link");
  if (options.next && options.next.startsWith("/") && !options.next.startsWith("//")) {
    params.set("next", options.next);
  }
  if (options.role) params.set("role", options.role);
  if (options.rerequest) params.set("rerequest", "true");
  const query = params.toString();
  return `/api/auth/${provider}/start${query ? `?${query}` : ""}`;
}

/** Why a Google/Facebook sign-in came back without signing anyone in. */
export function oauthErrorMessage(code: string, provider: string | null): string {
  const name = provider === "facebook" ? "Facebook" : provider === "google" ? "Google" : "The provider";
  switch (code) {
    case "cancelled":
      return `${name} sign-in was cancelled. Nothing was changed. You can try again or use your email.`;
    case "not_configured":
      return `${name} sign-in is not configured on this deployment yet. Email and password sign-in works.`;
    case "invalid_state":
      return `That ${name} sign-in expired or was already used, so it was not accepted. Please try again.`;
    case "provider_error":
      return `${name} did not confirm your identity, so you were not signed in. Please try again.`;
    case "provider_unreachable":
      return `RehabSense could not reach ${name}. Please try again in a moment.`;
    case "email_unverified":
      return `Your ${name} account's email address is not verified, so it cannot be used to create a RehabSense account.`;
    case "email_required":
      return `${name} did not share an email address, and RehabSense needs one to create your account. Try again and allow email access, or sign up with email.`;
    case "account_exists":
      return `A RehabSense account already uses this ${name} email address. For your security it is not connected automatically: sign in to that account below, and ${name} will then be connected to it.`;
    case "account_disabled":
      return "This RehabSense account is disabled.";
    case "identity_in_use":
      return `That ${name} account is already connected to a different RehabSense account.`;
    case "provider_already_linked":
      return `This account already has a different ${name} account connected. Disconnect it first.`;
    case "link_session_expired":
      return `Your session ended before ${name} could be connected. Sign in and try again.`;
    default:
      return `${name} sign-in did not complete. Please try again.`;
  }
}

export interface SignInMethods {
  password: boolean;
  identities: { provider: SocialProvider | "phone"; email: string | null; linked_at: string; last_used_at: string | null }[];
  available: Record<SocialProvider, boolean>;
}

export function fetchSignInMethods(): Promise<SignInMethods> {
  return authFetch<SignInMethods>("/identities", { method: "GET" });
}

export function disconnectProvider(provider: SocialProvider): Promise<void> {
  return authFetch<void>(`/identities/${provider}`, { method: "DELETE" });
}

/** Permanently delete the signed-in account (DELETE /api/me). */
export async function deleteAccount(confirm: string, password?: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch("/api/me", {
      method: "DELETE",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm, password: password || null }),
      cache: "no-store",
    });
  } catch {
    throw new AuthError("NETWORK_ERROR", UNREACHABLE);
  }
  if (response.status === 204) return;
  const body = (await response.json().catch(() => null)) as { code?: string; message?: string } | null;
  throw new AuthError(body?.code ?? "ERROR", body?.message ?? "The account was not deleted.", response.status);
}

/** Where a role should land after signing in. */
export function homeForRole(role: UserRole): string {
  return role === "PHYSIOTHERAPIST" || role === "ADMIN" ? "/workspace/patients" : "/workspace";
}
