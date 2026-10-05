import type { AuthResult, Role, User } from "./types";
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
let accessToken: string | null = null;
let refreshInFlight: Promise<AuthResult | null> | null = null;
const listeners = new Set<() => void>();
export function onSessionLost(callback: () => void) {
  listeners.add(callback);
  return () => {
    listeners.delete(callback);
  };
}
export function clearAccessToken() {
  accessToken = null;
}
export async function raw<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch("/api/v1" + path, {
    ...options,
    credentials: "include",
    signal: AbortSignal.timeout(10000),
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Protection": "1",
      ...options.headers,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      response.status,
      body?.error?.message ||
        "Unable to complete the request. Please try again.",
    );
  }
  if (response.status === 204) return undefined as T;
  if (response.headers.get("content-type")?.startsWith("text/csv"))
    return response.text() as Promise<T>;
  return response.json() as Promise<T>;
}
async function sessionLock<T>(callback: () => Promise<T>): Promise<T> {
  // Cookie rotations are serialized between browser tabs where Web Locks is supported.
  if (navigator.locks)
    return navigator.locks.request("nearperk-session", callback);
  return callback();
}
export async function restoreSession(): Promise<AuthResult | null> {
  if (!refreshInFlight) {
    refreshInFlight = sessionLock(async () => {
      try {
        const result = await raw<AuthResult>("/auth/refresh", {
          method: "POST",
        });
        accessToken = result.access_token;
        return result;
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          accessToken = null;
          return null;
        }
        throw error;
      }
    }).finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}
export async function signIn(
  email: string,
  password: string,
  workspace: Role,
): Promise<AuthResult> {
  if (refreshInFlight) await refreshInFlight.catch(() => null);
  return sessionLock(async () => {
    const result = await raw<AuthResult>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password, workspace }),
    });
    accessToken = result.access_token;
    return result;
  });
}
export function registerAccount(data: {
  email: string;
  password: string;
  display_name: string;
  role: "USER" | "MERCHANT";
}) {
  return raw<User>("/auth/register", {
    method: "POST",
    body: JSON.stringify(data),
  });
}
export async function signOut() {
  if (refreshInFlight) await refreshInFlight.catch(() => null);
  await sessionLock(() => raw<void>("/auth/logout", { method: "POST" }));
  accessToken = null;
}
export async function authorized<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  try {
    return await raw<T>(path, {
      ...options,
      headers: {
        ...options.headers,
        ...(accessToken ? { Authorization: "Bearer " + accessToken } : {}),
      },
    });
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error;
    const refreshed = await restoreSession();
    if (!refreshed) {
      listeners.forEach((fn) => fn());
      throw new ApiError(401, "Your session ended. Please sign in again.");
    }
    try {
      return await raw<T>(path, {
        ...options,
        headers: {
          ...options.headers,
          Authorization: "Bearer " + refreshed.access_token,
        },
      });
    } catch (retryError) {
      if (retryError instanceof ApiError && retryError.status === 401) {
        accessToken = null;
        listeners.forEach((fn) => fn());
      }
      throw retryError;
    }
  }
}
