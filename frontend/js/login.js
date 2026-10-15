/**
 * Sign-in page logic. Kept in its own file because the Content Security
 * Policy does not allow inline scripts.
 */

import { ApiError, api } from "./api.js";
import { getUser, landingPage, safeNextPage, setUser, signIn } from "./auth.js";
import { DEFAULT_LANG, loadLang, savedLang, t, tError } from "./i18n.js";
import { languageSwitch } from "./nav.js";

const params = new URLSearchParams(window.location.search);

/** Go to the requested page (if safe) or the role's start page. */
function goOn(user) {
  window.location.assign(safeNextPage(params.get("next")) || landingPage(user.role));
}

/**
 * Switch the password between hidden and readable, and keep the toggle's
 * text and state in step (aria-pressed tells screen readers which it is).
 * @param {HTMLInputElement} input
 * @param {boolean} visible
 */
function showPassword(input, visible) {
  const toggle = document.getElementById("password-toggle");
  input.type = visible ? "text" : "password";
  toggle.setAttribute("aria-pressed", String(visible));
  toggle.dataset.i18n = visible ? "login.hide_password" : "login.show_password";
  toggle.dataset.i18nAriaLabel = visible ? "login.hide_password_label" : "login.show_password_label";
  toggle.textContent = t(toggle.dataset.i18n);
  toggle.setAttribute("aria-label", t(toggle.dataset.i18nAriaLabel));
}

/** Show/hide button and a Caps Lock warning for the password field. */
function setUpPasswordField(input) {
  const toggle = document.getElementById("password-toggle");
  toggle.addEventListener("click", () => {
    showPassword(input, input.type === "password");
    input.focus();
  });
  // Leaving the page (or the tab) hides the password again.
  window.addEventListener("pagehide", () => showPassword(input, false));
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      showPassword(input, false);
    }
  });

  const caps = document.getElementById("caps-warning");
  const checkCaps = (event) => {
    if (typeof event.getModifierState === "function") {
      caps.hidden = !event.getModifierState("CapsLock");
    }
  };
  input.addEventListener("keydown", checkCaps);
  input.addEventListener("keyup", checkCaps);
  input.addEventListener("blur", () => {
    caps.hidden = true;
  });
}

async function main() {
  // Already signed in: skip the form.
  const existing = getUser();
  if (existing) {
    goOn(existing);
    return;
  }

  document.getElementById("lang-slot").replaceWith(languageSwitch({ signedIn: false }));
  await loadLang(savedLang() || DEFAULT_LANG);

  const notice = document.getElementById("login-notice");
  const errorBox = document.getElementById("login-error");
  const form = document.getElementById("login-form");
  const submit = document.getElementById("login-submit");

  // Messages are stored as keys and codes, so a language switch re-renders them.
  const noticeKey = { expired: "login.session_expired", signed_out: "login.signed_out" }[
    params.get("reason")
  ];
  let errorKey = null; // a translation key (local check) ...
  let errorCode = null; // ... or an API error code

  function render() {
    notice.hidden = !noticeKey;
    notice.textContent = noticeKey ? t(noticeKey) : "";
    errorBox.hidden = !errorKey && !errorCode;
    errorBox.textContent = errorKey ? t(errorKey) : errorCode ? tError(errorCode) : "";
  }
  render();
  document.addEventListener("langchange", render);
  setUpPasswordField(form.password);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const email = form.email.value.trim();
    const password = form.password.value;
    errorKey = null;
    errorCode = null;
    if (!email || !password) {
      errorKey = "login.required";
      render();
      return;
    }

    // Hide the password again before it leaves the page, so it is never left
    // readable on screen or offered to the browser as plain text.
    showPassword(form.password, false);
    submit.disabled = true;
    submit.textContent = t("login.submitting");
    render();
    try {
      let user = await signIn(email, password);
      // A language picked on this page before signing in wins and is saved on
      // the account. Without a pick, the account's saved language is used.
      const picked = savedLang();
      if (picked && picked !== user.language) {
        try {
          user = await api("/auth/me/language", { method: "PUT", body: { language: picked } });
          setUser(user);
        } catch {
          // Signing in still succeeded; the language can be saved later.
        }
      } else if (!picked) {
        await loadLang(user.language, { remember: true });
      }
      goOn(user);
    } catch (error) {
      errorCode = error instanceof ApiError ? error.code : "UNKNOWN_ERROR";
      submit.disabled = false;
      submit.textContent = t("login.submit");
      render();
      form.password.select();
    }
  });
}

main();
