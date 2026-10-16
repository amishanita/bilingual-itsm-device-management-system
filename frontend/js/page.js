/**
 * Start-up shared by every signed-in page: check the session, load the
 * language, and draw the top bar. Each page module calls startPage() first.
 */

import { requireUser } from "./auth.js";
import { mountChatWidget } from "./chat-widget.js";
import { DEFAULT_LANG, getLang, loadLang, savedLang, t } from "./i18n.js";
import { renderTopBar } from "./nav.js";

/**
 * @param {string} activePage File name of the page, for example "dashboard.html".
 * @param {string[]} [roles] Roles allowed on the page; omit for any signed-in user.
 * @returns {Promise<object|null>} The user, or null when the browser is being redirected.
 */
export async function startPage(activePage, roles) {
  const user = requireUser(roles);
  if (!user) {
    return null;
  }
  // The choice made in this browser wins; otherwise the account's language.
  await loadLang(savedLang() || user.language || DEFAULT_LANG);
  renderTopBar(user, activePage);
  // The helpdesk chat sits on every signed-in page. It loads in the background
  // and never blocks the page itself.
  mountChatWidget().catch((error) => console.warn("Chat widget could not start", error));
  return user;
}

/**
 * Create an element with attributes and optional text (always textContent).
 * @param {string} tag
 * @param {Record<string, string>} [attributes]
 * @param {string|number} [text]
 * @returns {HTMLElement}
 */
export function el(tag, attributes = {}, text) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    node.setAttribute(name, value);
  }
  if (text !== undefined) {
    node.textContent = String(text);
  }
  return node;
}

/**
 * A date as "YYYY-MM-DD" in the browser's time zone (toISOString would use UTC
 * and give yesterday's date in Japan before 9:00).
 * @param {Date} date
 * @returns {string}
 */
export function localDate(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/**
 * Format a whole number for the active language (1,234 in both ja and en).
 * @param {number} value
 * @returns {string}
 */
export function fmtNumber(value) {
  return new Intl.NumberFormat(getLang() === "en" ? "en-US" : "ja-JP").format(value);
}

/**
 * Show a loading message, an error with a retry button, or nothing.
 * @param {HTMLElement} box The status element of the page.
 * @param {{state: "loading"|"error"|"done", message?: string, onRetry?: () => void}} options
 */
export function showStatus(box, { state, message, onRetry }) {
  box.replaceChildren();
  box.hidden = state === "done";
  box.className = state === "error" ? "alert" : "notice";
  box.setAttribute("role", state === "error" ? "alert" : "status");
  if (state === "loading") {
    box.textContent = t("common.loading");
  } else if (state === "error") {
    box.append(el("span", {}, message));
    if (onRetry) {
      const retry = el("button", { type: "button", class: "button button-quiet retry" }, t("common.retry"));
      retry.addEventListener("click", onRetry);
      box.append(retry);
    }
  }
}
