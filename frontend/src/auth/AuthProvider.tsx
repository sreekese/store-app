import { createContext, useContext, useEffect, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  clearAccessToken,
  onSessionLost,
  restoreSession,
  signIn,
  signOut,
} from "./client";
import type { AuthResult, Role, User } from "./types";
interface AuthContextValue {
  user: User | null;
  loading: boolean;
  error: Error | null;
  retry: () => void;
  login: (email: string, password: string, role: Role) => Promise<User>;
  logout: () => Promise<void>;
}
const Context = createContext<AuthContextValue | null>(null);
export function AuthProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const session = useQuery({
    queryKey: ["auth-session"],
    queryFn: restoreSession,
    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  useEffect(
    () =>
      onSessionLost(() => {
        client.removeQueries({
          predicate: (query) => query.queryKey[0] !== "auth-session",
        });
        client.setQueryData(["auth-session"], null);
      }),
    [client],
  );
  useEffect(() => {
    const changed = (event: StorageEvent) => {
      if (event.key !== "nearperk-session-event") return;
      clearAccessToken();
      void client.cancelQueries().then(() => {
        client.removeQueries({
          predicate: (query) => query.queryKey[0] !== "auth-session",
        });
        client.setQueryData(["auth-session"], null);
        if (event.newValue?.startsWith("login:"))
          void client.invalidateQueries({ queryKey: ["auth-session"] });
      });
    };
    window.addEventListener("storage", changed);
    return () => window.removeEventListener("storage", changed);
  }, [client]);
  function announce(type: string) {
    try {
      localStorage.setItem(
        "nearperk-session-event",
        type + ":" + crypto.randomUUID(),
      );
    } catch {
      /* Cookie sessions still work when local storage is unavailable. */
    }
  }
  const login = async (email: string, password: string, role: Role) => {
    const result = await signIn(email, password, role);
    await client.cancelQueries();
    client.removeQueries({
      predicate: (query) => query.queryKey[0] !== "auth-session",
    });
    client.setQueryData<AuthResult>(["auth-session"], result);
    announce("login");
    return result.user;
  };
  const logout = async () => {
    await signOut();
    await client.cancelQueries();
    client.removeQueries({
      predicate: (query) => query.queryKey[0] !== "auth-session",
    });
    client.setQueryData(["auth-session"], null);
    announce("logout");
  };
  return (
    <Context.Provider
      value={{
        user: session.data?.user ?? null,
        loading: session.isPending,
        error: session.error,
        retry: () => {
          void session.refetch();
        },
        login,
        logout,
      }}
    >
      {children}
    </Context.Provider>
  );
}
export function useAuth() {
  const context = useContext(Context);
  if (!context) throw new Error("AuthProvider is required");
  return context;
}
