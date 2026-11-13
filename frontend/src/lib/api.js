/* Tiny API client: bearer token in localStorage, same-origin by default so the
   Vite dev proxy (and nginx in Docker) take care of routing. */

const TOKEN_KEY = "jarvis_token";
const API_BASE = import.meta.env.VITE_API_BASE || "";
const WS_BASE = import.meta.env.VITE_WS_BASE || "";

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

export function setToken(token) {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* storage can be disabled — the session still works */
  }
}

export function clearToken() {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

function safeJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

export async function api(path, { method = "GET", body, token, signal } = {}) {
  const headers = { Authorization: `Bearer ${token ?? getToken()}` };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    signal,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (response.status === 204) return null;

  const text = await response.text();
  const data = text ? safeJson(text) : null;

  if (!response.ok) {
    const detail =
      (data && (data.detail || data.message)) || `${response.status} ${response.statusText}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

export function wsUrl(token) {
  if (WS_BASE) {
    return `${WS_BASE.replace(/\/$/, "")}/ws?token=${encodeURIComponent(token)}`;
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws?token=${encodeURIComponent(token)}`;
}

export function apiBase() {
  return API_BASE;
}
