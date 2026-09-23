"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api } from "@/lib/api/client";

/**
 * Holds the in-progress live session above the route.
 *
 * The Live Lab unmounts whenever the user visits another page. If the session
 * id lived in that component, leaving the lab would orphan the session: it
 * stays ACTIVE on the server with a simulator still feeding it, and the user
 * has no control left to stop it. Keeping it here means the lab reattaches on
 * return, and the workspace can always say a session is still running.
 */
type LiveSessionState = {
  sessionId: number | null;
  startedAt: number | null;
  begin: (sessionId: number) => void;
  clear: () => void;
};

const KEY = "rehabsense-live-session";

const LiveSessionContext = createContext<LiveSessionState>({
  sessionId: null,
  startedAt: null,
  begin: () => undefined,
  clear: () => undefined,
});

export function useLiveSessionHandle() {
  return useContext(LiveSessionContext);
}

export function LiveSessionProvider({ children }: { children: ReactNode }) {
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [startedAt, setStartedAt] = useState<number | null>(null);

  // Survives a full page reload too, so refreshing during a stream does not
  // strand the session. Verified against the server before it is trusted.
  useEffect(() => {
    let stored: { id: number; at: number } | null = null;
    try {
      const raw = localStorage.getItem(KEY);
      stored = raw ? (JSON.parse(raw) as { id: number; at: number }) : null;
    } catch {
      stored = null;
    }
    if (!stored?.id) return;

    let cancelled = false;
    api
      .session(stored.id)
      .then((detail) => {
        if (cancelled) return;
        if (detail.status === "ACTIVE") {
          setSessionId(stored.id);
          setStartedAt(stored.at);
        } else {
          // Already ended elsewhere; do not resurrect it.
          try {
            localStorage.removeItem(KEY);
          } catch {
            /* ignore */
          }
        }
      })
      .catch(() => {
        try {
          localStorage.removeItem(KEY);
        } catch {
          /* ignore */
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const begin = useCallback((id: number) => {
    const at = Date.now();
    setSessionId(id);
    setStartedAt(at);
    try {
      localStorage.setItem(KEY, JSON.stringify({ id, at }));
    } catch {
      /* not persisted; the session still works for this page view */
    }
  }, []);

  const clear = useCallback(() => {
    setSessionId(null);
    setStartedAt(null);
    try {
      localStorage.removeItem(KEY);
    } catch {
      /* ignore */
    }
  }, []);

  const value = useMemo(
    () => ({ sessionId, startedAt, begin, clear }),
    [sessionId, startedAt, begin, clear],
  );

  return <LiveSessionContext.Provider value={value}>{children}</LiveSessionContext.Provider>;
}
