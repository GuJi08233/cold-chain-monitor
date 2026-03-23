function normalize(value: string | undefined, fallback: string): string {
  const text = (value || "").trim();
  if (!text) {
    return fallback;
  }
  if (text.length > 1 && text.endsWith("/")) {
    return text.slice(0, -1);
  }
  return text;
}

export const appEnv = {
  apiBaseUrl: normalize(import.meta.env.VITE_API_BASE_URL, "/api"),
  wsBaseUrl: normalize(import.meta.env.VITE_WS_BASE_URL, "/ws"),
};

function joinPath(base: string, suffix: string): string {
  const left = base.endsWith("/") ? base.slice(0, -1) : base;
  const right = suffix.startsWith("/") ? suffix : `/${suffix}`;
  return `${left}${right}`;
}

function toAbsoluteWsBase(base: string): string {
  if (base.startsWith("ws://") || base.startsWith("wss://")) {
    return base;
  }
  if (base.startsWith("http://") || base.startsWith("https://")) {
    return base.replace(/^http/i, "ws");
  }
  if (base.startsWith("/")) {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    return `${protocol}://${window.location.host}${base}`;
  }
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${base}`;
}

export function buildWsUrl(path: string, query?: Record<string, string>): string {
  const base = toAbsoluteWsBase(appEnv.wsBaseUrl);
  const url = new URL(joinPath(base, path));
  if (query) {
    Object.entries(query).forEach(([key, value]) => {
      url.searchParams.set(key, value);
    });
  }
  return url.toString();
}
