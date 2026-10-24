import { clearRefreshToken, writeRefreshToken } from "@/session";
import type { ApiError } from "@/types";

export const API_URL = process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000";

let accessToken: string | null = null;
let refreshToken: string | null = null;

export function currentAccessToken(): string | null {
  return accessToken;
}

export function rememberSession(access: string, refresh: string): void {
  accessToken = access;
  refreshToken = refresh;
}

export async function forgetSession(): Promise<void> {
  accessToken = null;
  refreshToken = null;
  await clearRefreshToken();
}

export class ApiRequestError extends Error {
  code: string;
  status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function parseError(response: Response): Promise<ApiRequestError> {
  try {
    const body = (await response.json()) as ApiError;
    return new ApiRequestError(response.status, body.error.code, body.error.message);
  } catch {
    return new ApiRequestError(response.status, "request_failed", "The request failed.");
  }
}

async function refreshAccess(): Promise<boolean> {
  if (!refreshToken) {
    return false;
  }
  const response = await fetch(`${API_URL}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!response.ok) {
    await forgetSession();
    return false;
  }
  const body = (await response.json()) as { access_token: string; refresh_token: string };
  accessToken = body.access_token;
  refreshToken = body.refresh_token;
  await writeRefreshToken(body.refresh_token);
  return true;
}

export async function api<T>(path: string, init: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
  const response = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (response.status === 401 && retry && accessToken) {
    const renewed = await refreshAccess();
    if (renewed) {
      return api<T>(path, init, false);
    }
  }
  if (!response.ok) {
    throw await parseError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
