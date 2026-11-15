"use client";

import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, refreshAccessToken, setAccessToken, setSessionExpiredHandler } from "./api";
import type { Role, User } from "./types";

interface AuthState {
  user: User | null;
  ready: boolean; // finished the initial "am I already logged in?" check
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  can: (...roles: Role[]) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const queryClient = useQueryClient();

  // On page load the access token (memory only) is gone, but the httpOnly
  // refresh cookie may still be valid: try to restore the session silently.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (await refreshAccessToken()) {
        try {
          const me = await api<User>("/api/auth/me/");
          if (!cancelled) setUser(me);
        } catch {
          /* not logged in */
        }
      }
      if (!cancelled) setReady(true);
    })();
    setSessionExpiredHandler(() => {
      setAccessToken(null);
      setUser(null);
      queryClient.clear();
    });
    return () => {
      cancelled = true;
      setSessionExpiredHandler(null);
    };
  }, [queryClient]);

  const login = useCallback(async (username: string, password: string) => {
    const res = await api<{ access: string; user: User }>("/api/auth/login/", {
      method: "POST",
      body: { username, password },
    });
    setAccessToken(res.access);
    setUser(res.user);
  }, []);

  const logout = useCallback(async () => {
    await api("/api/auth/logout/", { method: "POST" }).catch(() => undefined);
    setAccessToken(null);
    setUser(null);
    queryClient.clear(); // never show the previous user's cached data
  }, [queryClient]);

  const can = useCallback((...roles: Role[]) => !!user && roles.includes(user.role), [user]);

  const value = useMemo(() => ({ user, ready, login, logout, can }), [user, ready, login, logout, can]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
