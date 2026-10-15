/**
 * Session handling: sign in, sign out, and page guards.
 *
 * The access token is kept in sessionStorage, so it disappears when the
 * browser is closed. That suits shared office PCs. The expiry time is stored
 * with it, so an expired session is noticed before any request is made.
 */

import { api } from "./api.js";

const TOKEN_KEY = "itsm.token";
const USER_KEY = "itsm.user";
const EXPIRES_KEY = "itsm.expires";

/** Pages a role starts on after signing in. */
const LANDING_PAGE = {
  super_admin: "dashboard.html",
  it_admin: "dashboard.html",
  manager: "dashboard.html",
  employee: "tickets.html",
};

/** @returns {string|null} The access token, or null if missing or expired. */
export function getToken() {
  try {
    const token = sessionStorage.getItem(TOKEN_KEY);
    const expires = Number(sessionStorage.getItem(EXPIRES_KEY));
    if (!token || !expires || Date.now() >= expires) {
      return null;
    }
    return token;
  } catch {
    return null;
  }
}

/** @returns {object|null} The signed-in user's profile from the last sign-in. */
export function getUser() {
  try {
    const raw = sessionStorage.getItem(USER_KEY);
    return raw && getToken() ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

/** @param {object} user Updated profile (for example after a language change). */
export function setUser(user) {
  try {
    sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch {
    // Not fatal: the next page load fetches the profile again.
  }
}

/** Forget the session in this browser tab. */
export function clearSession() {
  try {
    for (const key of [TOKEN_KEY, USER_KEY, EXPIRES_KEY]) {
      sessionStorage.removeItem(key);
    }
  } catch {
    // Nothing stored, nothing to clear.
  }
}

/**
 * Sign in and keep the session. Throws ApiError on failure.
 * @param {string} email
 * @param {string} password
 * @returns {Promise<object>} The user profile.
 */
export async function signIn(email, password) {
  const result = await api("/auth/login", {
    method: "POST",
    body: { email, password },
    auth: false,
  });
  // Treat the session as expired 30 seconds early, so a request never leaves
  // with a token that runs out on the way.
  const expires = Date.now() + (result.expires_in - 30) * 1000;
  sessionStorage.setItem(TOKEN_KEY, result.access_token);
  sessionStorage.setItem(EXPIRES_KEY, String(expires));
  setUser(result.user);
  return result.user;
}

/** Sign out and return to the sign-in page. */
export function signOut() {
  clearSession();
  window.location.assign("index.html?reason=signed_out");
}

/**
 * @param {string} role
 * @returns {string} The page this role starts on.
 */
export function landingPage(role) {
  return LANDING_PAGE[role] || "tickets.html";
}

/**
 * Only accept a plain page name from the same site as a post-sign-in target,
 * so a crafted link cannot send the user to another website (open redirect).
 * @param {string|null} next
 * @returns {string|null}
 */
export function safeNextPage(next) {
  return next && /^[a-z]+\.html$/.test(next) && next !== "index.html" ? next : null;
}

/**
 * Guard for protected pages: returns the user, or redirects and returns null.
 * The server checks permissions on every request; this only avoids showing
 * a page the user cannot use.
 * @param {string[]} [roles] Roles allowed on this page; omit for any signed-in user.
 * @returns {object|null}
 */
export function requireUser(roles) {
  const user = getUser();
  if (!user) {
    const next = encodeURIComponent(window.location.pathname.split("/").pop() || "");
    window.location.assign(`index.html?next=${next}`);
    return null;
  }
  if (roles && !roles.includes(user.role)) {
    window.location.assign(landingPage(user.role));
    return null;
  }
  return user;
}
