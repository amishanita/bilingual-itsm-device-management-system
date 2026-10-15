/**
 * API client. Adds the access token and Accept-Language to every request and
 * turns error responses into ApiError with the server's error code.
 */

import { getLang } from "./i18n.js";
import { clearSession, getToken } from "./auth.js";

/**
 * Where the API lives. In production Caddy serves the pages and proxies /api
 * on the same origin. In local development the pages are served on port 8080
 * and the API runs on port 8000.
 */
export const API_BASE =
  window.location.port === "8080"
    ? `${window.location.protocol}//${window.location.hostname}:8000/api`
    : "/api";

/** An API failure with the stable error code from {"detail": {"code", "message"}}. */
export class ApiError extends Error {
  /**
   * @param {string} code Error code, for example INVALID_CREDENTIALS.
   * @param {number} status HTTP status, or 0 when the server could not be reached.
   * @param {object} [detail] The full detail object (for example row errors).
   */
  constructor(code, status, detail = {}) {
    super(detail.message || code);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Call the API and return the parsed JSON body (or null for 204).
 *
 * A 401 on an authenticated request means the session is no longer valid:
 * the session is cleared and the browser goes back to the sign-in page.
 * @param {string} path Path below /api, for example "/auth/me".
 * @param {{method?: string, body?: object|FormData, auth?: boolean}} [options]
 * @returns {Promise<any>}
 */
export async function api(path, { method = "GET", body, auth = true } = {}) {
  const headers = { Accept: "application/json", "Accept-Language": getLang() };
  const token = auth ? getToken() : null;
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  let payload;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, { method, headers, body: payload });
  } catch {
    throw new ApiError("NETWORK_ERROR", 0);
  }

  if (response.status === 204) {
    return null;
  }
  let data = null;
  try {
    data = await response.json();
  } catch {
    // Not JSON (for example a proxy error page); handled below by status.
  }
  if (response.ok) {
    return data;
  }

  const detail = data && typeof data.detail === "object" ? data.detail : {};
  const code = detail.code || "UNKNOWN_ERROR";
  if (response.status === 401 && token) {
    clearSession();
    const next = encodeURIComponent(window.location.pathname.split("/").pop() || "");
    window.location.assign(`index.html?reason=expired&next=${next}`);
  }
  throw new ApiError(code, response.status, detail);
}
