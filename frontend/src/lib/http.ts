import axios, { type AxiosResponse } from "axios";

import { clearAuth, getAuth } from "./auth";
import { appEnv } from "../config/env";
import type { ApiResponse } from "../types/api";

export const api = axios.create({
  baseURL: appEnv.apiBaseUrl,
  timeout: 15000,
});

type ApiErrorDetailItem = {
  loc?: Array<string | number>;
  msg?: string;
  type?: string;
};

function formatValidationDetail(item: ApiErrorDetailItem): string {
  const message = typeof item.msg === "string" ? item.msg.trim() : "";
  if (!message) {
    return "";
  }
  const locParts = Array.isArray(item.loc)
    ? item.loc
        .map((part) => String(part).trim())
        .filter((part) => part && part !== "body" && part !== "query" && part !== "path")
    : [];
  if (locParts.length === 0) {
    return message;
  }
  return `${locParts.join(".")}: ${message}`;
}

function shouldBypassMonitorCache(url?: string, method?: string): boolean {
  return (
    (method || "get").toLowerCase() === "get" &&
    typeof url === "string" &&
    url.startsWith("/monitor/")
  );
}

api.interceptors.request.use((config) => {
  const auth = getAuth();
  if (auth?.token) {
    config.headers.Authorization = `Bearer ${auth.token}`;
  }
  if (shouldBypassMonitorCache(config.url, config.method)) {
    config.params = {
      ...(config.params ?? {}),
      _ts: Date.now(),
    };
    config.headers["Cache-Control"] = "no-cache";
    config.headers.Pragma = "no-cache";
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (axios.isAxiosError(error) && error.response?.status === 401) {
      clearAuth();
      if (!window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  },
);

export function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const payload = error.response?.data as
      | {
          detail?: string | ApiErrorDetailItem[];
          msg?: string;
        }
      | undefined;
    if (typeof payload?.msg === "string" && payload.msg.trim()) {
      return payload.msg;
    }
    if (typeof payload?.detail === "string" && payload.detail.trim()) {
      return payload.detail;
    }
    if (Array.isArray(payload?.detail) && payload.detail.length > 0) {
      const firstMessage = formatValidationDetail(payload.detail[0]);
      if (firstMessage) {
        return firstMessage;
      }
    }
    if (typeof error.message === "string" && error.message.trim()) {
      return error.message;
    }
  }
  if (error instanceof Error && typeof error.message === "string" && error.message.trim()) {
    return error.message;
  }
  return "请求失败，请稍后重试";
}

export async function unwrap<T>(
  request: Promise<AxiosResponse<ApiResponse<T>>>,
): Promise<T> {
  const response = await request;
  return response.data.data;
}
