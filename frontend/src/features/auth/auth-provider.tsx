"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, ApiError, errorMessage } from "@/lib/http";
import type { User } from "./types";

type AuthState = {
  user: User | null;
  loading: boolean;
  error: string;
  reload: () => Promise<void>;
  setUser: (user: User | null) => void;
};
const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const reload = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setUser(await api<User>("/auth/me"));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setUser(null);
      else setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void reload();
  }, [reload]);
  return (
    <AuthContext.Provider value={{ user, loading, error, reload, setUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("AuthProvider is missing");
  return value;
}
