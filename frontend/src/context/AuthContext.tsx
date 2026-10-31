"use client";

/**
 * GitHub auth state (Workstream: Login with GitHub).
 *
 * Talks to backend/api/auth.py: OAuth redirect login, instant PAT/App
 * login (server-validated), /api/auth/me session probe, logout. The
 * browser never stores tokens — only the HttpOnly session cookie.
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { resolveApiBase } from "@/hooks/useMissionControlStream";

export interface GitHubUser {
  login: string;
  name: string | null;
  avatar_url: string;
  html_url: string;
  auth_mode: string;
}

interface AuthContextValue {
  user: GitHubUser | null;
  loading: boolean;
  error: string | null;
  loginWithOAuth: () => void;
  loginWithConfigured: () => Promise<void>;
  loginWithToken: (token: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function isUserPayload(value: unknown): value is GitHubUser {
  if (!value || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return typeof v.login === "string" && typeof v.auth_mode === "string";
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const apiBase = resolveApiBase();
  const [user, setUser] = useState<GitHubUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const authErr = params.get("auth_error");
      if (authErr) {
        setError(`Authentication failed: ${authErr}`);
        const clean = new URL(window.location.href);
        clean.searchParams.delete("auth_error");
        window.history.replaceState({}, "", clean.toString());
      } else if (params.get("auth") === "ok") {
        const clean = new URL(window.location.href);
        clean.searchParams.delete("auth");
        window.history.replaceState({}, "", clean.toString());
      }
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${apiBase}/api/auth/me`, { credentials: "include" });
        if (!res.ok) throw new Error("unauthenticated");
        const body: unknown = await res.json();
        if (!cancelled && isUserPayload(body)) setUser(body);
      } catch {
        if (!cancelled) setUser(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [apiBase]);

  const loginWithOAuth = useCallback(() => {
    window.location.href = `${apiBase}/api/auth/github/login`;
  }, [apiBase]);

  const loginWithConfigured = useCallback(async () => {
    setError(null);
    try {
      const res = await fetch(`${apiBase}/api/auth/github/token`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const body: unknown = await res.json().catch(() => null);
      if (!res.ok) {
        const detail =
          body && typeof body === "object" && "detail" in body
            ? String((body as Record<string, unknown>).detail)
            : `Login failed (${res.status})`;
        throw new Error(detail);
      }
      const next =
        body && typeof body === "object" && "user" in body
          ? (body as Record<string, unknown>).user
          : null;
      if (!isUserPayload(next)) throw new Error("Login returned an unexpected payload");
      setUser(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    }
  }, [apiBase]);

  const loginWithToken = useCallback(
    async (token: string) => {
      setError(null);
      try {
        const res = await fetch(`${apiBase}/api/auth/github/token`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token }),
        });
        const body: unknown = await res.json().catch(() => null);
        if (!res.ok) {
          const detail =
            body && typeof body === "object" && "detail" in body
              ? String((body as Record<string, unknown>).detail)
              : `Login failed (${res.status})`;
          throw new Error(detail);
        }
        const next =
          body && typeof body === "object" && "user" in body
            ? (body as Record<string, unknown>).user
            : null;
        if (!isUserPayload(next)) throw new Error("Login returned an unexpected payload");
        setUser(next);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Login failed");
        throw err;
      }
    },
    [apiBase],
  );

  const logout = useCallback(async () => {
    try {
      await fetch(`${apiBase}/api/auth/logout`, {
        method: "POST",
        credentials: "include",
      });
    } catch {
      /* session is gone either way */
    }
    setUser(null);
  }, [apiBase]);

  const value = useMemo<AuthContextValue>(
    () => ({ user, loading, error, loginWithOAuth, loginWithConfigured, loginWithToken, logout }),
    [user, loading, error, loginWithOAuth, loginWithConfigured, loginWithToken, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
