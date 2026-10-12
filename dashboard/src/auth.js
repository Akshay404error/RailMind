// RailMind - dashboard auth helpers (v2)
export const API = import.meta.env.VITE_API_URL || "/api"; // same Vite proxy as api.js
const KEY = "railmind_token";

export const getToken = () => localStorage.getItem(KEY);
export const setToken = (t) => localStorage.setItem(KEY, t);

// Clears the session locally and sends the user back to the login screen.
export function clearSession() {
  localStorage.removeItem(KEY);
  window.dispatchEvent(new Event("auth-expired"));
}

// Records the sign-out on the server (best effort), then clears the session.
export async function logout() {
  try {
    await authFetch("/auth/logout", { method: "POST" });
  } catch {
    /* ignore */
  }
  clearSession();
}

async function readError(res) {
  try {
    const j = await res.json();
    return typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
  } catch {
    return `Request failed (${res.status})`;
  }
}

// Use this instead of fetch() for every API call. `path` starts with "/".
export async function authFetch(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  const t = getToken();
  if (t) headers.Authorization = `Bearer ${t}`;
  const res = await fetch(`${API}${path}`, { ...opts, headers });
  if (res.status === 401 && t) clearSession();
  return res;
}

async function post(path, body) {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export const requestOtp = (email) => post("/auth/request-otp", { email });
export const verifyOtp = (email, code) => post("/auth/verify-otp", { email, code });
export const registerUser = (signup_token, details) =>
  post("/auth/register", { signup_token, ...details });

export async function fetchMe() {
  const res = await authFetch("/auth/me");
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

// Download any file endpoint through authFetch (adds the login token).
export async function downloadFile(path, filename) {
  const res = await authFetch(path);
  if (!res.ok) throw new Error(await readError(res));
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// params e.g. { train_number: "03686", section_index: 3, delay_min: 20 }
export function downloadReportPdf(params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
  ).toString();
  return downloadFile(`/report/pdf${qs ? "?" + qs : ""}`, "railmind_report.pdf");
}

export async function getJson(path) {
  const res = await authFetch(path);
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function postJson(path) {
  const res = await authFetch(path, { method: "POST" });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}