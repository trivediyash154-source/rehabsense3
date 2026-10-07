"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  fetchSession,
  signOut as endSession,
  type SessionUser,
} from "@/lib/auth";

type Status = "loading" | "authenticated" | "anonymous";

interface AuthState {
  status: Status;
  user: SessionUser | null;
  /** Re-reads the session from the server; call after signing in or out. */
  refresh: () => Promise<SessionUser | null>;
  /**
   * Adopt the user a successful sign-in or sign-up just returned. That
   * response already came from the server, so asking /me again would only add
   * a round trip before the workspace opens.
   */
  setSignedIn: (user: SessionUser) => void;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState>({
  status: "loading",
  user: null,
  refresh: async () => null,
  setSignedIn: () => {},
  signOut: async () => {},
});

/**
 * Holds the signed-in user for the client tree.
 *
 * The session itself lives in an HttpOnly cookie, so this never stores a
 * credential — it only mirrors who the server says the caller is. That is why
 * a refresh of the browser keeps the user signed in: the cookie survives, and
 * this asks the server again on mount.
 */
export function AuthProvider({
  children,
  initialUser = null,
  serverResolved = false,
}: {
  children: React.ReactNode;
  /** Resolved on the server so the first paint already knows the user. */
  initialUser?: SessionUser | null;
  /**
   * Whether the server actually answered. When it did, `initialUser` is
   * authoritative for both outcomes -- signed in *and* signed out -- so the
   * client skips a mount fetch that would otherwise 401 on every page a
   * signed-out visitor opens.
   */
  serverResolved?: boolean;
}) {
  const [user, setUser] = useState<SessionUser | null>(initialUser);
  const [status, setStatus] = useState<Status>(
    initialUser ? "authenticated" : serverResolved ? "anonymous" : "loading",
  );

  const refresh = useCallback(async () => {
    try {
      const session = await fetchSession();
      setUser(session?.user ?? null);
      setStatus(session ? "authenticated" : "anonymous");
      return session?.user ?? null;
    } catch {
      // A backend that is down is not the same as being signed out; keep the
      // user we already have rather than bouncing them to /login.
      setStatus((current) => (current === "loading" ? "anonymous" : current));
      return null;
    }
  }, []);

  useEffect(() => {
    if (initialUser || serverResolved) return;
    void refresh();
  }, [initialUser, serverResolved, refresh]);

  const setSignedIn = useCallback((next: SessionUser) => {
    setUser(next);
    setStatus("authenticated");
  }, []);

  const signOut = useCallback(async () => {
    try {
      await endSession();
    } finally {
      setUser(null);
      setStatus("anonymous");
    }
  }, []);

  const value = useMemo(
    () => ({ status, user, refresh, setSignedIn, signOut }),
    [status, user, refresh, setSignedIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
