import type { AuthState, LoginResult, UserRole } from "../types/api";

const AUTH_STORAGE_KEY = "cold_chain_frontend_auth";

function readRawAuth(): string | null {
  const sessionValue = sessionStorage.getItem(AUTH_STORAGE_KEY);
  if (sessionValue) {
    return sessionValue;
  }
  const legacyLocalValue = localStorage.getItem(AUTH_STORAGE_KEY);
  if (!legacyLocalValue) {
    return null;
  }
  sessionStorage.setItem(AUTH_STORAGE_KEY, legacyLocalValue);
  localStorage.removeItem(AUTH_STORAGE_KEY);
  return legacyLocalValue;
}

function isRole(value: string): value is UserRole {
  return value === "super_admin" || value === "admin" || value === "driver";
}

export function getAuth(): AuthState | null {
  const raw = readRawAuth();
  if (!raw) {
    return null;
  }

  try {
    const parsed = JSON.parse(raw) as Partial<AuthState>;
    if (
      typeof parsed.token !== "string" ||
      typeof parsed.userId !== "number" ||
      typeof parsed.username !== "string" ||
      typeof parsed.displayName !== "string" ||
      typeof parsed.role !== "string" ||
      !isRole(parsed.role)
    ) {
      return null;
    }
    return {
      token: parsed.token,
      userId: parsed.userId,
      username: parsed.username,
      displayName: parsed.displayName,
      role: parsed.role,
    };
  } catch {
    return null;
  }
}

export function saveAuth(login: LoginResult): AuthState {
  const payload: AuthState = {
    token: login.access_token,
    userId: login.user.user_id,
    username: login.user.username,
    displayName: login.user.display_name || login.user.username,
    role: login.user.role,
  };
  sessionStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(payload));
  localStorage.removeItem(AUTH_STORAGE_KEY);
  return payload;
}

export function clearAuth(): void {
  sessionStorage.removeItem(AUTH_STORAGE_KEY);
  localStorage.removeItem(AUTH_STORAGE_KEY);
}

export function resolveHomePath(role: UserRole | undefined): string {
  if (role === "driver") {
    return "/driver/orders";
  }
  return "/admin/dashboard";
}

export function isSuperAdmin(): boolean {
  return getAuth()?.role === "super_admin";
}
