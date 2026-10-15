/**
 * Shared top bar: app name, role-aware navigation, language switch, the
 * signed-in user, and sign-out. Built with DOM methods and textContent only.
 */

import { api } from "./api.js";
import { applyTranslations, getLang, loadLang, t } from "./i18n.js";
import { setUser, signOut } from "./auth.js";

/**
 * Navigation entries and the roles that see them. The server enforces the
 * same rules on every request; hiding links only keeps the menu relevant.
 */
export const NAV_ITEMS = [
  { page: "dashboard.html", key: "nav.dashboard", roles: ["super_admin", "it_admin", "manager"] },
  { page: "devices.html", key: "nav.devices", roles: ["super_admin", "it_admin", "manager", "employee"] },
  { page: "kitting.html", key: "nav.kitting", roles: ["super_admin", "it_admin"] },
  { page: "loans.html", key: "nav.loans", roles: ["super_admin", "it_admin", "manager"] },
  { page: "employees.html", key: "nav.employees", roles: ["super_admin", "it_admin", "manager"] },
  { page: "tickets.html", key: "nav.tickets", roles: ["super_admin", "it_admin", "manager", "employee"] },
  { page: "faq.html", key: "nav.faq", roles: ["super_admin", "it_admin", "manager", "employee"] },
  { page: "users.html", key: "nav.users", roles: ["super_admin"] },
];

/**
 * @param {string} tag
 * @param {Record<string, string>} [attributes]
 * @param {string} [text]
 * @returns {HTMLElement}
 */
function el(tag, attributes = {}, text) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    node.setAttribute(name, value);
  }
  if (text !== undefined) {
    node.textContent = text;
  }
  return node;
}

/**
 * The 日本語 | EN switch. Saves the choice in this browser and, when signed
 * in, on the user's account too.
 * @param {{signedIn: boolean}} options
 * @returns {HTMLElement}
 */
export function languageSwitch({ signedIn }) {
  const group = el("div", { class: "lang-switch", role: "group", "data-i18n-aria-label": "lang.switch" });
  for (const code of ["ja", "en"]) {
    const button = el("button", {
      type: "button",
      class: "lang-button",
      lang: code,
      "data-lang": code,
      "data-i18n": `lang.${code}`,
    });
    button.addEventListener("click", async () => {
      if (code === getLang()) {
        return;
      }
      await loadLang(code, { remember: true });
      if (signedIn) {
        try {
          setUser(await api("/auth/me/language", { method: "PUT", body: { language: code } }));
        } catch (error) {
          // The page is already switched; saving on the account can be retried later.
          console.warn("Could not save the language on the account", error);
        }
      }
    });
    group.append(button);
  }
  const markActive = () => {
    for (const button of group.querySelectorAll("button")) {
      button.setAttribute("aria-pressed", String(button.dataset.lang === getLang()));
    }
  };
  markActive();
  document.addEventListener("langchange", markActive);
  return group;
}

/**
 * Render the top bar into the page's <header id="topbar">.
 * @param {object} user The signed-in user.
 * @param {string} activePage File name of the current page, for aria-current.
 */
export function renderTopBar(user, activePage) {
  const header = document.getElementById("topbar");
  header.replaceChildren();

  const brand = el("a", { class: "brand", href: "index.html", "data-i18n": "app.short_name" });
  const toggle = el("button", {
    type: "button",
    class: "menu-toggle",
    "aria-expanded": "false",
    "aria-controls": "main-nav",
    "data-i18n": "nav.menu",
  });
  const nav = el("nav", { id: "main-nav", class: "main-nav", "data-i18n-aria-label": "nav.main" });
  const list = el("ul");
  for (const item of NAV_ITEMS.filter((entry) => entry.roles.includes(user.role))) {
    const link = el("a", { href: item.page, "data-i18n": item.key });
    if (item.page === activePage) {
      link.setAttribute("aria-current", "page");
    }
    const entry = el("li");
    entry.append(link);
    list.append(entry);
  }
  nav.append(list);
  toggle.addEventListener("click", () => {
    const open = nav.classList.toggle("open");
    toggle.setAttribute("aria-expanded", String(open));
  });

  // The user's own name is data, so it is shown as stored and never translated.
  const displayName = user.employee ? user.employee.name : user.email;
  const who = el("span", { class: "who" });
  const renderWho = () => {
    who.textContent = t("nav.signed_in_as", { name: displayName });
  };
  renderWho();
  document.addEventListener("langchange", renderWho);

  const logout = el("button", { type: "button", class: "button button-quiet", "data-i18n": "nav.logout" });
  logout.addEventListener("click", signOut);

  const tools = el("div", { class: "tools" });
  tools.append(languageSwitch({ signedIn: true }), who, logout);
  header.append(brand, toggle, nav, tools);
  applyTranslations(header);
}
