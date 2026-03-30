import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { fetchMe, login as loginRequest, logout as logoutRequest, setAuthToken } from "./api";
import type { User } from "./types";

type AuthContextState = {
  user: User | null;
  isReady: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextState | null>(null);
const TOKEN_KEY = "psh.jwt";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isReady, setIsReady] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) {
      setIsReady(true);
      return;
    }
    setAuthToken(token);
    fetchMe()
      .then((me) => setUser(me))
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY);
        setAuthToken(null);
      })
      .finally(() => setIsReady(true));
  }, []);

  const value = useMemo<AuthContextState>(
    () => ({
      user,
      isReady,
      login: async (username: string, password: string) => {
        const token = await loginRequest(username, password);
        localStorage.setItem(TOKEN_KEY, token);
        setAuthToken(token);
        const me = await fetchMe();
        setUser(me);
      },
      logout: async () => {
        try {
          await logoutRequest();
        } catch {
          // best effort
        }
        localStorage.removeItem(TOKEN_KEY);
        setAuthToken(null);
        setUser(null);
      },
    }),
    [isReady, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
