/**
 * Interface translations (Japanese by default, English optional).
 *
 * Only interface text is translated. Names, notes, ticket text, and other
 * data entered by people are always shown exactly as stored.
 *
 * Markup uses data attributes, applied by applyTranslations():
 *   data-i18n="key"             -> textContent
 *   data-i18n-placeholder="key" -> placeholder
 *   data-i18n-aria-label="key"  -> aria-label
 *   data-i18n-title="key"       -> title
 */

export const LANGUAGES = ["ja", "en"];
export const DEFAULT_LANG = "ja";
const STORAGE_KEY = "itsm.lang";
const LOCALES = { ja: "ja-JP", en: "en-US" };

let currentLang = DEFAULT_LANG;
let dictionary = {};
const cache = new Map();

/**
 * The language saved in this browser, or null if the user never chose one.
 * @returns {string|null}
 */
export function savedLang() {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return LANGUAGES.includes(value) ? value : null;
  } catch {
    // Storage can be blocked (private mode, strict settings); fall back to the default.
    return null;
  }
}

/** @param {string} code */
function saveLang(code) {
  try {
    localStorage.setItem(STORAGE_KEY, code);
  } catch {
    // Not fatal: the choice simply is not remembered in this browser.
  }
}

/** @returns {string} The active language code ("ja" or "en"). */
export function getLang() {
  return currentLang;
}

/**
 * Load a language file and make it active. Fires "langchange" on document.
 * @param {string} code "ja" or "en"; anything else falls back to Japanese.
 * @param {{remember?: boolean}} [options] remember=true saves the choice in this browser.
 */
export async function loadLang(code, { remember = false } = {}) {
  const lang = LANGUAGES.includes(code) ? code : DEFAULT_LANG;
  if (!cache.has(lang)) {
    const response = await fetch(`i18n/${lang}.json`, { cache: "no-cache" });
    if (!response.ok) {
      throw new Error(`Cannot load translations for ${lang}`);
    }
    cache.set(lang, await response.json());
  }
  dictionary = cache.get(lang);
  currentLang = lang;
  if (remember) {
    saveLang(lang);
  }
  document.documentElement.lang = lang;
  applyTranslations(document);
  document.dispatchEvent(new CustomEvent("langchange", { detail: { lang } }));
}

/**
 * Translate a key, filling {placeholders} from params.
 *
 * A missing key is never hidden: it is logged as an error and shown as
 * [[key]], so it gets noticed and fixed instead of silently showing nothing.
 * @param {string} key
 * @param {Record<string, string|number>} [params]
 * @returns {string}
 */
export function t(key, params = {}) {
  const template = dictionary[key];
  if (template === undefined) {
    console.error(`Missing translation for "${key}" in ${currentLang}`);
    return `[[${key}]]`;
  }
  return template.replace(/\{(\w+)\}/g, (match, name) =>
    name in params ? String(params[name]) : match,
  );
}

/**
 * @param {string} key
 * @returns {boolean} Whether the active language has this key.
 */
export function hasKey(key) {
  return key in dictionary;
}

/**
 * Translate an API error code. Unknown codes fall back to a generic message.
 * @param {string} code
 * @returns {string}
 */
export function tError(code) {
  const key = `error.${code}`;
  return key in dictionary ? dictionary[key] : t("error.UNKNOWN_ERROR");
}

/**
 * Parse an ISO string. A plain date ("2026-10-15") is read as a local calendar
 * date; new Date() would read it as UTC midnight and show the previous day in
 * time zones west of UTC.
 * @param {string} value
 * @returns {Date}
 */
export function parseDate(value) {
  const plain = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  return plain ? new Date(Number(plain[1]), Number(plain[2]) - 1, Number(plain[3])) : new Date(value);
}

/**
 * Format a date or date-time for the active language (ja-JP or en-US).
 * @param {string|Date|null|undefined} value ISO string or Date.
 * @param {{time?: boolean}} [options] time=true includes hours and minutes.
 * @returns {string} An empty string for empty values.
 */
export function fmtDate(value, { time = false } = {}) {
  if (!value) {
    return "";
  }
  const date = value instanceof Date ? value : parseDate(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  const options = { year: "numeric", month: "2-digit", day: "2-digit" };
  if (time) {
    Object.assign(options, { hour: "2-digit", minute: "2-digit" });
  }
  return new Intl.DateTimeFormat(LOCALES[currentLang], options).format(date);
}

/**
 * Fill every translatable element inside root. Uses textContent only, so
 * translations can never inject HTML.
 * @param {ParentNode} root
 */
export function applyTranslations(root) {
  const bindings = [
    ["data-i18n", (el, text) => (el.textContent = text)],
    ["data-i18n-placeholder", (el, text) => el.setAttribute("placeholder", text)],
    ["data-i18n-aria-label", (el, text) => el.setAttribute("aria-label", text)],
    ["data-i18n-title", (el, text) => el.setAttribute("title", text)],
  ];
  for (const [attribute, apply] of bindings) {
    for (const el of root.querySelectorAll(`[${attribute}]`)) {
      apply(el, t(el.getAttribute(attribute)));
    }
  }
}
