import { ref } from "vue";

const API_KEY = "carbon_api_base";
const FALLBACK_BASES = ["/"];
const apiBase = ref(localStorage.getItem(API_KEY) || FALLBACK_BASES[0]);

function joinUrl(base: string, path: string): string {
  const normalizedBase = String(base || "").trim().replace(/\/+$/, "");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return normalizedBase ? `${normalizedBase}${normalizedPath}` : normalizedPath;
}

function buildBaseCandidates(): string[] {
  const unique = new Set<string>();
  for (const item of FALLBACK_BASES) {
    unique.add(item);
  }
  unique.add(apiBase.value.trim());
  return Array.from(unique).filter(Boolean);
}

function buildFetchOptions(method: string, body: unknown): RequestInit {
  const options: RequestInit = {
    method,
  };

  const token = localStorage.getItem("access_token");
  if (token) {
    options.headers = {
      Authorization: `Bearer ${token}`,
    };
  }

  if (body instanceof FormData) {
    options.body = body;
  } else {
    if (!options.headers) {
      options.headers = {};
    }
    options.headers["Content-Type"] = "application/json";
    if (body !== null) {
      options.body = JSON.stringify(body);
    }
  }

  return options;
}

function parseCurrentRole(): string {
  const token = localStorage.getItem("access_token");
  if (!token) return "user";
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return String(payload?.role || "user").toLowerCase();
  } catch {
    return "user";
  }
}

async function safeFetch(
  url: string,
  options: RequestInit,
  timeout = 8000,
  enableAbort: boolean = true,
): Promise<Response> {
  if (!enableAbort) {
    return await fetch(url, options);
  }
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeout);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    window.clearTimeout(timer);
  }
}

export function useApiBase() {
  const saveApiBase = () => {
    localStorage.setItem(API_KEY, apiBase.value.trim());
  };

  return { apiBase, saveApiBase };
}

export async function callApi<T = unknown>(
  path: string,
  method: string = "GET",
  body: unknown = null,
): Promise<T> {
  const role = parseCurrentRole();
  const upperMethod = String(method || "GET").toUpperCase();
  const isWriteMethod = upperMethod === "PUT" || upperMethod === "PATCH" || upperMethod === "DELETE";
  if (role !== "admin" && isWriteMethod) {
    throw new Error("当前账号无权限执行修改/删除操作");
  }

  const options = buildFetchOptions(method, body);
  const candidates = buildBaseCandidates();
  let lastError: unknown;

  const isUpload = body instanceof FormData;
  const isChatAsk = path === "/api/chat/ask";
  const isAuthLogin = path === "/api/auth/login";
  const isCarbonMarket = path.startsWith("/api/carbon-market/market-price") || path.startsWith("/api/carbon-market/test-carbon-price");
const isEUCarbonPrice = path.startsWith("/api/cbam/eu-carbon-price") || path.startsWith("/api/cbam/test-eu-carbon-price");
  const timeout = isUpload
    ? 60000
    : isChatAsk
      ? 60000
      : isAuthLogin
        ? 30000
        : isCarbonMarket
          ? 45000
          : isEUCarbonPrice
            ? 45000
            : 15000;
  const enableAbort = !isChatAsk;
  for (const base of candidates) {
    try {
      const res = await safeFetch(joinUrl(base, path), options, timeout, enableAbort);
      const text = await res.text();

      let payload: unknown;
      try {
        payload = JSON.parse(text);
      } catch {
        payload = text;
      }

      if (!res.ok) {
        const detail =
          typeof payload === "object"
            ? JSON.stringify(payload, null, 2)
            : String(payload);
        throw new Error(`请求失败 [${res.status}]: ${detail}`);
      }

      if (apiBase.value !== base) {
        apiBase.value = base;
        localStorage.setItem(API_KEY, base);
      }

      return payload as T;
    } catch (error) {
      lastError = error;
    }
  }

  throw lastError instanceof Error
    ? lastError
    : new Error("API 请求失败，未找到可用后端地址");
}


